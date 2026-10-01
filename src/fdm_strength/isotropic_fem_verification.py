"""Solver-backed evidence generation for the isotropic linear-elastic FEM gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

from fdm_strength.fem_models import (
    BoundaryConditionSet,
    GmshMeshSettings,
    IsotropicMaterialProfile,
    IsotropicTensileRequest,
    RectangularTensileSpecimen,
    TensileLoad,
    analytical_tensile_response,
    isotropic_lame_parameters,
)
from fdm_strength.isotropic_fem_stage import (
    _solve_tensile_case,
    isotropic_cauchy_stress,
    isotropic_strain,
)
from fdm_strength.verification import observed_l2_convergence_order, relative_error

_MANUFACTURED_REFINEMENT_LEVELS = 4
_TENSILE_SPECIMEN = RectangularTensileSpecimen(
    specimen_id="M4-ISOTROPIC-PATCH",
    length_mm=40.0,
    width_mm=10.0,
    thickness_mm=2.0,
)
_TENSILE_MATERIAL = IsotropicMaterialProfile(
    profile_id="M4-ISOTROPIC-2000MPA-NU035",
    youngs_modulus_mpa=2000.0,
    poissons_ratio=0.35,
)
_TENSILE_LOAD = TensileLoad(force_n=100.0)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _generate_box_mesh(
    output_path: Path,
    dimensions_mm: tuple[float, float, float],
    max_cell_size_mm: float,
    name: str,
) -> Any:
    import gmsh
    from dolfinx.io import gmsh as gmshio
    from mpi4py import MPI

    comm = MPI.COMM_WORLD
    if comm.size != 1:
        raise ValueError("M4 verification currently requires exactly one MPI rank")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)
        gmsh.model.add(name)
        volume = gmsh.model.occ.addBox(0.0, 0.0, 0.0, *dimensions_mm)
        gmsh.model.occ.synchronize()
        gmsh.model.mesh.setSize(gmsh.model.getEntities(0), max_cell_size_mm)
        gmsh.model.addPhysicalGroup(3, [volume], tag=1)
        gmsh.model.setPhysicalName(3, 1, "specimen")
        gmsh.option.setNumber("Mesh.MeshSizeMin", max_cell_size_mm * 0.5)
        gmsh.option.setNumber("Mesh.MeshSizeMax", max_cell_size_mm)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(output_path))
        return gmshio.model_to_mesh(gmsh.model, comm, rank=0, gdim=3).mesh
    finally:
        gmsh.finalize()


def _mesh_max_edge_length(mesh_path: Path) -> float:
    import meshio
    import numpy as np

    mesh_data = meshio.read(mesh_path)
    tetrahedra = mesh_data.cells_dict.get("tetra")
    if tetrahedra is None or tetrahedra.size == 0:
        raise ValueError(f"mesh has no linear tetrahedra: {mesh_path.name}")
    points = np.asarray(mesh_data.points[:, :3], dtype=np.float64)
    edge_lengths = [
        np.linalg.norm(points[tetrahedra[:, left]] - points[tetrahedra[:, right]], axis=1)
        for left in range(4)
        for right in range(left + 1, 4)
    ]
    return float(max(float(np.max(lengths)) for lengths in edge_lengths))


def _format_node_set(name: str, node_ids: list[int]) -> str:
    if not node_ids:
        raise ValueError(f"CalculiX node set {name} is empty")
    lines = [f"*NSET, NSET={name}"]
    lines.extend(
        ", ".join(str(node_id) for node_id in node_ids[offset : offset + 16])
        for offset in range(0, len(node_ids), 16)
    )
    return "\n".join(lines)


def calculix_input_text(mesh: Any, request: IsotropicTensileRequest) -> str:
    """Create a C3D4 deck with the same mesh, material, and kinematics as the DOLFINx case."""
    import numpy as np

    if request.mesh.element_order != 1:
        raise ValueError("the M4 CalculiX cross-check requires the shared first-order tetra mesh")
    points = np.asarray(mesh.points[:, :3], dtype=np.float64)
    tetrahedra = mesh.cells_dict.get("tetra")
    if tetrahedra is None or tetrahedra.size == 0:
        raise ValueError("CalculiX cross-check requires linear tetrahedral cells")
    if not np.all(np.isfinite(points)):
        raise ValueError("CalculiX mesh coordinates must be finite")

    specimen = request.specimen
    tolerance = max(specimen.length_mm, specimen.width_mm, specimen.thickness_mm) * 1e-10

    def matching_nodes(predicate: Any, label: str) -> list[int]:
        ids = [index + 1 for index, point in enumerate(points) if predicate(point)]
        if not ids:
            raise ValueError(f"CalculiX mesh has no nodes for {label}")
        return ids

    fixed_x = matching_nodes(lambda p: abs(p[0]) <= tolerance, "fixed x face")
    loaded_x = matching_nodes(
        lambda p: abs(p[0] - specimen.length_mm) <= tolerance, "loaded x face"
    )
    origin = matching_nodes(
        lambda p: all(abs(float(p[i])) <= tolerance for i in range(3)), "origin anchor"
    )
    torsion_anchor = matching_nodes(
        lambda p: abs(p[0]) <= tolerance
        and abs(p[1]) <= tolerance
        and abs(p[2] - specimen.thickness_mm) <= tolerance,
        "torsion anchor",
    )
    gauge_mid = matching_nodes(
        lambda p: abs(p[0] - specimen.length_mm / 2.0) <= tolerance,
        "midspan gauge plane",
    )
    analytical = analytical_tensile_response(request)

    lines = [
        "*HEADING",
        "M4 isotropic rectangular tensile verification; lengths mm, force N, stress MPa",
        "*NODE",
    ]
    lines.extend(
        f"{index}, {float(point[0])}, {float(point[1])}, {float(point[2])}"
        for index, point in enumerate(points, start=1)
    )
    lines.append("*ELEMENT, TYPE=C3D4, ELSET=SPECIMEN")
    lines.extend(
        f"{index}, " + ", ".join(str(int(node) + 1) for node in cell)
        for index, cell in enumerate(tetrahedra, start=1)
    )
    lines.extend(
        (
            _format_node_set("FIXED_X", fixed_x),
            _format_node_set("LOADED_X", loaded_x),
            _format_node_set("ORIGIN", origin),
            _format_node_set("TORSION_ANCHOR", torsion_anchor),
            _format_node_set("GAUGE_MID", gauge_mid),
            "*MATERIAL, NAME=ISOTROPIC",
            "*ELASTIC",
            f"{request.material.youngs_modulus_mpa}, {request.material.poissons_ratio}",
            "*SOLID SECTION, ELSET=SPECIMEN, MATERIAL=ISOTROPIC",
            ",",
            "*STEP",
            "*STATIC",
            "1., 1., 1.e-05, 1.",
            "*BOUNDARY",
            "FIXED_X, 1, 1, 0.0",
            f"LOADED_X, 1, 1, {analytical.axial_displacement_mm}",
            "ORIGIN, 2, 2, 0.0",
            "ORIGIN, 3, 3, 0.0",
            "TORSION_ANCHOR, 2, 2, 0.0",
            "*NODE PRINT, NSET=LOADED_X, TOTALS=YES",
            "U, RF",
            "*NODE PRINT, NSET=FIXED_X, TOTALS=YES",
            "RF",
            "*NODE PRINT, NSET=GAUGE_MID",
            "U",
            "*NODE FILE",
            "U, RF",
            "*EL FILE",
            "S",
            "*END STEP",
        )
    )
    return "\n".join(lines) + "\n"


def parse_calculix_dat(dat_text: str) -> dict[str, float]:
    """Extract mean midspan axial displacement and loaded-face resultant from CCX text output."""
    number = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)"
    gauge_match = re.search(
        r"displacements\s+\(vx,vy,vz\)\s+for set GAUGE_MID and time[^\n]*\n"
        r"(.*?)(?=\n\s*(?:displacements|forces|total force)\s+\(|\Z)",
        dat_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if gauge_match is None:
        raise ValueError("CalculiX output is missing GAUGE_MID displacement rows")
    gauge_rows = re.findall(
        rf"^\s*\d+\s+{number}\s+{number}\s+{number}\s*$",
        gauge_match.group(1),
        flags=re.MULTILINE,
    )
    if not gauge_rows:
        raise ValueError("CalculiX GAUGE_MID output contains no displacement values")
    total_force_match = re.search(
        rf"total force\s+\(fx,fy,fz\)\s+for set LOADED_X and time[^\n]*\n"
        rf"\s*{number}\s+{number}\s+{number}",
        dat_text,
        flags=re.IGNORECASE,
    )
    if total_force_match is None:
        raise ValueError("CalculiX output is missing the LOADED_X total reaction force")
    gauge_axial = [float(row[0]) for row in gauge_rows]
    loaded_force_x = float(total_force_match.group(1))
    if not all(math.isfinite(value) for value in (*gauge_axial, loaded_force_x)):
        raise ValueError("CalculiX output contains non-finite verification quantities")
    return {
        "midspan_axial_displacement_mm": sum(gauge_axial) / len(gauge_axial),
        "loaded_face_reaction_force_n": loaded_force_x,
    }


def _manufactured_relative_l2_error(
    domain: Any, element_order: int
) -> tuple[float, int, dict[str, int]]:
    import numpy as np
    import ufl
    from dolfinx import fem
    from dolfinx.fem.petsc import LinearProblem
    from mpi4py import MPI

    youngs_modulus_mpa = 2000.0
    poissons_ratio = 0.3
    lame_lambda, mu = isotropic_lame_parameters(youngs_modulus_mpa, poissons_ratio)
    space = fem.functionspace(domain, ("Lagrange", element_order, (3,)))
    trial = ufl.TrialFunction(space)
    test = ufl.TestFunction(space)
    x = ufl.SpatialCoordinate(domain)
    exact = ufl.as_vector((x[0] ** 3, x[1] ** 3, x[2] ** 3))
    body_force = -6.0 * (lame_lambda + 2.0 * mu) * ufl.as_vector((x[0], x[1], x[2]))
    exact_boundary = fem.Function(space)
    exact_boundary.interpolate(
        lambda coordinates: np.vstack(
            (coordinates[0] ** 3, coordinates[1] ** 3, coordinates[2] ** 3)
        )
    )
    def on_boundary(coordinates: Any) -> Any:
        at_unit_cube_face = np.isclose(coordinates, 0.0, atol=1e-12, rtol=0.0) | np.isclose(
            coordinates, 1.0, atol=1e-12, rtol=0.0
        )
        return np.any(at_unit_cube_face, axis=0)

    boundary_dofs = fem.locate_dofs_geometrical(space, on_boundary)
    block_size = int(space.dofmap.index_map_bs)
    total_dof_count = int(space.dofmap.index_map.size_global * block_size)
    boundary_dof_count = int(boundary_dofs.size * block_size)
    free_dof_count = total_dof_count - boundary_dof_count
    if free_dof_count <= 0:
        raise ValueError(
            f"manufactured P{element_order} mesh has no free interior degrees of freedom"
        )
    boundary_condition = fem.dirichletbc(exact_boundary, boundary_dofs)
    dx = ufl.Measure("dx", domain=domain)
    bilinear = ufl.inner(
        isotropic_cauchy_stress(trial, youngs_modulus_mpa, poissons_ratio, ufl),
        isotropic_strain(test, ufl),
    ) * dx
    linear = ufl.inner(body_force, test) * dx
    problem = LinearProblem(
        bilinear,
        linear,
        bcs=[boundary_condition],
        petsc_options={
            "ksp_type": "preonly",
            "pc_type": "lu",
            "pc_factor_mat_solver_type": "mumps",
        },
        petsc_options_prefix=f"fdm_m4_manufactured_p{element_order}_",
    )
    displacement = problem.solve()
    error_squared = fem.assemble_scalar(
        fem.form(ufl.inner(displacement - exact, displacement - exact) * dx)
    )
    exact_squared = fem.assemble_scalar(fem.form(ufl.inner(exact, exact) * dx))
    global_error_squared = domain.comm.allreduce(error_squared, op=MPI.SUM)
    global_exact_squared = domain.comm.allreduce(exact_squared, op=MPI.SUM)
    if global_exact_squared <= 0:
        raise ValueError("manufactured exact solution has a zero L2 norm")
    return (
        math.sqrt(global_error_squared / global_exact_squared),
        int(problem.solver.getIterationNumber()),
        {
            "boundary_dof_count": boundary_dof_count,
            "free_dof_count": free_dof_count,
            "total_dof_count": total_dof_count,
        },
    )


def _run_manufactured_convergence(output_dir: Path) -> dict[str, Any]:
    mesh_sizes: list[float] = []
    target_sizes: list[float] = []
    errors: dict[str, list[float]] = {"p1": [], "p2": []}
    solver_iterations: dict[str, list[int]] = {"p1": [], "p2": []}
    solver_diagnostics: dict[str, list[dict[str, int]]] = {"p1": [], "p2": []}
    mesh_names: list[str] = []
    target_size = 0.8
    for index in range(_MANUFACTURED_REFINEMENT_LEVELS):
        mesh_name = f"manufactured-level-{index + 1}.msh"
        mesh_path = output_dir / mesh_name
        previous_size = mesh_sizes[-1] if mesh_sizes else None
        for attempt in range(8):
            domain = _generate_box_mesh(
                mesh_path,
                (1.0, 1.0, 1.0),
                target_size,
                f"m4_manufactured_level_{index + 1}",
            )
            mesh_size = _mesh_max_edge_length(mesh_path)
            if previous_size is None or mesh_size < previous_size:
                break
            target_size *= 0.65
        else:
            raise ValueError("Gmsh could not produce a strictly refined manufactured mesh")
        mesh_sizes.append(mesh_size)
        target_sizes.append(target_size)
        mesh_names.append(mesh_name)
        for order, label in ((1, "p1"), (2, "p2")):
            error, iterations, diagnostics = _manufactured_relative_l2_error(domain, order)
            errors[label].append(error)
            solver_iterations[label].append(iterations)
            solver_diagnostics[label].append(diagnostics)
        target_size = min(target_size * 0.65, mesh_size * 0.65)

    return {
        "metrics": {
            "p1_l2_order": observed_l2_convergence_order(mesh_sizes, errors["p1"]),
            "p2_l2_order": observed_l2_convergence_order(mesh_sizes, errors["p2"]),
        },
        "mesh_sizes_mm": mesh_sizes,
        "target_sizes_mm": target_sizes,
        "relative_l2_errors": errors,
        "solver_iterations": solver_iterations,
        "solver_diagnostics": solver_diagnostics,
        "element_orders": {"p1": 1, "p2": 2},
        "artifacts": mesh_names,
    }


def _run_tensile_patch(output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    tensile_dir = output_dir / "tensile"
    tensile_dir.mkdir(parents=True, exist_ok=True)
    request = IsotropicTensileRequest(
        specimen=_TENSILE_SPECIMEN,
        material=_TENSILE_MATERIAL,
        load=_TENSILE_LOAD,
        boundary_conditions=BoundaryConditionSet(set_id="m4-tensile-uniaxial-v1"),
        mesh=GmshMeshSettings(max_cell_size_mm=2.5, element_order=1, optimize=False),
    )
    solver_output = _solve_tensile_case(request, tensile_dir, include_midspan_gauge=True)
    shutil.copyfile(tensile_dir / "mesh.msh", output_dir / "tensile-mesh.msh")
    import meshio

    tensile_mesh = meshio.read(tensile_dir / "mesh.msh")
    (output_dir / "tensile.inp").write_text(
        calculix_input_text(tensile_mesh, request), encoding="ascii", newline="\n"
    )
    result = solver_output["result"]
    analytical = analytical_tensile_response(request)
    measured_strain = result["measured_axial_displacement_mm"] / _TENSILE_SPECIMEN.length_mm
    metrics = {
        "stress_uniformity_relative_range": result["axial_stress_uniformity_relative_range"],
        "stress_relative_error": relative_error(
            result["volume_average_axial_stress_mpa"], analytical.nominal_stress_mpa
        ),
        "strain_relative_error": relative_error(measured_strain, analytical.nominal_strain),
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
        "stress_uniformity_relative_range": metrics["stress_uniformity_relative_range"],
        "displacement_relative_error": metrics["displacement_relative_error"],
        "reaction_force_relative_error": metrics["reaction_force_relative_error"],
    }
    detail = {
        "specimen": _TENSILE_SPECIMEN.model_dump(mode="json"),
        "material": _TENSILE_MATERIAL.model_dump(mode="json"),
        "load": _TENSILE_LOAD.model_dump(mode="json"),
        "boundary_conditions": request.boundary_conditions.model_dump(mode="json"),
        "mesh": request.mesh.model_dump(mode="json"),
        "analytical_reference": analytical.model_dump(mode="json"),
        "solver_result": result,
        "solver_iterations": solver_output["solver_iterations"],
        "solver_residual_norm": solver_output["solver_residual_norm"],
    }
    _write_json(output_dir / "tensile-result.json", detail)
    return patch_metrics, metrics


def run_dolfinx_verification(output_dir: Path) -> dict[str, Any]:
    """Run the actual DOLFINx convergence, patch, and analytical tensile cases."""
    import gmsh
    import numpy
    import petsc4py
    import ufl
    from dolfinx import __version__ as dolfinx_version

    output_dir.mkdir(parents=True, exist_ok=True)
    manufactured = _run_manufactured_convergence(output_dir)
    patch_metrics, analytical_metrics = _run_tensile_patch(output_dir)
    report = {
        "schema_version": 1,
        "solver": {
            "name": "DOLFINx",
            "version": dolfinx_version,
            "gmsh_version": gmsh.__version__,
            "numpy_version": numpy.__version__,
            "petsc4py_version": petsc4py.__version__,
            "ufl_version": ufl.__version__,
            "mpi_ranks": 1,
            "omp_threads": 1,
            "blas_threads": 1,
        },
        "solver_source_sha256": solver_source_sha256(),
        "gates": {
            "manufactured_solution": manufactured,
            "uniform_stress_patch": {
                "metrics": patch_metrics,
                "artifacts": ["tensile-result.json", "tensile-mesh.msh", "tensile.inp"],
            },
            "analytical_agreement": {
                "metrics": analytical_metrics,
                "artifacts": ["tensile-result.json", "tensile-mesh.msh", "tensile.inp"],
            },
        },
    }
    _write_json(output_dir / "dolfinx-evidence.json", report)
    return report


def solver_source_sha256() -> dict[str, str]:
    """Hash the solver modules as they exist inside the executing DOLFINx image."""
    source_root = Path(__file__).resolve().parent
    source_files = (
        "fem_models.py",
        "isotropic_fem_stage.py",
        "isotropic_fem_verification.py",
        "verification.py",
    )
    return {
        f"src/fdm_strength/{name}": hashlib.sha256((source_root / name).read_bytes()).hexdigest()
        for name in source_files
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dolfinx_verification(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
