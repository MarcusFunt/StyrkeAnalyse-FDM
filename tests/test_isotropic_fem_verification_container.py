"""Real DOLFINx numerical verification executed by the pinned FEM container."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


def test_pinned_container_generates_passing_dolfinx_m4_cases(tmp_path: Path) -> None:
    image = os.environ.get("FDM_ISOTROPIC_FEM_IMAGE")
    if not image:
        pytest.skip("set FDM_ISOTROPIC_FEM_IMAGE to run the solver-backed M4 cases")

    output_dir = tmp_path / "m4-evidence"
    output_dir.mkdir()
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0:0",
            "--volume",
            f"{output_dir.resolve().as_posix()}:/verification",
            "--env",
            "OMP_NUM_THREADS=1",
            "--env",
            "OPENBLAS_NUM_THREADS=1",
            "--env",
            "MKL_NUM_THREADS=1",
            "--env",
            "NUMEXPR_NUM_THREADS=1",
            image,
            "python",
            "-m",
            "fdm_strength.isotropic_fem_verification",
            "--output-dir",
            "/verification",
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    report = json.loads((output_dir / "dolfinx-evidence.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    manufactured = report["gates"]["manufactured_solution"]["metrics"]
    assert manufactured["p1_l2_order"] >= 1.9
    assert manufactured["p2_l2_order"] >= 2.9
    diagnostics = report["gates"]["manufactured_solution"]["solver_diagnostics"]
    assert all(item["free_dof_count"] > 0 for item in diagnostics["p1"])
    assert all(item["free_dof_count"] > 0 for item in diagnostics["p2"])
    assert all(
        item["boundary_dof_count"] < item["total_dof_count"]
        for level_group in diagnostics.values()
        for item in level_group
    )
    patch = report["gates"]["uniform_stress_patch"]["metrics"]
    assert patch["stress_uniformity_relative_range"] <= 1e-12
    assert patch["displacement_relative_error"] <= 0.001
    assert patch["reaction_force_relative_error"] <= 0.001
    analytical = report["gates"]["analytical_agreement"]["metrics"]
    assert analytical["stress_relative_error"] <= 0.001
    assert analytical["strain_relative_error"] <= 0.001
    assert analytical["displacement_relative_error"] <= 0.001
    assert analytical["reaction_force_relative_error"] <= 0.001
    assert (output_dir / "manufactured-level-1.msh").is_file()
    assert (output_dir / "manufactured-level-4.msh").is_file()
    assert (output_dir / "tensile-mesh.msh").is_file()
