import base64
import hashlib
import json
import socket
from datetime import datetime, timezone
from threading import Thread
from urllib.request import Request, urlopen

import pytest
from pydantic import ValidationError

from fdm_strength.run_models import ArtifactReference, Run, StageRecord
from fdm_strength.run_store import ArtifactStore, RunStore
from fdm_strength.runner import create_runner_server
from fdm_strength.runner_service import (
    DockerStageExecutor,
    RunService,
    RunSubmission,
    StageExecution,
    _send_archive_to_work,
)
from fdm_strength.stage_contract import load_stage_contract


def test_artifacts_are_content_addressed_and_byte_preserving(tmp_path):
    store = ArtifactStore(tmp_path)
    original = b"force_N,travel_mm\r\n0,0\r\n"

    first = store.put_bytes(original, media_type="text/csv")
    second = store.put_bytes(original, media_type="text/csv")

    assert first == second
    assert first.sha256 == "cee8d050ec3a14c4ef49f0c2a4acf3b07003209128aaa0e166bfeb3ed00ab676"
    assert first.size_bytes == len(original)
    assert store.get_bytes(first.sha256) == original


def test_artifact_store_rejects_tampered_content(tmp_path):
    store = ArtifactStore(tmp_path)
    reference = store.put_bytes(b"original", media_type="text/plain")
    artifact_path = store.path_for(reference.sha256)
    artifact_path.write_bytes(b"changed")

    with pytest.raises(ValueError, match="digest mismatch"):
        store.get_bytes(reference.sha256)


def test_artifact_reference_and_run_records_are_strict_and_immutable():
    with pytest.raises(ValidationError):
        ArtifactReference(sha256="nope", size_bytes=1, media_type="text/plain")

    run = _sample_run()
    with pytest.raises(ValidationError):
        run.status = "failed"
    with pytest.raises(ValidationError):
        Run.model_validate({**run.model_dump(mode="json"), "mutable_extra": True})


def test_run_store_creates_immutable_records(tmp_path):
    store = RunStore(tmp_path)
    run = _sample_run()
    store.create(run)

    assert store.get(run.id) == run
    with pytest.raises(FileExistsError, match="immutable"):
        store.create(run)
    assert json.loads(store.path_for(run.id).read_text()) == run.model_dump(mode="json")


def test_run_store_rejects_malformed_or_misfiled_run(tmp_path):
    store = RunStore(tmp_path)
    malformed_id = "8e02d8f8-b1ab-4abc-9fe5-2f65173b6704"
    store.path_for(malformed_id).parent.mkdir(parents=True)
    store.path_for(malformed_id).write_text("{bad json")

    with pytest.raises(ValueError, match="invalid run record"):
        store.get(malformed_id)


def test_stage_contract_checks_input_digest_size_and_confines_names(tmp_path):
    source = b"force_N,travel_mm\n0,0\n"
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "in" / "source.csv").write_bytes(source)
    manifest = {
        "schema_version": 1,
        "run_id": "8e02d8f8-b1ab-4abc-9fe5-2f65173b6704",
        "stage_id": "experimental-reduction",
        "operation": "tensile",
        "inputs": [
            {
                "name": "source.csv",
                "sha256": hashlib.sha256(source).hexdigest(),
                "size_bytes": len(source),
                "media_type": "text/csv",
            }
        ],
        "parameters": {"force_column": "force_N"},
        "expected_outputs": ["result.json"],
    }
    (tmp_path / "run.json").write_text(json.dumps(manifest))

    contract = load_stage_contract(tmp_path)
    assert contract.inputs[0].name == "source.csv"

    manifest["inputs"][0]["name"] = "../source.csv"
    (tmp_path / "run.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="safe filename"):
        load_stage_contract(tmp_path)


def test_stage_contract_fails_closed_on_modified_input(tmp_path):
    source = b"expected"
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "in" / "source.csv").write_bytes(b"modified")
    manifest = {
        "schema_version": 1,
        "run_id": "8e02d8f8-b1ab-4abc-9fe5-2f65173b6704",
        "stage_id": "experimental-reduction",
        "operation": "tensile",
        "inputs": [
            {
                "name": "source.csv",
                "sha256": hashlib.sha256(source).hexdigest(),
                "size_bytes": len(source),
                "media_type": "text/csv",
            }
        ],
        "parameters": {},
        "expected_outputs": ["result.json"],
    }
    (tmp_path / "run.json").write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="digest mismatch"):
        load_stage_contract(tmp_path)


