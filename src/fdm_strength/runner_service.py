"""Formal Run lifecycle and isolated Docker stage execution."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import socket
import tarfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from fdm_strength.run_models import ArtifactReference, Run, StageRecord
from fdm_strength.run_store import ArtifactStore, RunStore
from fdm_strength.stage_contract import (
    StageContract,
    StageInput,
    canonical_contract_bytes,
)
from fdm_strength.study_models import StudyWorkspaceV3, migrate_workspace_v2_to_v3

DEFAULT_IMAGE = "styrkeanalyse-fdm:exp-reduction"
MAX_INPUT_BYTES = 24 * 1024 * 1024
STAGE_TIMEOUT_SECONDS = 120
STAGE_CPU_COUNT = 1
STAGE_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
MAX_STAGE_OUTPUT_BYTES = 64 * 1024 * 1024


class RunInputFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_base64: str = Field(min_length=1)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("filename cannot contain a NUL character")
        return value


class RunSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: str = Field(pattern=r"^(tensile|campaign)$")
    input_file: RunInputFile
    parameters: dict[str, Any]
    upstream_run_ids: tuple[str, ...] = ()

    @field_validator("upstream_run_ids")
    @classmethod
    def validate_upstream_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        try:
            canonical = tuple(str(uuid.UUID(value)) for value in values)
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("upstream_run_ids must contain UUIDs") from error
        if canonical != values or len(set(values)) != len(values):
            raise ValueError("upstream run IDs must be unique canonical UUIDs")
        return values


@dataclass(frozen=True)
class StageImage:
    digest: str
    git_commit: str
    git_dirty: bool | None


@dataclass(frozen=True)
class StageExecution:
    success: bool
    outputs: dict[str, bytes]
    stdout: bytes
    stderr: bytes
    started_at: datetime
    completed_at: datetime
    error: str | None


class DockerStageExecutor:
    """Runs a baked image with no network, source mounts, or writable root."""

    def __init__(self, *, timeout_seconds: int = STAGE_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds

    def inspect_image(self, image_reference: str | None = None) -> StageImage:
        import docker

        client = docker.from_env(timeout=self.timeout_seconds)
        try:
            image = client.images.get(image_reference or DEFAULT_IMAGE)
            labels = (image.attrs.get("Config") or {}).get("Labels") or {}
            commit = labels.get("fdm.git.commit") or labels.get("org.opencontainers.image.revision")
            dirty = labels.get("fdm.git.dirty")
            return StageImage(
                digest=image.id,
                git_commit=commit if isinstance(commit, str) and commit else "unknown",
                git_dirty=(dirty.lower() == "true")
                if dirty and dirty.lower() in {"true", "false"}
                else None,
            )
        finally:
            client.close()

    def execute(
        self,
        contract_bytes: bytes,
        inputs: dict[str, bytes],
        image_digest: str,
    ) -> StageExecution:
        import docker

        started_at = datetime.now(timezone.utc)
        stdout = b""
        stderr = b""
        container = None
        client = docker.from_env(timeout=self.timeout_seconds)
        try:
            container = client.containers.create(
                image_digest,
                command=("python", "-c", "import time; time.sleep(300)"),
                name=f"fdm-stage-{uuid.uuid4().hex}",
                user="10001:10001",
                network_mode="none",
                read_only=True,
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                pids_limit=128,
                mem_limit=STAGE_MEMORY_LIMIT_BYTES,
                nano_cpus=STAGE_CPU_COUNT * 1_000_000_000,
                tmpfs={
                    "/work": ("rw,noexec,nosuid,nodev,size=134217728,uid=10001,gid=10001,mode=0770")
                },
            )
            container.start()
            entries: dict[str, bytes] = {"run.json": contract_bytes}
            for digest, content in inputs.items():
                input_name = _contract_input_name(contract_bytes, digest)
                entries[f"in/{input_name}"] = content
            _send_archive_to_work(client, container, _make_tar(entries), self.timeout_seconds)

            stage_stdout, stage_stderr, exit_code = self._exec_with_timeout(container)
            stdout = stage_stdout
            stderr = stage_stderr
            outputs: dict[str, bytes] = {}
            if exit_code == 0:
                contract = StageContract.model_validate_json(contract_bytes)
                outputs = _read_stage_outputs(
                    client, container, contract.expected_outputs, self.timeout_seconds
                )
            success = exit_code == 0
            error = (
                None
                if success
                else _bounded_error(stderr or stdout or b"stage exited unsuccessfully")
            )
            return StageExecution(
                success=success,
                outputs=outputs,
                stdout=stdout,
                stderr=stderr,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                error=error,
            )
        except Exception as error:
            return StageExecution(
                success=False,
                outputs={},
                stdout=stdout,
                stderr=str(error).encode("utf-8", errors="replace")[:16_000],
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                error=_bounded_error(str(error).encode("utf-8", errors="replace")),
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True, v=True)
                except Exception:
                    pass
            client.close()

    def _exec_with_timeout(self, container: Any) -> tuple[bytes, bytes, int]:
        timer = threading.Timer(self.timeout_seconds, _kill_container, args=(container,))
        timer.daemon = True
        timer.start()
        start = time.monotonic()
        try:
            result = container.exec_run(
                ("python", "-m", "fdm_strength.exp_reduction_stage"),
                workdir="/work",
                user="10001:10001",
                demux=True,
            )
        finally:
            timer.cancel()
        if time.monotonic() - start >= self.timeout_seconds:
            raise TimeoutError(f"stage exceeded {self.timeout_seconds} seconds")
        output = result.output
        if isinstance(output, tuple):
            stdout = output[0] or b""
            stderr = output[1] or b""
        else:
            stdout, stderr = output or b"", b""
        return stdout, stderr, int(result.exit_code)


class RunService:
    def __init__(self, data_root: str | os.PathLike[str], *, executor: Any | None = None):
        self.artifacts = ArtifactStore(data_root)
        self.runs = RunStore(data_root)
        self.executor = executor or DockerStageExecutor()

    def submit(
        self,
        submission: RunSubmission,
        *,
        image_reference: str | None = None,
    ) -> tuple[Run, dict[str, Any] | None]:
        input_bytes = _decode_input(submission.input_file)
        computed_digest = hashlib.sha256(input_bytes).hexdigest()
        if computed_digest != submission.input_file.sha256:
            raise ValueError("uploaded file SHA-256 does not match its provenance")
        if len(input_bytes) > MAX_INPUT_BYTES:
            raise ValueError(f"input file exceeds {MAX_INPUT_BYTES // (1024 * 1024)} MB")
        _validate_input_media_type(submission.operation, submission.input_file.media_type)
        parameters = _json_object(submission.parameters, "parameters")
        upstream_runs = self._resolve_upstream_runs(submission, input_bytes)

        run_id = str(uuid.uuid4())
        source_artifact = self.artifacts.put_bytes(
            input_bytes,
            media_type=submission.input_file.media_type,
        )
        stage_input = StageInput(
            name="source.csv" if submission.operation == "tensile" else "workspace.json",
            sha256=source_artifact.sha256,
            size_bytes=source_artifact.size_bytes,
            media_type=source_artifact.media_type,
        )
        stage_parameters = {**parameters, "_source_filename": submission.input_file.filename}
        contract = StageContract(
            schema_version=1,
            run_id=run_id,
            stage_id="experimental-reduction",
            operation=submission.operation,
            inputs=(stage_input,),
            parameters=stage_parameters,
            expected_outputs=("result.json", "provenance.json"),
        )
        contract_bytes = canonical_contract_bytes(contract)
        spec_artifact = self.artifacts.put_bytes(
            contract_bytes,
            media_type="application/vnd.styrkeanalyse.stage-contract+json",
        )
        direct_inputs = (source_artifact,)
        run_inputs = _unique_artifacts(
            (
                *direct_inputs,
                *(
                    reference
                    for parent in upstream_runs
                    for reference in (*parent.input_artifacts, *parent.output_artifacts)
                ),
            )
        )
        started_before_inspect = datetime.now(timezone.utc)
        try:
            image = self.executor.inspect_image(image_reference)
        except Exception as error:
            run = Run(
                id=run_id,
                created_at=started_before_inspect,
                operation=submission.operation,
                status="failed",
                spec_artifact=spec_artifact,
                input_artifacts=run_inputs,
                output_artifacts=(),
                result_artifact=None,
                stages=(),
                upstream_run_ids=submission.upstream_run_ids,
                error=_bounded_error(str(error).encode("utf-8", errors="replace")),
            )
            self.runs.create(run)
            return run, None

        execution = self.executor.execute(
            contract_bytes,
            {source_artifact.sha256: input_bytes},
            image.digest,
        )
        outputs: list[ArtifactReference] = []
        result_artifact: ArtifactReference | None = None
        provenance_artifact: ArtifactReference | None = None
        result_value: dict[str, Any] | None = None
        if execution.success:
            output_bytes = execution.outputs.get("result.json")
            if output_bytes is None:
                execution = _replace_execution_failure(execution, "stage omitted result.json")
            else:
                try:
                    result_payload = json.loads(output_bytes)
                    if (
                        not isinstance(result_payload, dict)
                        or result_payload.get("schema_version") != 1
                        or result_payload.get("run_id") != run_id
                        or not isinstance(result_payload.get("result"), dict)
                    ):
                        raise ValueError("stage result has an invalid envelope")
                    provenance_bytes = execution.outputs.get("provenance.json")
                    if provenance_bytes is None:
                        raise ValueError("stage omitted provenance.json")
                    provenance = json.loads(provenance_bytes)
                    expected_provenance = {
                        "schema_version": 1,
                        "run_id": run_id,
                        "stage_id": contract.stage_id,
                        "operation": contract.operation,
                        "inputs": [
                            {
                                "name": item.name,
                                "sha256": item.sha256,
                                "size_bytes": item.size_bytes,
                            }
                            for item in contract.inputs
                        ],
                        "outputs": [
                            {
                                "name": "result.json",
                                "sha256": hashlib.sha256(output_bytes).hexdigest(),
                                "size_bytes": len(output_bytes),
                            }
                        ],
                    }
                    if provenance != expected_provenance:
                        raise ValueError(
                            "stage provenance does not match its immutable inputs and outputs"
                        )
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    execution = _replace_execution_failure(execution, str(error))
                else:
                    result_artifact = self.artifacts.put_bytes(
                        output_bytes,
                        media_type="application/vnd.styrkeanalyse.experimental-reduction+json",
                    )
                    provenance_artifact = self.artifacts.put_bytes(
                        provenance_bytes,
                        media_type="application/vnd.styrkeanalyse.stage-provenance+json",
                    )
                    outputs.append(result_artifact)
                    outputs.append(provenance_artifact)
                    result_value = result_payload["result"]

        logs = _logs_bytes(execution.stdout, execution.stderr)
        log_artifact = (
            self.artifacts.put_bytes(logs, media_type="text/plain; charset=utf-8") if logs else None
        )
        if log_artifact is not None:
            outputs.append(log_artifact)
        stage = StageRecord(
            stage_id="experimental-reduction",
            operation=submission.operation,
            status="succeeded" if execution.success else "failed",
            image_digest=image.digest,
            command=("python", "-m", "fdm_strength.exp_reduction_stage"),
            input_artifacts=(spec_artifact, *direct_inputs),
            output_artifacts=tuple(
                artifact
                for artifact in (result_artifact, provenance_artifact)
                if artifact is not None
            ),
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            duration_ms=max(
                0, round((execution.completed_at - execution.started_at).total_seconds() * 1000)
            ),
            git_commit=image.git_commit,
            git_dirty=image.git_dirty,
            cpu_count=STAGE_CPU_COUNT,
            memory_limit_bytes=STAGE_MEMORY_LIMIT_BYTES,
        )
        run = Run(
            id=run_id,
            created_at=execution.completed_at,
            operation=submission.operation,
            status="succeeded" if execution.success else "failed",
            spec_artifact=spec_artifact,
            input_artifacts=run_inputs,
            output_artifacts=tuple(outputs),
            result_artifact=result_artifact,
            stages=(stage,),
            upstream_run_ids=submission.upstream_run_ids,
            error=execution.error,
        )
        self.runs.create(run)
        return run, result_value

    def replay(self, run_id: str) -> tuple[Run, dict[str, Any] | None]:
        original = self.runs.get(run_id)
        if original.status != "succeeded" or not original.stages:
            raise ValueError("only successful Runs can be replayed")
        try:
            contract = StageContract.model_validate_json(
                self.artifacts.get_bytes(original.spec_artifact.sha256)
            )
        except (FileNotFoundError, ValidationError, ValueError) as error:
            raise ValueError(f"saved Run {run_id} has an unreadable stage contract") from error
        if contract.run_id != original.id or len(contract.inputs) != 1:
            raise ValueError("saved Run stage contract does not match its immutable record")
        input_info = contract.inputs[0]
        source_bytes = self.artifacts.get_bytes(input_info.sha256)
        parameters = dict(contract.parameters)
        filename = parameters.pop("_source_filename", "input.csv")
        replay_submission = RunSubmission(
            operation=contract.operation,
            input_file=RunInputFile(
                filename=filename,
                media_type=input_info.media_type,
                sha256=input_info.sha256,
                content_base64=base64.b64encode(source_bytes).decode("ascii"),
            ),
            parameters=parameters,
            upstream_run_ids=original.upstream_run_ids,
        )
        return self.submit(
            replay_submission,
            image_reference=original.stages[0].image_digest,
        )

    def read_run(self, run_id: str) -> Run:
        return self.runs.get(run_id)

    def read_artifact(self, digest: str) -> bytes:
        return self.artifacts.get_bytes(digest)

    def _resolve_upstream_runs(
        self,
        submission: RunSubmission,
        input_bytes: bytes,
    ) -> tuple[Run, ...]:
        linked_run_ids: set[str] = set()
        workspace: dict[str, Any] | None = None
        if submission.operation == "campaign":
            try:
                workspace = json.loads(input_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("campaign input must be a JSON study workspace") from error
            if not isinstance(workspace, dict):
                raise ValueError("campaign input must be a JSON study workspace")
            try:
                if workspace.get("version") == 2:
                    workspace = migrate_workspace_v2_to_v3(workspace)
                else:
                    StudyWorkspaceV3.model_validate(workspace)
            except (ValidationError, ValueError) as error:
                raise ValueError(f"invalid campaign workspace: {error}") from error
            specimens = workspace.get("specimens", [])
            if not isinstance(specimens, list):
                raise ValueError("campaign specimens must be a list")
            for specimen in specimens:
                if not isinstance(specimen, dict):
                    raise ValueError("campaign specimen must be an object")
                test_runs = specimen.get("test_runs", [])
                if not isinstance(test_runs, list):
                    raise ValueError("specimen test_runs must be a list")
                for test_run in test_runs:
                    if not isinstance(test_run, dict):
                        raise ValueError("specimen test run must be an object")
                    if test_run.get("run_id"):
                        if not isinstance(test_run["run_id"], str):
                            raise ValueError("linked specimen Run IDs must be strings")
                        linked_run_ids.add(test_run["run_id"])
            if linked_run_ids != set(submission.upstream_run_ids):
                raise ValueError("campaign upstream runs must match its linked specimen Runs")
        elif submission.upstream_run_ids:
            raise ValueError("tensile Runs cannot depend on upstream Runs")

        resolved: list[Run] = []
        for upstream_id in submission.upstream_run_ids:
            try:
                parent = self.runs.get(upstream_id)
            except FileNotFoundError as error:
                raise ValueError(f"upstream Run {upstream_id} was not found") from error
            if parent.status != "succeeded" or parent.operation != "tensile":
                raise ValueError(f"upstream Run {upstream_id} is not a successful tensile Run")
            resolved.append(parent)
        if workspace is not None:
            self._validate_campaign_run_links(workspace, resolved)
        return tuple(resolved)

    def _validate_campaign_run_links(self, workspace: dict[str, Any], parents: list[Run]) -> None:
        parent_by_id = {parent.id: parent for parent in parents}
        for specimen in workspace.get("specimens", []):
            if not isinstance(specimen, dict):
                raise ValueError("campaign specimen must be an object")
            geometry = specimen.get("geometry") or {}
            if not isinstance(geometry, dict):
                raise ValueError("linked specimen geometry must be an object")
            for test_run in specimen.get("test_runs", []):
                if not isinstance(test_run, dict):
                    raise ValueError("specimen test run must be an object")
                if not test_run.get("run_id"):
                    continue
                input_file = test_run.get("input_file")
                if not isinstance(input_file, dict):
                    raise ValueError("linked test run requires input-file provenance")
                parent = parent_by_id[test_run["run_id"]]
                try:
                    contract = StageContract.model_validate_json(
                        self.artifacts.get_bytes(parent.spec_artifact.sha256)
                    )
                    parent_result = json.loads(
                        self.artifacts.get_bytes(parent.result_artifact.sha256)
                    )["result"]
                except (FileNotFoundError, KeyError, ValidationError, ValueError) as error:
                    raise ValueError(
                        f"linked Run {parent.id} has incomplete immutable artifacts"
                    ) from error
                parameters = contract.parameters
                if (
                    len(contract.inputs) != 1
                    or input_file.get("sha256") != contract.inputs[0].sha256
                ):
                    raise ValueError(f"specimen input file does not match linked Run {parent.id}")
                if test_run.get("result") != parent_result.get("analysis"):
                    raise ValueError(f"specimen result does not match linked Run {parent.id}")
                setting_pairs = {
                    "forceColumn": "force_column",
                    "displacementColumn": "displacement_column",
                    "forceUnit": "force_unit",
                    "displacementUnit": "displacement_unit",
                    "decimalSeparator": "decimal_separator",
                    "tensionDirection": "tension_direction",
                }
                settings = test_run.get("settings") or {}
                if not isinstance(settings, dict):
                    raise ValueError("linked test-run settings must be an object")
                if any(
                    settings.get(saved) != parameters.get(source)
                    for saved, source in setting_pairs.items()
                ):
                    raise ValueError(f"specimen settings do not match linked Run {parent.id}")
                dimension_pairs = {
                    "width_mm": "width_mm",
                    "thickness_mm": "thickness_mm",
                    "gauge_length_mm": "gauge_length_mm",
                }
                if any(
                    geometry.get(saved) != parameters.get(source)
                    for saved, source in dimension_pairs.items()
                ):
                    raise ValueError(f"specimen dimensions do not match linked Run {parent.id}")
                if specimen.get("id") != parameters.get("specimen_id"):
                    raise ValueError(f"specimen identity does not match linked Run {parent.id}")
                if test_run.get("sensor_source") != parameters.get("sensor_source"):
                    raise ValueError(f"sensor source does not match linked Run {parent.id}")
                correction = test_run.get("compliance_correction") or {}
                recorded_correction = parameters.get("compliance_correction") or {}
                if not isinstance(correction, dict) or not isinstance(recorded_correction, dict):
                    raise ValueError("linked compliance correction must be an object")
                for key in ("method", "compliance_mm_per_n", "calibration_source"):
                    if correction.get(key) != recorded_correction.get(key):
                        raise ValueError(
                            f"compliance metadata does not match linked Run {parent.id}"
                        )


def _decode_input(source: RunInputFile) -> bytes:
    try:
        content = base64.b64decode(source.content_base64, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("content_base64 must contain valid base64") from error
    return content


def _validate_input_media_type(operation: str, media_type: str) -> None:
    if operation == "tensile" and media_type not in {
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.ms-excel",
    }:
        raise ValueError("tensile input must be a CSV or tab-separated file")
    if operation == "campaign" and media_type not in {
        "application/json",
        "application/vnd.styrkeanalyse.study+json",
    }:
        raise ValueError("campaign input must be a JSON study workspace")


def _json_object(value: dict[str, Any], label: str) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must contain finite JSON values") from error


def _unique_artifacts(artifacts: tuple[ArtifactReference, ...]) -> tuple[ArtifactReference, ...]:
    by_digest: dict[str, ArtifactReference] = {}
    for artifact in artifacts:
        by_digest.setdefault(artifact.sha256, artifact)
    return tuple(by_digest.values())


def _logs_bytes(stdout: bytes, stderr: bytes) -> bytes:
    parts = []
    if stdout:
        parts.append(b"--- stdout ---\n" + stdout)
    if stderr:
        parts.append(b"--- stderr ---\n" + stderr)
    return b"\n".join(parts)


def _bounded_error(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")[:4000] or "stage failed without details"


def _replace_execution_failure(execution: StageExecution, error: str) -> StageExecution:
    return StageExecution(
        success=False,
        outputs={},
        stdout=execution.stdout,
        stderr=execution.stderr,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        error=error[:4000],
    )


def _make_tar(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for directory in ("in/", "out/"):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o770
            info.uid = 10001
            info.gid = 10001
            archive.addfile(info)
        for name, content in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o444 if name == "run.json" else 0o400
            info.uid = 10001
            info.gid = 10001
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _send_archive_to_work(
    client: Any, container: Any, archive: bytes, timeout_seconds: int
) -> None:
    transfer_command = (
        "python",
        "-c",
        "import sys,tarfile; "
        "archive=tarfile.open(fileobj=sys.stdin.buffer, mode='r|'); "
        "archive.extractall('/work', filter='data')",
    )
    created = client.api.exec_create(
        container.id,
        transfer_command,
        stdin=True,
        stdout=False,
        stderr=False,
        tty=False,
        user="10001:10001",
        workdir="/work",
    )
    transfer_socket = client.api.exec_start(created["Id"], tty=False, socket=True)
    set_timeout = getattr(transfer_socket, "settimeout", None)
    if callable(set_timeout):
        set_timeout(timeout_seconds)
    timer = threading.Timer(timeout_seconds, _kill_container, args=(container,))
    timer.daemon = True
    timer.start()
    try:
        sendall = getattr(transfer_socket, "sendall", None)
        if callable(sendall):
            sendall(archive)
        else:
            write = getattr(transfer_socket, "write", None)
            if not callable(write):
                raise TypeError("Docker input stream does not support writing")
            remaining = memoryview(archive)
            while remaining:
                written = write(remaining)
                if not isinstance(written, int) or written <= 0:
                    raise OSError("Docker input stream stopped accepting stage files")
                remaining = remaining[written:]
        shutdown = getattr(transfer_socket, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown(socket.SHUT_WR)
            except (OSError, NotImplementedError):
                pass
    finally:
        try:
            transfer_socket.close()
        except OSError:
            pass
        timer.cancel()
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = client.api.exec_inspect(created["Id"])
        if not status.get("Running"):
            exit_code = status.get("ExitCode")
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"stage input transfer exceeded {timeout_seconds} seconds")
        time.sleep(0.05)
    if exit_code != 0:
        raise RuntimeError(f"stage input archive transfer failed with exit code {exit_code}")


def _read_stage_outputs(
    client: Any,
    container: Any,
    output_names: tuple[str, ...],
    timeout_seconds: int,
) -> dict[str, bytes]:
    names_literal = repr(output_names)
    export_command = (
        "python",
        "-c",
        "import sys,tarfile; "
        "archive=tarfile.open(fileobj=sys.stdout.buffer, mode='w|'); "
        f"[archive.add('/work/out/'+name, arcname=name, recursive=False) "
        f"for name in {names_literal}]; "
        "archive.close()",
    )
    created = client.api.exec_create(
        container.id,
        export_command,
        stdin=False,
        stdout=True,
        stderr=True,
        tty=False,
        user="10001:10001",
        workdir="/work",
    )
    timer = threading.Timer(timeout_seconds, _kill_container, args=(container,))
    timer.daemon = True
    timer.start()
    stdout = bytearray()
    stderr = bytearray()
    try:
        stream = client.api.exec_start(created["Id"], tty=False, stream=True, demux=True)
        for output, error in stream:
            if output:
                stdout.extend(output)
                if len(stdout) > MAX_STAGE_OUTPUT_BYTES:
                    raise ValueError("stage outputs exceed 64 MB")
            if error:
                stderr.extend(error)
                if len(stderr) > 16_000:
                    del stderr[16_000:]
    finally:
        timer.cancel()
        try:
            stream.close()
        except (UnboundLocalError, AttributeError, OSError):
            pass
    status = client.api.exec_inspect(created["Id"])
    exit_code = status.get("ExitCode")
    if exit_code != 0:
        details = bytes(stderr).decode("utf-8", errors="replace")
        message = f"stage output export failed with exit code {exit_code}: {details[:2000]}"
        raise RuntimeError(message)
    try:
        with tarfile.open(fileobj=io.BytesIO(stdout), mode="r:*") as archive:
            members = archive.getmembers()
            if {member.name for member in members} != set(output_names):
                raise ValueError("stage output archive does not match its declared outputs")
            outputs: dict[str, bytes] = {}
            for member in members:
                if not member.isfile():
                    raise ValueError(f"stage output {member.name} is not a regular file")
                content = archive.extractfile(member)
                if content is None:
                    raise ValueError(f"stage output {member.name} could not be read")
                outputs[member.name] = content.read()
    except tarfile.TarError as error:
        raise ValueError("stage output archive is invalid") from error
    return outputs


def _contract_input_name(contract_bytes: bytes, digest: str) -> str:
    contract = StageContract.model_validate_json(contract_bytes)
    for item in contract.inputs:
        if item.sha256 == digest:
            return item.name
    raise ValueError(f"artifact {digest} is not declared in the stage contract")


def _kill_container(container: Any) -> None:
    try:
        container.kill()
    except Exception:
        pass
