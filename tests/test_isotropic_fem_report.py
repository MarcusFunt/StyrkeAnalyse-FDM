"""Report assembly and fail-closed validation for solver-backed M4 evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fdm_strength.isotropic_fem_report import assess_m4_report, build_m4_report
from fdm_strength.isotropic_fem_verification import solver_source_sha256

_DOLFINX_IMAGE = "sha256:" + "a" * 64
_CALCULIX_IMAGE = "sha256:" + "b" * 64
_IMAGE_LABELS = {
    "org.opencontainers.image.revision": "a" * 40,
    "fdm.git.commit": "a" * 40,
    "fdm.git.dirty": "false",
}


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _solver_outputs(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "manufactured-level-1.msh": b"mesh 1",
        "manufactured-level-2.msh": b"mesh 2",
        "manufactured-level-3.msh": b"mesh 3",
        "manufactured-level-4.msh": b"mesh 4",
        "tensile-mesh.msh": b"tensile mesh",
        "tensile.inp": b"calculix deck",
        "tensile.dat": b"solver output",
        "tensile.frd": b"field output",
    }
    for name, content in files.items():
        (directory / name).write_bytes(content)
    _write_json(
        directory / "tensile-result.json",
        {
            "specimen": {
                "specimen_id": "M4",
                "length_mm": 40.0,
                "width_mm": 10.0,
                "thickness_mm": 2.0,
            },
            "material": {
                "profile_id": "PLA",
                "youngs_modulus_mpa": 2000.0,
                "poissons_ratio": 0.35,
            },
            "load": {"force_n": 100.0},
            "boundary_conditions": {"set_id": "pull-v1"},
            "mesh": {"max_cell_size_mm": 2.5, "element_order": 1, "optimize": False},
            "analytical_reference": {
                "cross_section_area_mm2": 20.0,
                "nominal_stress_mpa": 5.0,
                "nominal_strain": 0.0025,
                "axial_displacement_mm": 0.1,
                "reaction_force_n": 100.0,
            },
            "solver_result": {
                "axial_stress_uniformity_relative_range": 0.0,
                "volume_average_axial_stress_mpa": 5.0,
                "measured_axial_displacement_mm": 0.1,
                "measured_midspan_displacement_mm": 0.05,
                "reaction_force_n": 100.0,
            },
        },
    )
    _write_json(
        directory / "dolfinx-evidence.json",
        {
            "schema_version": 1,
            "solver": {
                "name": "DOLFINx",
                "version": "0.11.0",
                "mpi_ranks": 1,
                "omp_threads": 1,
                "blas_threads": 1,
            },
            "solver_source_sha256": solver_source_sha256(),
            "gates": {
                "manufactured_solution": {
                    "metrics": {"p1_l2_order": 2.0, "p2_l2_order": 3.0},
                    "mesh_sizes_mm": [4.0, 3.0, 2.0, 1.0],
                    "relative_l2_errors": {
                        "p1": [0.16, 0.09, 0.04, 0.01],
                        "p2": [0.064, 0.027, 0.008, 0.001],
                    },
                    "solver_diagnostics": {
                        order: [
                            {
                                "boundary_dof_count": 10,
                                "free_dof_count": 10,
                                "total_dof_count": 20,
                            }
                            for _ in range(4)
                        ]
                        for order in ("p1", "p2")
                    },
                    "artifacts": [f"manufactured-level-{index}.msh" for index in range(1, 5)],
                },
                "uniform_stress_patch": {
                    "metrics": {
                        "stress_uniformity_relative_range": 0.0,
                        "displacement_relative_error": 0.0,
                        "reaction_force_relative_error": 0.0,
                    },
                    "artifacts": ["tensile-result.json", "tensile-mesh.msh"],
                },
                "analytical_agreement": {
                    "metrics": {
                        "stress_uniformity_relative_range": 0.0,
                        "stress_relative_error": 0.0,
                        "strain_relative_error": 0.0,
                        "displacement_relative_error": 0.0,
                        "midspan_displacement_relative_error": 0.0,
                        "reaction_force_relative_error": 0.0,
                    },
                    "artifacts": ["tensile-result.json", "tensile-mesh.msh"],
                },
            },
        },
    )
    (directory / "tensile.dat").write_text(
        """
 displacements (vx,vy,vz) for set GAUGE_MID and time  0.1000000E+01
        1  5.000000E-02  0.000000E+00  0.000000E+00
 total force (fx,fy,fz) for set LOADED_X and time  0.1000000E+01
        1.000000E+02  0.000000E+00  0.000000E+00
