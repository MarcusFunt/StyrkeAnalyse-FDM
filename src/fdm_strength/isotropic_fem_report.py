"""Assemble and validate the immutable M4 isotropic FEM evidence report."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fdm_strength.fem_models import IsotropicTensileRequest, analytical_tensile_response
from fdm_strength.isotropic_fem_verification import parse_calculix_dat
from fdm_strength.verification import (
    ISOTROPIC_FEM_REQUIRED_GATES,
    GateAssessment,
    GateEvidence,
    evaluate_isotropic_fem_gate,
    isotropic_fem_gate_metric_blockers,
    observed_l2_convergence_order,
    relative_error,
)

REPORT_FILENAME = "m4-verification-report.json"
_PINNED_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOLVER_SOURCE_FILES = (
    "src/fdm_strength/fem_models.py",
    "src/fdm_strength/isotropic_fem_stage.py",
    "src/fdm_strength/isotropic_fem_verification.py",
    "src/fdm_strength/verification.py",
)
_REQUIRED_GATE_ARTIFACTS = {
    "manufactured_solution": {
        "dolfinx-evidence.json",
        "manufactured-level-1.msh",
        "manufactured-level-2.msh",
        "manufactured-level-3.msh",
        "manufactured-level-4.msh",
    },
    "uniform_stress_patch": {
        "dolfinx-evidence.json",
        "tensile-result.json",
        "tensile-mesh.msh",
        "tensile.inp",
    },
    "analytical_agreement": {
        "dolfinx-evidence.json",
        "tensile-result.json",
        "tensile-mesh.msh",
        "tensile.inp",
    },
    "calculix_crosscheck": {
        "dolfinx-evidence.json",
        "tensile-result.json",
        "tensile-mesh.msh",
        "tensile.inp",
        "tensile.dat",
        "tensile.frd",
    },
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _model_digest(configuration: Mapping[str, Any]) -> str:
    return f"sha256:{_sha256_bytes(_canonical_json(configuration))}"


def _verification_source_hashes() -> dict[str, str]:
    repository_root = Path(__file__).resolve().parents[2]
    source_files = (
        "src/fdm_strength/fem_models.py",
        "src/fdm_strength/isotropic_fem_stage.py",
        "src/fdm_strength/isotropic_fem_verification.py",
        "src/fdm_strength/isotropic_fem_report.py",
        "src/fdm_strength/verification.py",
        "scripts/verify_isotropic_fem.py",
    )
    return {name: _sha256_bytes((repository_root / name).read_bytes()) for name in source_files}


def _solver_source_hashes() -> dict[str, str]:
    repository_root = Path(__file__).resolve().parents[2]
    return {
        name: _sha256_bytes((repository_root / name).read_bytes())
        for name in _SOLVER_SOURCE_FILES
    }


def _image_provenance(labels: Mapping[str, Any], git_commit: str, solver: str) -> dict[str, str]:
    required = {
        "org.opencontainers.image.revision": git_commit,
        "fdm.git.commit": git_commit,
        "fdm.git.dirty": "false",
    }
    for key, expected in required.items():
        if labels.get(key) != expected:
            raise ValueError(f"{solver} image label {key} must be {expected!r}")
    selected = {key: str(labels[key]) for key in required}
    for optional in ("fdm.base-image.reference", "fdm.dependency-lock.sha256", "fdm.solver.name"):
        if optional in labels:
            selected[optional] = str(labels[optional])
    return selected


def _close_metric(actual: Any, expected: float) -> bool:
    return (
        isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and math.isfinite(float(actual))
        and math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-14)
    )


def _require_matching_metrics(
    actual: Mapping[str, Any], expected: Mapping[str, float], source: str
) -> None:
    if set(actual) != set(expected) or any(
        not _close_metric(actual.get(name), value) for name, value in expected.items()
    ):
        raise ValueError(f"{source} metrics do not match recomputed solver evidence")


def _derive_tensile_metrics(tensile: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    request = IsotropicTensileRequest.model_validate(
        {
            "specimen": tensile["specimen"],
            "material": tensile["material"],
            "load": tensile["load"],
            "boundary_conditions": tensile["boundary_conditions"],
            "mesh": tensile["mesh"],
        }
    )
    analytical = analytical_tensile_response(request)
    if tensile.get("analytical_reference") != analytical.model_dump(mode="json"):
        raise ValueError("stored analytical reference does not match the immutable tensile inputs")
    result = tensile["solver_result"]
    strain = result["measured_axial_displacement_mm"] / request.specimen.length_mm
    analytical_metrics = {
        "stress_uniformity_relative_range": result["axial_stress_uniformity_relative_range"],
        "stress_relative_error": relative_error(
            result["volume_average_axial_stress_mpa"], analytical.nominal_stress_mpa
        ),
        "strain_relative_error": relative_error(strain, analytical.nominal_strain),
        "displacement_relative_error": relative_error(
            result["measured_axial_displacement_mm"], analytical.axial_displacement_mm
        ),
        "midspan_displacement_relative_error": relative_error(
            result["measured_midspan_displacement_mm"], analytical.axial_displacement_mm / 2.0
        ),
        "reaction_force_relative_error": relative_error(
            result["reaction_force_n"], analytical.reaction_force_n
        ),
    }
    patch_metrics = {
        key: analytical_metrics[key]
        for key in (
            "stress_uniformity_relative_range",
            "displacement_relative_error",
            "reaction_force_relative_error",
        )
    }
    return {
        "uniform_stress_patch": patch_metrics,
        "analytical_agreement": analytical_metrics,
    }


def _derive_gate_metrics(
    name: str, evidence_dir: Path, dolfinx_report: Mapping[str, Any], tensile: Mapping[str, Any]
) -> dict[str, float]:
    if name == "manufactured_solution":
        source = dolfinx_report["gates"][name]
        sizes = source["mesh_sizes_mm"]
        errors = source["relative_l2_errors"]
        diagnostics = source["solver_diagnostics"]
        expected_levels = len(sizes)
        errors_match = all(len(errors[label]) == expected_levels for label in ("p1", "p2"))
        if expected_levels < 4 or not errors_match:
            raise ValueError(
                "manufactured-solution evidence must contain four matching refinement levels"
            )
        for label in ("p1", "p2"):
            levels = diagnostics[label]
            if len(levels) != expected_levels or any(
                level["free_dof_count"] <= 0
                or level["boundary_dof_count"] >= level["total_dof_count"]
                for level in levels
            ):
                raise ValueError("manufactured-solution evidence has no free interior DOFs")
        return {
            "p1_l2_order": observed_l2_convergence_order(sizes, errors["p1"]),
            "p2_l2_order": observed_l2_convergence_order(sizes, errors["p2"]),
        }
    if name in {"uniform_stress_patch", "analytical_agreement"}:
        return _derive_tensile_metrics(tensile)[name]
    if name == "calculix_crosscheck":
        calculix = parse_calculix_dat((evidence_dir / "tensile.dat").read_text(encoding="utf-8"))
        result = tensile["solver_result"]
        return {
            "relative_midspan_displacement_error": relative_error(
                calculix["midspan_axial_displacement_mm"],
                result["measured_midspan_displacement_mm"],
            ),
            "relative_reaction_force_error": relative_error(
                calculix["loaded_face_reaction_force_n"], result["reaction_force_n"]
            ),
        }
    raise ValueError(f"unknown M4 verification gate {name}")


def _artifact_set_digest(paths: list[str], by_path: Mapping[str, Mapping[str, Any]]) -> str:
    records = [{"path": path, "sha256": by_path[path]["sha256"]} for path in sorted(paths)]
    return _sha256_bytes(_canonical_json(records))


def _assessment_json(assessment: GateAssessment) -> dict[str, Any]:
    return {
        "comparison_allowed": assessment.comparison_allowed,
        "missing_gates": list(assessment.missing_gates),
        "failed_gates": list(assessment.failed_gates),
        "blockers": list(assessment.blockers),
    }


def _artifact_inventory(evidence_dir: Path) -> list[dict[str, Any]]:
    root = evidence_dir.resolve()
    inventory: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == REPORT_FILENAME:
            continue
        payload = path.read_bytes()
        inventory.append(
            {"path": relative, "sha256": _sha256_bytes(payload), "size_bytes": len(payload)}
        )
    return inventory


def _gate_artifact_paths(
    name: str, dolfinx_report: Mapping[str, Any], inventory: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    paths = sorted(_REQUIRED_GATE_ARTIFACTS[name])
    if name == "manufactured_solution":
        declared_meshes = set(dolfinx_report["gates"][name]["artifacts"])
        required_meshes = _REQUIRED_GATE_ARTIFACTS[name] - {"dolfinx-evidence.json"}
        if declared_meshes != required_meshes:
            raise ValueError("manufactured-solution evidence references an unexpected mesh set")
    missing = sorted(set(paths) - set(inventory))
    if missing:
        raise ValueError(f"{name} evidence is missing artifacts: {', '.join(missing)}")
    return sorted(set(paths))


def build_m4_report(
    evidence_dir: Path,
    *,
    dolfinx_image_digest: str,
    calculix_image_digest: str,
    dolfinx_image_labels: Mapping[str, Any],
    calculix_image_labels: Mapping[str, Any],
    calculix_version: str,
    git_commit: str,
) -> dict[str, Any]:
    """Bind solver metrics to exact inputs, images, and hashed output files."""
    if not _PINNED_DIGEST.fullmatch(dolfinx_image_digest):
        raise ValueError("DOLFINx image must have an immutable sha256 digest")
    if not _PINNED_DIGEST.fullmatch(calculix_image_digest):
        raise ValueError("CalculiX image must have an immutable sha256 digest")
    if re.fullmatch(r"[0-9a-f]{40}", git_commit) is None:
        raise ValueError("git commit must be a full 40-character revision")

    image_labels = {
        "dolfinx": _image_provenance(dolfinx_image_labels, git_commit, "DOLFINx"),
        "calculix": _image_provenance(calculix_image_labels, git_commit, "CalculiX"),
    }

    root = evidence_dir.resolve()
    dolfinx_report = json.loads((root / "dolfinx-evidence.json").read_text(encoding="utf-8"))
    tensile = json.loads((root / "tensile-result.json").read_text(encoding="utf-8"))
    solver_metadata = dolfinx_report["solver"]
    for setting in ("mpi_ranks", "omp_threads", "blas_threads"):
        if solver_metadata.get(setting) != 1:
            raise ValueError(f"DOLFINx evidence must record {setting}=1")
    solver_source_hashes = dolfinx_report.get("solver_source_sha256")
    if (
        not isinstance(solver_source_hashes, Mapping)
        or dict(solver_source_hashes) != _solver_source_hashes()
    ):
        raise ValueError(
            "DOLFINx executed source hashes do not match the clean verification checkout"
        )

    artifacts = _artifact_inventory(root)
    by_path = {item["path"]: item for item in artifacts}
    if len(by_path) != len(artifacts):
        raise ValueError("evidence artifact paths must be unique")
    image_digests = {"dolfinx": dolfinx_image_digest, "calculix": calculix_image_digest}
    model_configuration = {
        "schema_version": 1,
        "git_commit": git_commit,
        "solver_image_digests": image_digests,
        "solver_image_labels": image_labels,
        "solver_versions": {
            "dolfinx": solver_metadata["version"],
            "calculix": calculix_version,
        },
        "solver_resources": {"mpi_ranks": 1, "omp_threads": 1, "blas_threads": 1},
        "executed_solver_source_sha256": dict(solver_source_hashes),
        "verification_source_sha256": _verification_source_hashes(),
        "specimen": tensile["specimen"],
        "material": tensile["material"],
        "load": tensile["load"],
        "boundary_conditions": tensile["boundary_conditions"],
        "mesh_settings": tensile["mesh"],
        "mesh_sha256": by_path["tensile-mesh.msh"]["sha256"],
        "calculix_deck_sha256": by_path["tensile.inp"]["sha256"],
    }
    model_digest = _model_digest(model_configuration)

    expected_configuration = {
        "specimen": tensile["specimen"],
        "material": tensile["material"],
        "load": tensile["load"],
        "boundary_conditions": tensile["boundary_conditions"],
        "mesh_settings": tensile["mesh"],
        "mesh_sha256": by_path["tensile-mesh.msh"]["sha256"],
        "calculix_deck_sha256": by_path["tensile.inp"]["sha256"],
    }
    if any(model_configuration.get(key) != value for key, value in expected_configuration.items()):
        raise ValueError("model configuration does not match the hashed tensile inputs")

    metrics_by_gate: dict[str, dict[str, float]] = {}
    for name in ISOTROPIC_FEM_REQUIRED_GATES:
        metrics_by_gate[name] = _derive_gate_metrics(name, root, dolfinx_report, tensile)
        if name != "calculix_crosscheck":
            _require_matching_metrics(
                dolfinx_report["gates"][name]["metrics"],
                metrics_by_gate[name],
                f"DOLFINx {name}",
            )
    gates: dict[str, dict[str, Any]] = {}
    recorded_at = datetime.now(UTC).isoformat()
    for name in ISOTROPIC_FEM_REQUIRED_GATES:
        paths = _gate_artifact_paths(name, dolfinx_report, by_path)
        solver_names = {"dolfinx", "calculix"} if name == "calculix_crosscheck" else {"dolfinx"}
        metrics = metrics_by_gate[name]
        gates[name] = {
            "name": name,
            "passed": not isotropic_fem_gate_metric_blockers(name, metrics),
            "model_digest": model_digest,
            "artifact_sha256": _artifact_set_digest(paths, by_path),
            "artifact_paths": paths,
            "solver_image_digests": {
                solver: image_digests[solver] for solver in sorted(solver_names)
            },
            "metrics": metrics,
            "recorded_at": recorded_at,
        }

    report: dict[str, Any] = {
        "schema_version": 1,
        "created_at": recorded_at,
        "model": {"configuration": model_configuration, "digest": model_digest},
        "artifacts": artifacts,
        "gates": gates,
    }
    report["assessment"] = _assessment_json(_assess_m4_report(report, root, False))
    return report


def _false_assessment(blockers: list[str]) -> GateAssessment:
    return GateAssessment(False, (), (), tuple(blockers))


def _assess_m4_report(
    report: Mapping[str, Any], evidence_dir: Path, require_stored_assessment: bool
) -> GateAssessment:
    blockers: list[str] = []
    if report.get("schema_version") != 1:
        blockers.append("unsupported or missing M4 report schema version")
    model = report.get("model")
    if not isinstance(model, Mapping) or not isinstance(model.get("configuration"), Mapping):
        return _false_assessment([*blockers, "model configuration is missing or malformed"])
    model_configuration = model["configuration"]
    model_digest = model.get("digest")
    try:
        recomputed_model_digest = _model_digest(model_configuration)
    except (TypeError, ValueError):
        recomputed_model_digest = ""
    if not isinstance(model_digest, str) or model_digest != recomputed_model_digest:
        blockers.append("model digest does not match its canonical configuration")

    image_digests = model_configuration.get("solver_image_digests", {})
    artifacts = report.get("artifacts")
    artifact_by_path: dict[str, Mapping[str, Any]] = {}
    if not isinstance(artifacts, list):
        blockers.append("artifact inventory is missing or malformed")
        artifacts = []
    root = evidence_dir.resolve()
    for item in artifacts:
        if not isinstance(item, Mapping):
            blockers.append("artifact inventory contains a malformed record")
            continue
        relative = item.get("path")
        if not isinstance(relative, str):
            blockers.append("artifact path is malformed")
            continue
        pure_path = PurePosixPath(relative)
        if pure_path.is_absolute() or ".." in pure_path.parts or "\\" in relative:
            blockers.append(f"artifact path escapes the evidence directory: {relative}")
            continue
        if relative in artifact_by_path:
            blockers.append(f"duplicate artifact path: {relative}")
            continue
        artifact_by_path[relative] = item
        actual_path = root.joinpath(*pure_path.parts)
        try:
            actual_resolved = actual_path.resolve(strict=True)
            actual_resolved.relative_to(root)
            if actual_path.is_symlink() or not actual_resolved.is_file():
                raise OSError("not a regular artifact file")
            payload = actual_resolved.read_bytes()
        except (OSError, ValueError):
            blockers.append(f"artifact file is missing or outside evidence root: {relative}")
            continue
        if item.get("sha256") != _sha256_bytes(payload):
            blockers.append(f"artifact content digest does not match: {relative}")
        if item.get("size_bytes") != len(payload):
            blockers.append(f"artifact size does not match: {relative}")

    git_commit = model_configuration.get("git_commit")
    if not isinstance(git_commit, str) or re.fullmatch(r"[0-9a-f]{40}", git_commit) is None:
        blockers.append("model configuration has no full source revision")
    else:
        raw_labels = model_configuration.get("solver_image_labels", {})
        if not isinstance(raw_labels, Mapping):
            blockers.append("solver image labels are missing or malformed")
        else:
            for solver in ("dolfinx", "calculix"):
                labels = raw_labels.get(solver)
                if not isinstance(labels, Mapping):
                    blockers.append(f"{solver}: image labels are missing or malformed")
                    continue
                try:
                    _image_provenance(labels, git_commit, solver)
                except ValueError as exc:
                    blockers.append(str(exc))
    try:
        if model_configuration.get("verification_source_sha256") != _verification_source_hashes():
            blockers.append("verification tooling source hashes do not match this checkout")
        if model_configuration.get("executed_solver_source_sha256") != _solver_source_hashes():
            blockers.append("executed solver source hashes do not match this checkout")
    except OSError as exc:
        blockers.append(f"verification source files cannot be hashed: {exc}")

    for solver in ("dolfinx", "calculix"):
        expected_image = image_digests.get(solver) if isinstance(image_digests, Mapping) else None
        if not isinstance(expected_image, str) or not _PINNED_DIGEST.fullmatch(expected_image):
            blockers.append(f"{solver}: immutable image ID is missing")

    dolfinx_report: Mapping[str, Any] = {}
    tensile: Mapping[str, Any] = {}
    try:
        dolfinx_report = json.loads((root / "dolfinx-evidence.json").read_text(encoding="utf-8"))
        tensile = json.loads((root / "tensile-result.json").read_text(encoding="utf-8"))
        if dolfinx_report.get("solver_source_sha256") != model_configuration.get(
            "executed_solver_source_sha256"
        ):
            blockers.append("solver evidence source hashes do not match model provenance")
        expected_configuration = {
            "specimen": tensile["specimen"],
            "material": tensile["material"],
            "load": tensile["load"],
            "boundary_conditions": tensile["boundary_conditions"],
            "mesh_settings": tensile["mesh"],
        }
        for key, expected in expected_configuration.items():
            if model_configuration.get(key) != expected:
                blockers.append(f"model configuration {key} does not match tensile inputs")
        if model_configuration.get("mesh_sha256") != artifact_by_path.get(
            "tensile-mesh.msh", {}
        ).get("sha256"):
            blockers.append("model mesh hash does not match the tensile mesh artifact")
        if model_configuration.get("calculix_deck_sha256") != artifact_by_path.get(
            "tensile.inp", {}
        ).get("sha256"):
            blockers.append("model deck hash does not match the CalculiX input artifact")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        blockers.append(f"solver input evidence is malformed or missing: {exc}")

    raw_gates = report.get("gates")
    evidence: list[GateEvidence] = []
    if not isinstance(raw_gates, Mapping):
        blockers.append("gate evidence is missing or malformed")
        raw_gates = {}
    for name, raw_gate in raw_gates.items():
        if not isinstance(raw_gate, Mapping):
            blockers.append(f"{name}: evidence record is malformed")
            continue
        paths = raw_gate.get("artifact_paths")
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            blockers.append(f"{name}: artifact path list is malformed")
            paths = []
        required_paths = _REQUIRED_GATE_ARTIFACTS.get(str(name))
        if required_paths is None:
            blockers.append(f"{name}: unsupported gate")
        elif set(paths) != required_paths:
            blockers.append(
                f"{name}: required solver artifact references are incomplete or unexpected"
            )
        missing_paths = [path for path in paths if path not in artifact_by_path]
        if missing_paths:
            blockers.append(f"{name}: referenced artifact is missing from inventory")
        else:
            expected_artifact_digest = _artifact_set_digest(paths, artifact_by_path)
            if raw_gate.get("artifact_sha256") != expected_artifact_digest:
                blockers.append(f"{name}: artifact-set digest does not match its references")
        metrics = raw_gate.get("metrics", {})
        if not isinstance(metrics, Mapping):
            blockers.append(f"{name}: metrics are malformed")
            metrics = {}
        if name in ISOTROPIC_FEM_REQUIRED_GATES and dolfinx_report and tensile:
            try:
                recomputed_metrics = _derive_gate_metrics(str(name), root, dolfinx_report, tensile)
                _require_matching_metrics(metrics, recomputed_metrics, str(name))
                if name != "calculix_crosscheck":
                    _require_matching_metrics(
                        dolfinx_report["gates"][name]["metrics"],
                        recomputed_metrics,
                        f"DOLFINx {name}",
                    )
            except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
                blockers.append(f"{name}: {exc}")
        evidence.append(
            GateEvidence(
                name=str(raw_gate.get("name", name)),
                passed=raw_gate.get("passed") is True,
                model_digest=str(raw_gate.get("model_digest", "")),
                artifact_sha256=str(raw_gate.get("artifact_sha256", "")),
                solver_image_digests=(
                    raw_gate.get("solver_image_digests", {})
                    if isinstance(raw_gate.get("solver_image_digests", {}), Mapping)
                    else {}
                ),
                metrics=metrics,
                recorded_at=str(raw_gate.get("recorded_at", "")),
            )
        )

    assessment = evaluate_isotropic_fem_gate(
        evidence,
        image_digests if isinstance(image_digests, Mapping) else {},
        model_digest=str(model_digest or ""),
    )
    blockers.extend(assessment.blockers)
    final = GateAssessment(
        comparison_allowed=assessment.comparison_allowed and not blockers,
        missing_gates=assessment.missing_gates,
        failed_gates=assessment.failed_gates,
        blockers=tuple(dict.fromkeys(blockers)),
    )
    if require_stored_assessment:
        stored = report.get("assessment")
        if not isinstance(stored, Mapping):
            return _false_assessment([*final.blockers, "stored gate assessment is missing"])
        if dict(stored) != _assessment_json(final):
            return _false_assessment(
                [*final.blockers, "stored gate assessment does not match evidence"]
            )
    return final


def assess_m4_report(report: Mapping[str, Any], evidence_dir: Path) -> GateAssessment:
    """Rehash all inputs and evidence, then re-run the fail-closed four-gate evaluator."""
    try:
        return _assess_m4_report(report, evidence_dir, True)
    except (KeyError, TypeError, ValueError, OverflowError, OSError, json.JSONDecodeError) as exc:
        return _false_assessment([f"M4 report is malformed or unverifiable: {exc}"])


def write_m4_report(report: Mapping[str, Any], evidence_dir: Path) -> Path:
    """Write a canonical, newline-terminated report, including failed assessments."""
    path = evidence_dir / REPORT_FILENAME
    path.write_bytes(_canonical_json(dict(report)) + b"\n")
    return path
