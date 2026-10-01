"""Command-line entry point for the research pipeline."""

import hashlib
import json
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console

from fdm_strength.provenance import StageProvenance
from fdm_strength.run_models import StageRecord
from fdm_strength.run_store import ArtifactStore, RunStore
from fdm_strength.stage_contract import StageContract

app = typer.Typer(help="FDM strength-analysis research tools.", no_args_is_help=True)
console = Console()


@app.command()
def info() -> None:
    """Show the current project boundary and available next steps."""
    console.print("[bold]StyrkeAnalyse-FDM[/bold] 0.1.0")
    console.print("Toolpath model ready; material mapping and verified solver stages remain.")


@app.command()
def inspect(
    path: Path = typer.Argument(..., exists=True, readable=True, file_okay=True, dir_okay=False),
) -> None:
    """Report an input file's size and SHA-256 before analysis."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    console.print(f"Input: {path.resolve()}")
    console.print(f"Size: {path.stat().st_size:,} bytes")
    console.print(f"SHA-256: {digest.hexdigest()}")


@app.command()
def provenance(
    run_id: str = typer.Option(..., "--run", help="Canonical immutable Run UUID."),
    data_root: Path = typer.Option(
        ...,
        "--data-root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Runner data directory containing runs/ and artifacts/.",
    ),
) -> None:
    """Print a Run and its hash-verified stage provenance manifests as JSON."""
    try:
        run = RunStore(data_root).get(run_id)
        artifacts = ArtifactStore(data_root)
        manifests: list[dict[str, object]] = []
        for stage in run.stages:
            references = [
                reference
                for reference in stage.output_artifacts
                if reference.media_type == "application/vnd.styrkeanalyse.stage-provenance+json"
            ]
            if len(references) > 1:
                raise ValueError(f"stage {stage.stage_id} has multiple provenance artifacts")
            if not references:
                manifests.append({"stage_id": stage.stage_id, "manifest": None})
                continue

            reference = references[0]
            manifest_bytes = artifacts.get_bytes(reference.sha256)
            if len(manifest_bytes) != reference.size_bytes:
                raise ValueError(f"stage {stage.stage_id} provenance artifact size mismatch")
            if stage.provenance_schema_version == 2:
                manifest = StageProvenance.model_validate_json(manifest_bytes)
                contract_ref = next(
                    (
                        item
                        for item in stage.input_artifacts
                        if item.sha256 == manifest.contract_sha256
                        and item.media_type == "application/vnd.styrkeanalyse.stage-contract+json"
                    ),
                    None,
                )
                if contract_ref is None:
                    raise ValueError(f"stage {stage.stage_id} contract artifact is missing")
                contract_bytes = artifacts.get_bytes(contract_ref.sha256)
                if len(contract_bytes) != contract_ref.size_bytes:
                    raise ValueError(f"stage {stage.stage_id} contract artifact size mismatch")
                contract = StageContract.model_validate_json(contract_bytes)
                _validate_manifest_against_run(run.id, stage, contract, manifest)
                for artifact in (*manifest.inputs, *manifest.outputs):
                    content = artifacts.get_bytes(artifact.sha256)
                    if len(content) != artifact.size_bytes:
                        raise ValueError(
                            f"stage {stage.stage_id} artifact {artifact.name} size mismatch"
                        )
                payload: dict[str, object] = manifest.model_dump(mode="json")
            else:
                payload = json.loads(manifest_bytes)
                if (
                    not isinstance(payload, dict)
                    or payload.get("schema_version") != 1
                    or payload.get("run_id") != run.id
                    or payload.get("stage_id") != stage.stage_id
                    or payload.get("operation") != stage.operation
                ):
                    raise ValueError(f"stage {stage.stage_id} has invalid legacy provenance")
            manifests.append({"stage_id": stage.stage_id, "manifest": payload})

        typer.echo(
            json.dumps(
                {"run": run.model_dump(mode="json"), "stage_provenance": manifests},
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                indent=2,
            )
        )
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as error:
        raise typer.BadParameter(str(error)) from error


def _validate_manifest_against_run(
    run_id: str,
    stage: StageRecord,
    contract: StageContract,
    manifest: StageProvenance,
) -> None:
    if (
        manifest.run_id != run_id
        or manifest.stage_id != stage.stage_id
        or manifest.operation != stage.operation
        or manifest.image_digest != stage.image_digest
        or manifest.image_reference != stage.image_reference
        or manifest.base_image_reference != stage.base_image_reference
        or manifest.dependency_lock_sha256 != stage.dependency_lock_sha256
        or manifest.entrypoint != stage.command
        or manifest.git_commit != stage.git_commit
        or manifest.git_dirty != stage.git_dirty
        or manifest.mpi_ranks != stage.mpi_ranks
        or manifest.omp_threads != stage.omp_threads
        or manifest.openblas_threads != stage.openblas_threads
        or manifest.cpu_count != stage.cpu_count
        or manifest.memory_limit_bytes != stage.memory_limit_bytes
        or not (
            stage.started_at <= manifest.started_at <= manifest.completed_at <= stage.completed_at
        )
    ):
        raise ValueError(f"stage {stage.stage_id} provenance does not match its Run record")
    if (
        contract.schema_version != 2
        or contract.run_id != run_id
        or contract.stage_id != stage.stage_id
        or contract.operation != stage.operation
        or contract.image_reference != manifest.image_reference
        or contract.image_digest != manifest.image_digest
        or contract.base_image_reference != manifest.base_image_reference
        or contract.dependency_lock_sha256 != manifest.dependency_lock_sha256
        or contract.git_commit != manifest.git_commit
        or contract.git_dirty != manifest.git_dirty
        or contract.entrypoint != manifest.entrypoint
        or contract.solver_name != manifest.solver_name
        or contract.solver_version != manifest.solver_version
        or (contract.mesh_sha256 is not None and contract.mesh_sha256 != manifest.mesh_sha256)
        or (
            contract.mesh_parameters is not None
            and contract.mesh_parameters != manifest.mesh_parameters
        )
        or contract.material_profile_id != manifest.material_profile_id
        or contract.material_profile_sha256 != manifest.material_profile_sha256
        or contract.boundary_condition_set_id != manifest.boundary_condition_set_id
        or contract.boundary_condition_set_sha256 != manifest.boundary_condition_set_sha256
        or contract.mpi_ranks != manifest.mpi_ranks
        or contract.omp_threads != manifest.omp_threads
        or contract.openblas_threads != manifest.openblas_threads
        or contract.cpu_count != manifest.cpu_count
        or contract.memory_limit_bytes != manifest.memory_limit_bytes
        or [item.model_dump(mode="json") for item in contract.inputs]
        != [item.model_dump(mode="json") for item in manifest.inputs]
    ):
        raise ValueError(f"stage {stage.stage_id} provenance does not match its contract")
    output_artifacts = {
        (item.sha256, item.size_bytes, item.media_type)
        for item in stage.output_artifacts
        if item.media_type != "application/vnd.styrkeanalyse.stage-provenance+json"
    }
    manifest_output_artifacts = {
        (item.sha256, item.size_bytes, item.media_type) for item in manifest.outputs
    }
    if manifest_output_artifacts != output_artifacts:
        raise ValueError(f"stage {stage.stage_id} output hashes do not resolve from its Run")


if __name__ == "__main__":
    app()