def test_archive_transfer_supports_file_like_docker_sockets():
    class FileLikeSocket:
        def __init__(self):
            self.received = bytearray()
            self.closed = False

        def write(self, content):
            chunk = bytes(content[:3])
            self.received.extend(chunk)
            return len(chunk)

        def close(self):
            self.closed = True

    class FakeDockerAPI:
        def __init__(self, stream):
            self.stream = stream

        def exec_create(self, *_args, **_kwargs):
            return {"Id": "transfer-exec"}

        def exec_start(self, *_args, **_kwargs):
            return self.stream

        def exec_inspect(self, _exec_id):
            return {"ExitCode": 0, "Running": False}

    class FakeContainer:
        id = "stage-container"

    payload = b"contract and source archive"
    stream = FileLikeSocket()
    client = type("FakeDockerClient", (), {"api": FakeDockerAPI(stream)})()

    _send_archive_to_work(client, FakeContainer(), payload, timeout_seconds=1)

    assert bytes(stream.received) == payload
    assert stream.closed


def test_archive_transfer_uses_writable_socket_inside_read_only_socketio():
    sender, receiver = socket.socketpair()
    stream = socket.SocketIO(sender, "r")

    class FakeDockerAPI:
        def exec_create(self, *_args, **_kwargs):
            return {"Id": "transfer-exec"}

        def exec_start(self, *_args, **_kwargs):
            return stream

        def exec_inspect(self, _exec_id):
            return {"ExitCode": 0, "Running": False}

    class FakeContainer:
        id = "stage-container"

    payload = b"contract and source archive"
    client = type("FakeDockerClient", (), {"api": FakeDockerAPI()})()

    try:
        _send_archive_to_work(client, FakeContainer(), payload, timeout_seconds=1)
        assert receiver.recv(len(payload)) == payload
        assert receiver.recv(1) == b""
    finally:
        receiver.close()


def test_read_only_stage_has_private_writable_tmpfs_for_solver_jit(monkeypatch):
    from types import ModuleType

    from fdm_strength.stage_contract import StageContract, canonical_contract_bytes

    created = {}

    class FakeContainer:
        def start(self):
            pass

        def remove(self, **_kwargs):
            pass

    class FakeContainers:
        def create(self, _image, **kwargs):
            created.update(kwargs)
            return FakeContainer()

    class FakeClient:
        containers = FakeContainers()

        def close(self):
            pass

    fake_docker = ModuleType("docker")
    fake_docker.from_env = lambda **_kwargs: FakeClient()
    monkeypatch.setitem(__import__("sys").modules, "docker", fake_docker)
    monkeypatch.setattr(
        "fdm_strength.runner_service._send_archive_to_work", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        DockerStageExecutor,
        "_exec_with_timeout",
        lambda *_args, **_kwargs: (b"", b"expected fake failure", 1),
    )
    contract = StageContract(
        schema_version=1,
        run_id="8e02d8f8-b1ab-4abc-9fe5-2f65173b6704",
        stage_id="test-stage",
        operation="tensile",
        inputs=(),
        parameters={},
        expected_outputs=("result.json", "provenance.json"),
    )

    DockerStageExecutor().execute(
        canonical_contract_bytes(contract), {}, "sha256:" + "b" * 64
    )

    assert created["read_only"] is True
    assert "/work" in created["tmpfs"]
    assert created["tmpfs"]["/tmp"] == (
        "rw,exec,nosuid,nodev,size=268435456,uid=10001,gid=10001,mode=0700"
    )


