"""CLI entrypoint for the pinned experimental-reduction runtime image."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from fdm_strength.experimental_reduction import analyze_uploaded_csv, reduce_campaign_workspace
from fdm_strength.provenance import ProvenanceArtifact, StageProvenance
from fdm_strength.stage_contract import load_stage_contract


def main() -> int:
    work_root = Path("/work")
    try:
        started_at = datetime.now(timezone.utc)
        contract = load_stage_contract(work_root)
        inputs = {
            item.name: (work_root / "in" / item.name).read_bytes() for item in contract.inputs
        }
        if contract.operation == "tensile":
            source = inputs.get("source.csv")
            if source is None:
                raise ValueError("tensile stage requires source.csv")
            result = analyze_uploaded_csv(source, contract.parameters)
        elif contract.operation == "campaign":
            source = inputs.get("workspace.json")
            if source is None:
                raise ValueError("campaign stage requires workspace.json")
            try:
                payload = json.loads(source)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("campaign workspace input is not valid UTF-8 JSON") from error
            if not isinstance(payload, dict):
                raise ValueError("campaign workspace input must be a JSON object")
            result = reduce_campaign_workspace(payload)
        else:  # pragma: no cover - the contract enum prevents this
            raise ValueError(f"unsupported experimental-reduction operation {contract.operation}")

        output_bytes = (
            json.dumps(
                {"schema_version": 1, "run_id": contract.run_id, "result": result},
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        outputs = {
            "result.json": output_bytes,
        }
        if set(contract.expected_outputs) != {"result.json", "provenance.json"}:
            raise ValueError(
                "experimental-reduction stage requires result.json and provenance.json outputs"
            )
        if contract.schema_version == 2:
            lock_path = Path("/app/uv.lock")
            lock_bytes = lock_path.read_bytes()
            lock_digest = hashlib.sha256(lock_bytes).hexdigest()
            if lock_digest != contract.dependency_lock_sha256:
                raise ValueError("stage dependency lock does not match the immutable contract")
            provenance = StageProvenance(
                schema_version=2,
                run_id=contract.run_id,
                stage_id=contract.stage_id,
                operation=contract.operation,
                image_reference=contract.image_reference,
                image_digest=contract.image_digest,
                base_image_reference=contract.base_image_reference,
                dependency_lock_sha256=lock_digest,
                contract_sha256=hashlib.sha256((work_root / "run.json").read_bytes()).hexdigest(),
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
                outputs=(
                    ProvenanceArtifact(
                        name="result.json",
                        sha256=hashlib.sha256(output_bytes).hexdigest(),
                        size_bytes=len(output_bytes),
                        media_type="application/vnd.styrkeanalyse.experimental-reduction+json",
                    ),
                ),
                git_commit=contract.git_commit,
                git_dirty=contract.git_dirty,
                solver_name=contract.solver_name,
                solver_version=contract.solver_version,
                mesh_sha256=contract.mesh_sha256,
                mesh_parameters=contract.mesh_parameters,
                material_profile_id=contract.material_profile_id,
                material_profile_sha256=contract.material_profile_sha256,
                boundary_condition_set_id=contract.boundary_condition_set_id,
                boundary_condition_set_sha256=contract.boundary_condition_set_sha256,
                mpi_ranks=contract.mpi_ranks,
                omp_threads=contract.omp_threads,
                cpu_count=contract.cpu_count,
                memory_limit_bytes=contract.memory_limit_bytes,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                runtime_versions={
                    "python": platform.python_version(),
                    "pydantic": importlib.metadata.version("pydantic"),
                },
            ).model_dump(mode="json")
        else:
            provenance = {
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
                        "name": name,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                    }
                    for name, content in outputs.items()
                ],
            }
        outputs["provenance.json"] = (
            json.dumps(
                provenance,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        for name, content in outputs.items():
            (work_root / "out" / name).write_bytes(content)
        return 0
    except (OSError, TypeError, ValueError) as error:
        print(f"experimental-reduction failed: {error}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