""",
        encoding="ascii",
    )


def test_m4_report_hashes_solver_artifacts_and_accepts_complete_evidence(tmp_path: Path) -> None:
    _solver_outputs(tmp_path)

    report = build_m4_report(
        tmp_path,
        dolfinx_image_digest=_DOLFINX_IMAGE,
        calculix_image_digest=_CALCULIX_IMAGE,
        dolfinx_image_labels=_IMAGE_LABELS,
        calculix_image_labels=_IMAGE_LABELS,
        calculix_version="2.21",
        git_commit="a" * 40,
    )

    assert report["schema_version"] == 1
    assert report["assessment"]["comparison_allowed"] is True
    assert set(report["gates"]) == {
        "manufactured_solution",
        "uniform_stress_patch",
        "analytical_agreement",
        "calculix_crosscheck",
    }
    assert report["gates"]["calculix_crosscheck"]["metrics"] == {
        "relative_midspan_displacement_error": 0.0,
        "relative_reaction_force_error": 0.0,
    }
    assert all(len(item["sha256"]) == 64 for item in report["artifacts"])
    assert report["model"]["configuration"]["solver_resources"] == {
        "mpi_ranks": 1,
        "omp_threads": 1,
        "blas_threads": 1,
    }
    assert report["model"]["configuration"]["verification_source_sha256"]
    assert assess_m4_report(report, tmp_path).comparison_allowed is True


def test_m4_report_fails_closed_for_tampered_artifact_digest_or_missing_gate(
    tmp_path: Path,
) -> None:
    _solver_outputs(tmp_path)
    report = build_m4_report(
        tmp_path,
        dolfinx_image_digest=_DOLFINX_IMAGE,
        calculix_image_digest=_CALCULIX_IMAGE,
        dolfinx_image_labels=_IMAGE_LABELS,
        calculix_image_labels=_IMAGE_LABELS,
        calculix_version="2.21",
        git_commit="a" * 40,
    )

    altered_digest = json.loads(json.dumps(report))
    altered_digest["model"]["digest"] = "sha256:" + "c" * 64
    assert assess_m4_report(altered_digest, tmp_path).comparison_allowed is False

    changed_artifact = json.loads(json.dumps(report))
    (tmp_path / "tensile-mesh.msh").write_bytes(b"different mesh")
    assert assess_m4_report(changed_artifact, tmp_path).comparison_allowed is False

    missing_gate = json.loads(json.dumps(report))
    del missing_gate["gates"]["calculix_crosscheck"]
    assert assess_m4_report(missing_gate, tmp_path).comparison_allowed is False

    altered_summary = json.loads(json.dumps(report))
    altered_summary["assessment"]["failed_gates"] = ["manufactured_solution"]
    assert assess_m4_report(altered_summary, tmp_path).comparison_allowed is False


def test_m4_report_rejects_artifact_paths_outside_evidence_directory(tmp_path: Path) -> None:
    _solver_outputs(tmp_path)
    report = build_m4_report(
        tmp_path,
        dolfinx_image_digest=_DOLFINX_IMAGE,
        calculix_image_digest=_CALCULIX_IMAGE,
        dolfinx_image_labels=_IMAGE_LABELS,
        calculix_image_labels=_IMAGE_LABELS,
        calculix_version="2.21",
        git_commit="a" * 40,
    )
    report["artifacts"][0]["path"] = "../outside.bin"

    assessment = assess_m4_report(report, tmp_path)

    assert assessment.comparison_allowed is False
    assert any("artifact path" in blocker for blocker in assessment.blockers)


def test_m4_report_rejects_passing_metrics_without_referenced_solver_artifacts(
    tmp_path: Path,
) -> None:
    _solver_outputs(tmp_path)
    report = build_m4_report(
        tmp_path,
        dolfinx_image_digest=_DOLFINX_IMAGE,
        calculix_image_digest=_CALCULIX_IMAGE,
        dolfinx_image_labels=_IMAGE_LABELS,
        calculix_image_labels=_IMAGE_LABELS,
        calculix_version="2.21",
        git_commit="a" * 40,
    )
    empty_set_digest = hashlib.sha256(b"[]").hexdigest()
    report["artifacts"] = []
    for gate in report["gates"].values():
        gate["artifact_paths"] = []
        gate["artifact_sha256"] = empty_set_digest

    assessment = assess_m4_report(report, tmp_path)

    assert assessment.comparison_allowed is False


def test_m4_report_recomputes_manufactured_metrics_from_solver_evidence(tmp_path: Path) -> None:
    _solver_outputs(tmp_path)
    report = build_m4_report(
        tmp_path,
        dolfinx_image_digest=_DOLFINX_IMAGE,
        calculix_image_digest=_CALCULIX_IMAGE,
        dolfinx_image_labels=_IMAGE_LABELS,
        calculix_image_labels=_IMAGE_LABELS,
        calculix_version="2.21",
        git_commit="a" * 40,
    )
    report["gates"]["manufactured_solution"]["metrics"]["p1_l2_order"] = 100.0

    assessment = assess_m4_report(report, tmp_path)

    assert assessment.comparison_allowed is False