def test_runner_creates_a_run_and_replay_uses_saved_artifacts_and_image(tmp_path):
    executor = _FakeStageExecutor()
    service = RunService(tmp_path, executor=executor)
    source = b"force_N,travel_mm\n0,0\n"
    submission = RunSubmission(
        operation="tensile",
        input_file={
            "filename": "raw.csv",
            "media_type": "text/csv",
            "sha256": hashlib.sha256(source).hexdigest(),
            "content_base64": base64.b64encode(source).decode("ascii"),
        },
        parameters={"force_column": "force_N"},
        upstream_run_ids=(),
    )

    original, original_result = service.submit(submission)
    replay, replay_result = service.replay(original.id)

    assert original.status == "succeeded"
    assert service.artifacts.get_bytes(original.input_artifacts[0].sha256) == source
    assert original.stages[0].image_digest == "sha256:" + "b" * 64
    assert replay.id != original.id
    assert replay.stages[0].image_digest == original.stages[0].image_digest
    assert original_result == replay_result
    assert executor.seen_source_bytes == [source, source]
    assert executor.seen_contracts[0].expected_outputs == ("result.json", "provenance.json")
    assert len(original.stages[0].output_artifacts) == 2
    stage_provenance = json.loads(
        service.artifacts.get_bytes(original.stages[0].output_artifacts[1].sha256)
    )
    assert stage_provenance["run_id"] == original.id
    assert stage_provenance["inputs"][0]["sha256"] == original.input_artifacts[0].sha256


def test_runner_submits_isotropic_fem_and_persists_all_declared_outputs(tmp_path):
    from fdm_strength.fem_models import (
        BoundaryConditionSet,
        GmshMeshSettings,
        IsotropicMaterialProfile,
        IsotropicTensileRequest,
        RectangularTensileSpecimen,
        TensileLoad,
        canonical_json_bytes,
    )

    request = IsotropicTensileRequest(
        specimen=RectangularTensileSpecimen(
            specimen_id="SYN-FEM-01", length_mm=50.0, width_mm=10.0, thickness_mm=2.0
        ),
        material=IsotropicMaterialProfile(
            profile_id="PLA-isotropic-v1", youngs_modulus_mpa=2000.0, poissons_ratio=0.35
        ),
        load=TensileLoad(force_n=100.0),
        boundary_conditions=BoundaryConditionSet(set_id="axial-pull-v1"),
        mesh=GmshMeshSettings(max_cell_size_mm=2.5, element_order=2),
    )
    request_bytes = canonical_json_bytes(request)
    executor = _FakeIsotropicFemExecutor()
    service = RunService(tmp_path, executor=executor)
    submission = RunSubmission(
        operation="fdm-l2-isotropic",
        input_file={
            "filename": "request.json",
            "media_type": "application/vnd.styrkeanalyse.fem-request+json",
            "sha256": hashlib.sha256(request_bytes).hexdigest(),
            "content_base64": base64.b64encode(request_bytes).decode("ascii"),
        },
        parameters={},
        upstream_run_ids=(),
    )

    run, result = service.submit(submission)

    assert run.status == "succeeded"
    assert run.operation == "fdm-l2-isotropic"
    assert result == {"nominal_stress_mpa": 5.0}
    contract = executor.seen_contracts[0]
    assert contract.stage_id == "fdm-l2-isotropic"
    assert contract.solver_name == "DOLFINx"
    assert contract.solver_version == "0.11.0.post0"
    assert contract.mesh_parameters == request.mesh.model_dump(mode="json")
    assert set(contract.expected_outputs) == {
        "result.json",
        "mesh.msh",
        "fields.xdmf",
        "fields.h5",
        "provenance.json",
    }
    assert {item.media_type for item in run.stages[0].output_artifacts} == {
        "application/vnd.styrkeanalyse.fem-result+json",
        "application/vnd.gmsh.msh",
        "application/vnd.xdmf+xml",
        "application/x-hdf5",
        "application/vnd.styrkeanalyse.stage-provenance+json",
    }
    assert len(run.stages[0].output_artifacts) == 5
    assert all(service.artifacts.get_bytes(item.sha256) for item in run.stages[0].output_artifacts)

    invalid_executor = _FakeIsotropicFemExecutor()
    invalid_executor.corrupt_mesh_digest = True
    invalid_service = RunService(tmp_path / "invalid", executor=invalid_executor)
    invalid_run, _ = invalid_service.submit(submission)
    assert invalid_run.status == "failed"
    assert "provenance" in invalid_run.error


def test_runner_rejects_uploaded_content_that_does_not_match_provenance(tmp_path):
    service = RunService(tmp_path, executor=_FakeStageExecutor())
    source = b"not the claimed input"
    submission = RunSubmission(
        operation="tensile",
        input_file={
            "filename": "raw.csv",
            "media_type": "text/csv",
            "sha256": "0" * 64,
            "content_base64": base64.b64encode(source).decode("ascii"),
        },
        parameters={},
        upstream_run_ids=(),
    )

    with pytest.raises(ValueError, match="uploaded file SHA-256 does not match"):
        service.submit(submission)


