"""Baked Gmsh + DOLFINx execution entrypoint for the first formal FEM stage."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fdm_strength.fem_models import (
    IsotropicTensileRequest,
    analytical_tensile_response,
    canonical_json_bytes,
    isotropic_lame_parameters,
    model_sha256,
)
from fdm_strength.fem_preview import build_surface_field_preview
from fdm_strength.provenance import ProvenanceArtifact, StageProvenance
from fdm_strength.stage_contract import StageContract, load_stage_contract, read_stage_outputs

STAGE_ID = "fdm-l2-isotropic"
OPERATION = "fdm-l2-isotropic"
DOLFINX_SOLVER_VERSION = "0.11.0.post0"
EXPECTED_OUTPUTS = (
    "result.json",
    "mesh.msh",
    "fields.xdmf",
    "fields.h5",
    "field-preview.json",
    "provenance.json",
)
SOLVER_ARTIFACT_OUTPUTS = ("mesh.msh", "fields.xdmf", "fields.h5", "field-preview.json")

_OUTPUT_MEDIA_TYPES = {
    "result.json": "application/vnd.styrkeanalyse.fem-result+json",
    "mesh.msh": "application/vnd.gmsh.msh",
    "fields.xdmf": "application/vnd.xdmf+xml",
    "fields.h5": "application/x-hdf5",
    "field-preview.json": "application/vnd.styrkeanalyse.fem-field-preview+json",
}


def isotropic_strain(displacement: Any, ufl: Any) -> Any:
    """Return the small-strain tensor used by both production and verification solves."""
    return ufl.sym(ufl.grad(displacement))


def isotropic_cauchy_stress(
    displacement: Any,
    youngs_modulus_mpa: float,
    poissons_ratio: float,
    ufl: Any,
) -> Any:
    """Return the isotropic linear-elastic stress expression used by all FEM cases."""
    lame_lambda, mu = isotropic_lame_parameters(youngs_modulus_mpa, poissons_ratio)
    epsilon = isotropic_strain(displacement, ufl)
    return lame_lambda * ufl.tr(epsilon) * ufl.Identity(3) + 2.0 * mu * epsilon


def _tetrahedron_corner_dofs(geometry_dofmap: Any) -> Any:
    """Return the four vertex geometry DOFs from DOLFINx's P1 or P2 cell map."""
    import numpy as np

    cell_dofs = np.asarray(geometry_dofmap)
    if cell_dofs.ndim != 2 or cell_dofs.shape[1] < 4:
        raise ValueError("tetrahedral geometry maps require at least four geometry nodes per cell")
    corner_dofs = np.ascontiguousarray(cell_dofs[:, :4], dtype=np.int64)
    if np.any(corner_dofs < 0) or np.any(np.diff(np.sort(corner_dofs, axis=1), axis=1) == 0):
        raise ValueError("tetrahedral geometry maps contain invalid corner DOFs")
    return corner_dofs


def _collect_solver_artifacts(output_root: Path) -> dict[str, bytes]:
    """Read the mesh and fields created by the solver before result.json is written."""
    artifact_contents = {
        name: (output_root / name).read_bytes()
        for name in SOLVER_ARTIFACT_OUTPUTS
        if (output_root / name).is_file()
    }
    if set(artifact_contents) != set(SOLVER_ARTIFACT_OUTPUTS):
        raise ValueError("solver did not create the full mesh and field artifact set")
    return artifact_contents


def validate_stage_request(contract: StageContract, request: IsotropicTensileRequest) -> None:
    """Bind the request's scientific identities and mesh controls to its immutable contract."""
    if contract.schema_version != 2:
        raise ValueError("fdm-l2-isotropic requires stage contract version 2")
    if contract.stage_id != STAGE_ID or contract.operation != OPERATION:
        raise ValueError("stage contract does not identify fdm-l2-isotropic")
    if contract.solver_name != "DOLFINx" or contract.solver_version != DOLFINX_SOLVER_VERSION:
        raise ValueError(
            f"stage contract must pin the DOLFINx solver version {DOLFINX_SOLVER_VERSION}"
        )
    if contract.image_reference is None or contract.image_digest is None:
        raise ValueError("formal isotropic FEM requires an immutable stage image")
    if (
        contract.base_image_reference is None
        or re.search(r"@sha256:[0-9a-f]{64}$", contract.base_image_reference) is None
    ):
        raise ValueError("formal isotropic FEM requires a digest-pinned base image")
    if contract.dependency_lock_sha256 is None:
        raise ValueError("formal isotropic FEM requires a dependency-lock hash")
    if (
        contract.git_commit is None
        or re.fullmatch(r"[0-9a-f]{40}", contract.git_commit) is None
        or contract.git_dirty is not False
    ):
        raise ValueError("formal isotropic FEM requires a clean source revision")
    if contract.mpi_ranks != 1:
        raise ValueError("fdm-l2-isotropic currently supports exactly one explicit MPI rank")
    if tuple(contract.expected_outputs) != EXPECTED_OUTPUTS:
        raise ValueError("stage outputs do not match the fdm-l2-isotropic contract")
    if contract.parameters:
        raise ValueError("all scientific inputs must be sealed in request.json")
    if len(contract.inputs) != 1 or contract.inputs[0].name != "request.json":
        raise ValueError("fdm-l2-isotropic requires exactly one request.json input")

    request_bytes = canonical_json_bytes(request)
    if contract.inputs[0].sha256 != hashlib.sha256(request_bytes).hexdigest() or contract.inputs[
        0
    ].size_bytes != len(request_bytes):
        raise ValueError("request.json does not match its immutable input identity")

    if (
        contract.material_profile_id != request.material.profile_id
        or contract.material_profile_sha256 != model_sha256(request.material)
    ):
        raise ValueError("material profile identity or hash does not match request.json")
    if (
        contract.boundary_condition_set_id != request.boundary_conditions.set_id
        or contract.boundary_condition_set_sha256 != model_sha256(request.boundary_conditions)
    ):
        raise ValueError("boundary-condition identity or hash does not match request.json")
    if contract.mesh_parameters != request.mesh.model_dump(mode="json"):
        raise ValueError("mesh settings do not match request.json")
    if contract.mesh_sha256 is not None:
        raise ValueError("the mesh is generated by this stage and cannot be an input hash")


def _require_runtime_policy(contract: StageContract, comm: Any) -> None:
    if comm.size != contract.mpi_ranks:
        raise ValueError("MPI world size does not match the immutable stage contract")
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        if os.environ.get(variable) != str(contract.omp_threads):
            raise ValueError(f"{variable} does not match the immutable thread policy")