def test_runner_rejects_malformed_campaign_before_starting_a_stage(tmp_path):
    executor = _FakeStageExecutor()
    service = RunService(tmp_path, executor=executor)
    source = json.dumps(
        {"format": "styrkeanalyse-fdm-study", "version": 3, "specimens": []}
    ).encode()
    submission = RunSubmission(
        operation="campaign",
        input_file={
            "filename": "study.fdmstudy.json",
            "media_type": "application/json",
            "sha256": hashlib.sha256(source).hexdigest(),
            "content_base64": base64.b64encode(source).decode("ascii"),
        },
        parameters={},
        upstream_run_ids=(),
    )

    with pytest.raises(ValueError, match="invalid campaign workspace"):
        service.submit(submission)
    assert executor.seen_source_bytes == []


def test_runner_http_api_submits_reads_and_replays_an_immutable_run(tmp_path):
    service = RunService(tmp_path, executor=_FakeStageExecutor())
    server = create_runner_server("127.0.0.1", 0, service=service)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = b"force_N,travel_mm\n0,0\n"
    try:
        payload = {
            "operation": "tensile",
            "input_file": {
                "filename": "input.csv",
                "media_type": "text/csv",
                "sha256": hashlib.sha256(source).hexdigest(),
                "content_base64": base64.b64encode(source).decode("ascii"),
            },
            "parameters": {"force_column": "force_N"},
        }
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/runs",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            created = json.load(response)
        run_id = created["run"]["id"]
        digest = created["run"]["input_artifacts"][0]["sha256"]

        with urlopen(f"http://127.0.0.1:{server.server_port}/api/runs/{run_id}") as response:
            stored = json.load(response)
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/artifacts/{digest}") as response:
            restored_source = response.read()

        replay = Request(
            f"http://127.0.0.1:{server.server_port}/api/runs/{run_id}/replay",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(replay) as response:
            replayed = json.load(response)

        assert stored["run"]["id"] == run_id
        assert restored_source == source
        assert replayed["result"] == created["result"]
        assert (
            replayed["run"]["stages"][0]["image_digest"]
            == created["run"]["stages"][0]["image_digest"]
        )
    finally:
        server.shutdown()
        server.server_close()


class _FakeIsotropicFemExecutor:
    def __init__(self):
        self.seen_contracts = []
        self.corrupt_mesh_digest = False

    def inspect_image(self, image_reference=None):
        from fdm_strength.runner_service import StageImage

        return StageImage(
            digest="sha256:" + "c" * 64,
            git_commit="1" * 40,
            git_dirty=False,
            image_reference=image_reference,
            base_image_reference="ghcr.io/fenics/dolfinx/dolfinx@sha256:" + "b" * 64,
            dependency_lock_sha256="d" * 64,
        )

    def execute(self, contract_bytes, inputs, image_digest):
        from datetime import datetime, timezone

        from fdm_strength.provenance import ProvenanceArtifact, StageProvenance
        from fdm_strength.runner_service import FEM_EXPECTED_OUTPUT_MEDIA_TYPES
        from fdm_strength.stage_contract import StageContract

        contract = StageContract.model_validate_json(contract_bytes)
        self.seen_contracts.append(contract)
        now = datetime.now(timezone.utc)
        contents = {
            "result.json": json.dumps(
                {
                    "schema_version": 1,
                    "run_id": contract.run_id,
                    "result": {"nominal_stress_mpa": 5.0},
                },
                sort_keys=True,
            ).encode(),
            "mesh.msh": b"gmsh mesh bytes",
            "fields.xdmf": b"xdmf field index",
            "fields.h5": b"hdf5 field values",
        }
        provenance = StageProvenance(
            run_id=contract.run_id,
            stage_id=contract.stage_id,
            operation=contract.operation,
            image_reference=contract.image_reference,
            image_digest=image_digest,
            base_image_reference=contract.base_image_reference,
            dependency_lock_sha256=contract.dependency_lock_sha256,
            contract_sha256=hashlib.sha256(contract_bytes).hexdigest(),
            entrypoint=contract.entrypoint,
            inputs=tuple(
                ProvenanceArtifact(
                    name=item.name,
                    sha256=item.sha256,
                    size_bytes=item.size_bytes,
                    media_type=item.media_type,
                )
                for item in contract.inputs
            ),
            outputs=tuple(
                ProvenanceArtifact(
                    name=name,
                    sha256=hashlib.sha256(contents[name]).hexdigest(),
                    size_bytes=len(contents[name]),
                    media_type=FEM_EXPECTED_OUTPUT_MEDIA_TYPES[name],
                )
                for name in sorted(contents)
            ),
            git_commit=contract.git_commit,
            git_dirty=contract.git_dirty,
            solver_name=contract.solver_name,
            solver_version=contract.solver_version,
            mesh_sha256=(
                "0" * 64
                if self.corrupt_mesh_digest
                else hashlib.sha256(contents["mesh.msh"]).hexdigest()
            ),
            mesh_parameters=contract.mesh_parameters,
            material_profile_id=contract.material_profile_id,
            material_profile_sha256=contract.material_profile_sha256,
            boundary_condition_set_id=contract.boundary_condition_set_id,
            boundary_condition_set_sha256=contract.boundary_condition_set_sha256,
            mpi_ranks=contract.mpi_ranks,
            omp_threads=contract.omp_threads,
            cpu_count=contract.cpu_count,
            memory_limit_bytes=contract.memory_limit_bytes,
            started_at=now,
            completed_at=now,
            runtime_versions={"python": "3.12", "pydantic": "2.11", "dolfinx": "0.11.0.post0"},
        ).model_dump_json().encode()
        return StageExecution(
            success=True,
            outputs={**contents, "provenance.json": provenance},
            stdout=b"FEM stage completed",
            stderr=b"",
            started_at=now,
            completed_at=now,
            error=None,
        )


class _FakeStageExecutor:
    def __init__(self):
        self.seen_source_bytes = []
        self.seen_contracts = []

    def inspect_image(self, image_reference=None):
        from fdm_strength.runner_service import StageImage

        return StageImage(
            digest="sha256:" + "b" * 64,
            git_commit="1" * 40,
            git_dirty=False,
        )

    def execute(self, contract_bytes, inputs, image_digest):
        from datetime import datetime, timezone

        from fdm_strength.stage_contract import StageContract

        contract = StageContract.model_validate_json(contract_bytes)
        self.seen_contracts.append(contract)
        source = inputs[contract.inputs[0].sha256]
        self.seen_source_bytes.append(source)
        result = json.dumps(
            {"schema_version": 1, "run_id": contract.run_id, "result": {"source": source.decode()}},
            sort_keys=True,
        ).encode()
        provenance = json.dumps(
            {
                "schema_version": 1,
                "run_id": contract.run_id,
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
                        "sha256": hashlib.sha256(result).hexdigest(),
                        "size_bytes": len(result),
                    }
                ],
            },
            sort_keys=True,
        ).encode()
        now = datetime.now(timezone.utc)
        return StageExecution(
            success=True,
            outputs={"result.json": result, "provenance.json": provenance},
            stdout=b"stage completed",
            stderr=b"",
            started_at=now,
            completed_at=now,
            error=None,
        )


def _sample_run() -> Run:
    now = datetime.now(timezone.utc)
    artifact = ArtifactReference(
        sha256="a" * 64,
        size_bytes=3,
        media_type="application/json",
    )
    stage = StageRecord(
        stage_id="experimental-reduction",
        operation="tensile",
        status="succeeded",
        image_digest="sha256:" + "b" * 64,
        command=("python", "-m", "fdm_strength.exp_reduction_stage"),
        input_artifacts=(artifact,),
        output_artifacts=(artifact,),
        started_at=now,
        completed_at=now,
        duration_ms=0,
        git_commit="1" * 40,
        git_dirty=False,
        cpu_count=1,
        memory_limit_bytes=1024,
    )
    return Run(
        id="8e02d8f8-b1ab-4abc-9fe5-2f65173b6704",
        created_at=now,
        operation="tensile",
        status="succeeded",
        spec_artifact=artifact,
        input_artifacts=(artifact,),
        output_artifacts=(artifact,),
        result_artifact=artifact,
        stages=(stage,),
        upstream_run_ids=(),
    )