def _solve_tensile_case(
    request: IsotropicTensileRequest,
    output_root: Path,
    *,
    include_midspan_gauge: bool = False,
) -> dict[str, Any]:
    """Generate a tetrahedral mesh and solve small-strain 3D isotropic elasticity."""
    import gmsh
    import numpy as np
    import ufl
    from dolfinx import __version__ as dolfinx_version
    from dolfinx import fem
    from dolfinx import mesh as dmesh
    from dolfinx.fem.petsc import LinearProblem
    from dolfinx.io import XDMFFile
    from dolfinx.io import gmsh as gmshio
    from mpi4py import MPI
    from petsc4py import PETSc

    comm = MPI.COMM_WORLD
    rank = comm.rank
    specimen = request.specimen
    material = request.material
    length = specimen.length_mm
    width = specimen.width_mm
    thickness = specimen.thickness_mm
    mesh_path = output_root / "mesh.msh"

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        if rank == 0:
            gmsh.model.add("rectangular_tensile_specimen")
            if include_midspan_gauge:
                # The verification mesh is partitioned at its gauge plane so both
                # DOLFINx and CalculiX measure displacement at the same nodes.
                left = gmsh.model.occ.addBox(0.0, 0.0, 0.0, length / 2.0, width, thickness)
                right = gmsh.model.occ.addBox(
                    length / 2.0, 0.0, 0.0, length / 2.0, width, thickness
                )
                fragments, _ = gmsh.model.occ.fragment([(3, left), (3, right)], [])
                volumes = [tag for dimension, tag in fragments if dimension == 3]
            else:
                volumes = [gmsh.model.occ.addBox(0.0, 0.0, 0.0, length, width, thickness)]
            gmsh.model.occ.synchronize()
            gmsh.model.addPhysicalGroup(3, volumes, tag=1)
            gmsh.model.setPhysicalName(3, 1, "specimen")
            gmsh.option.setNumber("Mesh.MeshSizeMin", request.mesh.max_cell_size_mm * 0.2)
            gmsh.option.setNumber("Mesh.MeshSizeMax", request.mesh.max_cell_size_mm)
            gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)
            gmsh.model.mesh.generate(3)
            gmsh.model.mesh.setOrder(request.mesh.element_order)
            if request.mesh.optimize and request.mesh.element_order > 1:
                gmsh.model.mesh.optimize("HighOrder")
            gmsh.write(str(mesh_path))

        mesh_data = gmshio.model_to_mesh(gmsh.model, comm, rank=0, gdim=3)
    finally:
        gmsh.finalize()

    domain = mesh_data.mesh
    degree = request.mesh.element_order
    V = fem.functionspace(domain, ("Lagrange", degree, (3,)))
    trial = ufl.TrialFunction(V)
    test = ufl.TestFunction(V)
    identity = ufl.Identity(3)

    def strain(displacement):
        return isotropic_strain(displacement, ufl)

    def cauchy_stress(displacement):
        return isotropic_cauchy_stress(
            displacement,
            material.youngs_modulus_mpa,
            material.poissons_ratio,
            ufl,
        )

    epsilon = np.finfo(np.float64).eps * max(length, width, thickness) * 128

    def x_min(x):
        return np.isclose(x[0], 0.0, atol=epsilon, rtol=0.0)

    def x_max(x):
        return np.isclose(x[0], length, atol=epsilon, rtol=0.0)

    def origin(x):
        return (
            np.isclose(x[0], 0.0, atol=epsilon, rtol=0.0)
            & np.isclose(x[1], 0.0, atol=epsilon, rtol=0.0)
            & np.isclose(x[2], 0.0, atol=epsilon, rtol=0.0)
        )

    def torsion_anchor(x):
        return (
            np.isclose(x[0], 0.0, atol=epsilon, rtol=0.0)
            & np.isclose(x[1], 0.0, atol=epsilon, rtol=0.0)
            & np.isclose(x[2], thickness, atol=epsilon, rtol=0.0)
        )

    analytical = analytical_tensile_response(request)

    def boundary_condition(subspace, marker, value):
        collapsed_subspace, _ = subspace.collapse()
        dof_pair = fem.locate_dofs_geometrical((subspace, collapsed_subspace), marker)
        dofs = np.ascontiguousarray(dof_pair[0], dtype=np.int32)
        if dofs.size == 0:
            raise ValueError("Gmsh mesh is missing a required tensile boundary node")
        return fem.dirichletbc(PETSc.ScalarType(value), dofs, subspace)

    bcs = [
        boundary_condition(V.sub(0), x_min, 0.0),
        boundary_condition(V.sub(0), x_max, analytical.axial_displacement_mm),
        boundary_condition(V.sub(1), origin, 0.0),
        boundary_condition(V.sub(2), origin, 0.0),
        # The additional y pin removes rigid rotation about the x axis.
        boundary_condition(V.sub(1), torsion_anchor, 0.0),
    ]
    dx = ufl.Measure("dx", domain=domain)
    bilinear = ufl.inner(cauchy_stress(trial), strain(test)) * dx
    zero_body_force = fem.Constant(domain, np.zeros(3, dtype=PETSc.ScalarType))
    linear = ufl.inner(zero_body_force, test) * dx
    problem = LinearProblem(
        bilinear,
        linear,
        bcs=bcs,
        petsc_options={
            "ksp_type": "preonly",
            "pc_type": "lu",
            "pc_factor_mat_solver_type": "mumps",
        },
        petsc_options_prefix="fdm_l2_isotropic_",
    )
    displacement = problem.solve()
    displacement.name = "displacement_mm"
    displacement.x.scatter_forward()

    stress_expr = cauchy_stress(displacement)
    stress_space = fem.functionspace(domain, ("Lagrange", degree, (3, 3)))
    stress_field = fem.Function(stress_space, name="cauchy_stress_mpa")
    stress_field.interpolate(fem.Expression(stress_expr, stress_space.element.interpolation_points))
    stress_field.x.scatter_forward()
    deviator = stress_expr - (ufl.tr(stress_expr) / 3.0) * identity
    von_mises_space = fem.functionspace(domain, ("Lagrange", degree))
    von_mises_field = fem.Function(von_mises_space, name="von_mises_stress_mpa")
    von_mises_expr = ufl.sqrt(1.5 * ufl.inner(deviator, deviator))
    von_mises_field.interpolate(
        fem.Expression(von_mises_expr, von_mises_space.element.interpolation_points)
    )
    von_mises_field.x.scatter_forward()

    fdim = domain.topology.dim - 1
    domain.topology.create_connectivity(fdim, domain.topology.dim)
    right_facets = np.unique(dmesh.locate_entities_boundary(domain, fdim, x_max).astype(np.int32))
    if right_facets.size == 0:
        raise ValueError("Gmsh mesh has no loaded-face facets")
    right_tags = dmesh.meshtags(
        domain,
        fdim,
        right_facets,
        np.full(right_facets.size, 1, dtype=np.int32),
    )
    ds = ufl.Measure("ds", domain=domain, subdomain_data=right_tags)

    def assemble_global(expression):
        local_value = fem.assemble_scalar(fem.form(expression))
        return comm.allreduce(local_value, op=MPI.SUM)

    domain_volume = float(assemble_global(1.0 * dx))
    reaction = float(assemble_global(stress_expr[0, 0] * ds(1)))
    mean_axial_stress = float(assemble_global(stress_expr[0, 0] * dx) / domain_volume)
    strain_energy = float(0.5 * assemble_global(ufl.inner(stress_expr, strain(displacement)) * dx))

    axial_displacement = displacement.sub(0).collapse()
    axial_displacement.x.scatter_forward()
    dof_coordinates = axial_displacement.function_space.tabulate_dof_coordinates()
    at_loaded_end = np.isclose(dof_coordinates[:, 0], length, atol=epsilon, rtol=0.0)
    if not np.any(at_loaded_end):
        raise ValueError("finite-element solution has no degrees of freedom on the loaded face")
    measured_extension = float(np.max(axial_displacement.x.array[at_loaded_end]))
    at_midspan = np.isclose(dof_coordinates[:, 0], length / 2.0, atol=epsilon, rtol=0.0)
    measured_midspan_displacement = (
        float(np.mean(axial_displacement.x.array[at_midspan])) if np.any(at_midspan) else None
    )
    if include_midspan_gauge and measured_midspan_displacement is None:
        raise ValueError("verification mesh is missing its partitioned midspan gauge plane")
    nominal_strain = measured_extension / length

    local_stress = stress_field.x.array.reshape((-1, 3, 3))[:, 0, 0]
    stress_min = float(comm.allreduce(float(np.min(local_stress)), op=MPI.MIN))
    stress_max = float(comm.allreduce(float(np.max(local_stress)), op=MPI.MAX))
    local_vm_max = float(np.max(von_mises_field.x.array))
    peak_von_mises = float(comm.allreduce(local_vm_max, op=MPI.MAX))
    stress_uniformity_range = (stress_max - stress_min) / max(
        abs(mean_axial_stress), np.finfo(np.float64).tiny
    )

    with XDMFFile(comm, str(output_root / "fields.xdmf"), "w") as field_file:
        field_file.write_mesh(domain)
        field_file.write_function(displacement, t=0.0)
        field_file.write_function(stress_field, t=0.0)
        field_file.write_function(von_mises_field, t=0.0)

    num_cells = int(comm.allreduce(domain.topology.index_map(domain.topology.dim).size_local))
    local_cell_count = domain.topology.index_map(domain.topology.dim).size_local
    geometry_cell_dofs = domain.geometry.dofmaps[0]
    tetrahedra = _tetrahedron_corner_dofs(geometry_cell_dofs[:local_cell_count])
    vm_cell_values = []
    stress_cell_values = []
    displacement_cell_values = []
    vm_coefficients = von_mises_field.x.array
    vm_dofmap = von_mises_field.function_space.dofmap
    stress_coefficients = stress_field.x.array.reshape((-1, 3, 3))
    stress_dofmap = stress_field.function_space.dofmap
    displacement_coefficients = axial_displacement.x.array
    displacement_dofmap = axial_displacement.function_space.dofmap
    for cell in range(local_cell_count):
        vm_cell_values.append(float(np.mean(vm_coefficients[vm_dofmap.cell_dofs(cell)])))
        stress_cell_values.append(
            float(np.mean(stress_coefficients[stress_dofmap.cell_dofs(cell), 0, 0]))
        )
        displacement_cell_values.append(
            float(np.mean(displacement_coefficients[displacement_dofmap.cell_dofs(cell)]))
        )
    mesh_digest = hashlib.sha256(mesh_path.read_bytes()).hexdigest()
    preview_bytes = build_surface_field_preview(
        domain.geometry.x[:, :3],
        tetrahedra,
        vm_cell_values,
        stress_cell_values,
        displacement_cell_values,
        mesh_digest,
    )
    (output_root / "field-preview.json").write_bytes(preview_bytes)
    return {
        "result": {
            "reaction_force_n": reaction,
            "imposed_force_n": request.load.force_n,
            "measured_axial_displacement_mm": measured_extension,
            **(
                {"measured_midspan_displacement_mm": measured_midspan_displacement}
                if measured_midspan_displacement is not None
                else {}
            ),
            "nominal_stress_mpa": analytical.nominal_stress_mpa,
            "nominal_strain": nominal_strain,
            "volume_average_axial_stress_mpa": mean_axial_stress,
            "peak_von_mises_stress_mpa": peak_von_mises,
            "axial_stress_uniformity_relative_range": stress_uniformity_range,
            "strain_energy_n_mm": strain_energy,
        },
        "mesh_cell_count": num_cells,
        "solver_iterations": int(problem.solver.getIterationNumber()),
        "solver_residual_norm": float(problem.solver.getResidualNorm()),
        "dolfinx_version": dolfinx_version,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> bytes:
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    path.write_bytes(content)
    return content


def _write_result_and_provenance(
    request: IsotropicTensileRequest,
    contract: StageContract,
    output_root: Path,
    solver_output: dict[str, Any],
    started_at: datetime,
    elapsed_seconds: float,
) -> None:
    mesh_bytes = (output_root / "mesh.msh").read_bytes()
    artifact_contents = _collect_solver_artifacts(output_root)

    runtime = solver_output["runtime_versions"]
    solver_metadata = {
        "name": contract.solver_name,
        "version": solver_output["dolfinx_version"],
        "linear_solver": "PETSc KSP preonly with LU factorization",
        "iteration_count": solver_output["solver_iterations"],
        "residual_norm": solver_output["solver_residual_norm"],
        "elapsed_seconds": elapsed_seconds,
        "runtime_versions": runtime,
        "mpi_ranks": contract.mpi_ranks,
        "omp_threads": contract.omp_threads,
        "blas_threads": contract.omp_threads,
        "allocated_cpus": contract.cpu_count,
    }
    mesh_parameters = request.mesh.model_dump(mode="json")
    result = {
        "schema_version": 1,
        "run_id": contract.run_id,
        "stage_id": contract.stage_id,
        "result": solver_output["result"],
        "specimen": request.specimen.model_dump(mode="json"),
        "material": {
            **request.material.model_dump(mode="json"),
            "sha256": model_sha256(request.material),
            "units": {"youngs_modulus_mpa": "MPa"},
        },
        "boundary_conditions": {
            **request.boundary_conditions.model_dump(mode="json"),
            "sha256": model_sha256(request.boundary_conditions),
            "prescribed_displacement_mm": solver_output["result"]["measured_axial_displacement_mm"],
            "transverse_anchor_coordinates_mm": [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, request.specimen.thickness_mm],
            ],
        },
        "mesh": {
            **mesh_parameters,
            "sha256": hashlib.sha256(mesh_bytes).hexdigest(),
            "cell_count": solver_output["mesh_cell_count"],
        },
        "solver_metadata": solver_metadata,
        "fields": {
            "displacement": "fields.xdmf:/displacement_mm",
            "cauchy_stress": "fields.xdmf:/cauchy_stress_mpa",
            "von_mises_stress": "fields.xdmf:/von_mises_stress_mpa",
        },
        "verification_status": "not_assessed",
        "artifacts": {
            name: {
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "media_type": _OUTPUT_MEDIA_TYPES[name],
            }
            for name, content in sorted(artifact_contents.items())
        },
    }
    result_bytes = _write_json(output_root / "result.json", result)
    artifact_contents["result.json"] = result_bytes

    completed_at = datetime.now(timezone.utc)
    dependency_lock = Path("/app/uv.lock").read_bytes()
    dependency_lock_sha256 = hashlib.sha256(dependency_lock).hexdigest()
    if dependency_lock_sha256 != contract.dependency_lock_sha256:
        raise ValueError("stage dependency lock does not match the immutable contract")
    provenance = StageProvenance(
        schema_version=2,
        run_id=contract.run_id,
        stage_id=contract.stage_id,
        operation=contract.operation,
        image_reference=contract.image_reference,
        image_digest=contract.image_digest,
        base_image_reference=contract.base_image_reference,
        dependency_lock_sha256=dependency_lock_sha256,
        contract_sha256=hashlib.sha256(Path("/work/run.json").read_bytes()).hexdigest(),
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
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                media_type=_OUTPUT_MEDIA_TYPES[name],
            )
            for name, content in sorted(artifact_contents.items())
        ),
        git_commit=contract.git_commit,
        git_dirty=contract.git_dirty,
        solver_name=contract.solver_name,
        solver_version=contract.solver_version,
        mesh_sha256=hashlib.sha256(mesh_bytes).hexdigest(),
        mesh_parameters=mesh_parameters,
        material_profile_id=request.material.profile_id,
        material_profile_sha256=model_sha256(request.material),
        boundary_condition_set_id=request.boundary_conditions.set_id,
        boundary_condition_set_sha256=model_sha256(request.boundary_conditions),
        mpi_ranks=contract.mpi_ranks,
        omp_threads=contract.omp_threads,
        cpu_count=contract.cpu_count,
        memory_limit_bytes=contract.memory_limit_bytes,
        started_at=started_at,
        completed_at=completed_at,
        runtime_versions=runtime,
    )
    _write_json(output_root / "provenance.json", provenance.model_dump(mode="json"))


def main() -> int:
    """Load, validate, execute, and persist a single immutable FEM invocation."""
    work_root = Path(os.environ.get("FDM_STAGE_WORK_ROOT", "/work"))
    output_root = work_root / "out"
    started_at = datetime.now(timezone.utc)
    wall_start = time.monotonic()
    try:
        contract = load_stage_contract(work_root)
        request = IsotropicTensileRequest.model_validate_json(
            (work_root / "in" / "request.json").read_bytes()
        )
        validate_stage_request(contract, request)

        import dolfinx
        import gmsh
        import numpy
        import petsc4py
        import ufl
        from mpi4py import MPI

        comm = MPI.COMM_WORLD
        _require_runtime_policy(contract, comm)
        if dolfinx.__version__ != contract.solver_version:
            raise ValueError("DOLFINx version does not match the immutable stage contract")
        solver_output = _solve_tensile_case(request, output_root)
        solver_output["runtime_versions"] = {
            "python": platform.python_version(),
            "pydantic": importlib.metadata.version("pydantic"),
            "dolfinx": dolfinx.__version__,
            "gmsh": gmsh.__version__,
            "numpy": numpy.__version__,
            "petsc4py": petsc4py.__version__,
            "ufl": ufl.__version__,
            "mpi4py": MPI.Get_library_version().strip(),
        }
        if comm.rank == 0:
            elapsed = time.monotonic() - wall_start
            _write_result_and_provenance(
                request,
                contract,
                output_root,
                solver_output,
                started_at,
                elapsed,
            )
            read_stage_outputs(work_root, contract)
        comm.Barrier()
        return 0
    except Exception as error:
        print(f"{STAGE_ID} failed: {error}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
