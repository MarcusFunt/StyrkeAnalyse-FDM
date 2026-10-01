import hashlib

import numpy as np
import pytest
from pydantic import ValidationError

import fdm_strength.fem_models as fem_models
from fdm_strength.fem_models import (
    BoundaryConditionSet,
    GmshMeshSettings,
    IsotropicMaterialProfile,
    IsotropicTensileRequest,
    RectangularTensileSpecimen,
    TensileLoad,
    analytical_tensile_response,
    canonical_json_bytes,
    model_sha256,
)
from fdm_strength.isotropic_fem_stage import (
    EXPECTED_OUTPUTS,
    _collect_solver_artifacts,
    _tetrahedron_corner_dofs,
    validate_stage_request,
)
from fdm_strength.stage_contract import StageContract, StageInput
from fdm_strength.stage_registry import stage_for_operation


def _request() -> IsotropicTensileRequest:
    return IsotropicTensileRequest(
        specimen=RectangularTensileSpecimen(
            specimen_id="SYN-T01",
            length_mm=50.0,
            width_mm=10.0,
            thickness_mm=2.0,
        ),
        material=IsotropicMaterialProfile(
            profile_id="PLA-isotropic-v1",
            youngs_modulus_mpa=2000.0,
            poissons_ratio=0.35,
        ),
        load=TensileLoad(force_n=100.0),
        boundary_conditions=BoundaryConditionSet(set_id="axial-pull-v1"),
        mesh=GmshMeshSettings(max_cell_size_mm=2.5, element_order=2),
    )


def test_rectangular_tensile_reference_matches_closed_form():
    response = analytical_tensile_response(_request())

    assert response.cross_section_area_mm2 == pytest.approx(20.0)
    assert response.nominal_stress_mpa == pytest.approx(5.0)
    assert response.nominal_strain == pytest.approx(0.0025)
    assert response.axial_displacement_mm == pytest.approx(0.125)
    assert response.reaction_force_n == pytest.approx(100.0)


def test_isotropic_lame_parameters_match_youngs_modulus_and_poisson_ratio():
    lame_parameters = getattr(fem_models, "isotropic_lame_parameters", None)
    assert callable(lame_parameters), "fem_models must expose isotropic_lame_parameters"

    lame_lambda, shear_modulus = lame_parameters(2000.0, 0.35)

    assert lame_lambda == pytest.approx(2000.0 * 0.35 / (1.35 * 0.30))
    assert shear_modulus == pytest.approx(2000.0 / (2.0 * 1.35))


def test_isotropic_lame_parameters_reject_unstable_inputs():
    lame_parameters = getattr(fem_models, "isotropic_lame_parameters", None)
    assert callable(lame_parameters), "fem_models must expose isotropic_lame_parameters"

    with pytest.raises(ValueError, match="stable isotropic material"):
        lame_parameters(2000.0, 0.5)
    with pytest.raises(ValueError, match="finite numbers"):
        lame_parameters(float("inf"), 0.3)


def test_fem_request_is_immutable_and_hashes_canonical_json():
    request = _request()
    encoded = canonical_json_bytes(request)

    assert encoded.endswith(b"\n")
    assert model_sha256(request) == hashlib.sha256(encoded).hexdigest()
    with pytest.raises(ValidationError):
        request.load.force_n = 200.0


@pytest.mark.parametrize(
    ("material", "message"),
    [
        (
            {"profile_id": "unstable", "youngs_modulus_mpa": 0.0, "poissons_ratio": 0.3},
            "greater than 0",
        ),
        (
            {"profile_id": "unstable", "youngs_modulus_mpa": 100.0, "poissons_ratio": 0.5},
            "less than 0.5",
        ),
    ],
)
def test_isotropic_material_rejects_nonphysical_parameters(material, message):
    with pytest.raises(ValidationError, match=message):
        IsotropicMaterialProfile(**material)


def test_tensile_request_rejects_invalid_geometry_and_mesh_order():
    with pytest.raises(ValidationError, match="greater than 0"):
        RectangularTensileSpecimen(
            specimen_id="SYN-T01",
            length_mm=0.0,
            width_mm=10.0,
            thickness_mm=2.0,
        )
    with pytest.raises(ValidationError):
        GmshMeshSettings(max_cell_size_mm=2.5, element_order=3)


def test_tensile_request_rejects_geometry_that_is_not_a_tensile_coupon():
    with pytest.raises(ValidationError, match="length must exceed width"):
        RectangularTensileSpecimen(
            specimen_id="SYN-T01",
            length_mm=10.0,
            width_mm=50.0,
            thickness_mm=2.0,
        )


def test_formal_stage_contract_binds_material_boundary_mesh_and_runtime():
    request = _request()
    request_bytes = canonical_json_bytes(request)
    contract = StageContract(
        schema_version=2,
        run_id="8e02d8f8-b1ab-4abc-9fe5-2f65173b6704",
        stage_id="fdm-l2-isotropic",
        operation="fdm-l2-isotropic",
        image_reference="styrkeanalyse-fdm:isotropic-fem",
        image_digest="sha256:" + "a" * 64,
        base_image_reference="ghcr.io/fenics/dolfinx/dolfinx@sha256:" + "b" * 64,
        dependency_lock_sha256="c" * 64,
        git_commit="1" * 40,
        git_dirty=False,
        solver_name="DOLFINx",
        solver_version="0.11.0.post0",
        material_profile_id=request.material.profile_id,
        material_profile_sha256=model_sha256(request.material),
        boundary_condition_set_id=request.boundary_conditions.set_id,
        boundary_condition_set_sha256=model_sha256(request.boundary_conditions),
        mesh_parameters=request.mesh.model_dump(mode="json"),
        mpi_ranks=1,
        omp_threads=1,
        cpu_count=1,
        memory_limit_bytes=1024 * 1024 * 1024,
        inputs=(
            StageInput(
                name="request.json",
                sha256=hashlib.sha256(request_bytes).hexdigest(),
                size_bytes=len(request_bytes),
                media_type="application/vnd.styrkeanalyse.fem-request+json",
            ),
        ),
        parameters={},
        expected_outputs=EXPECTED_OUTPUTS,
        entrypoint=("python", "-m", "fdm_strength.isotropic_fem_stage"),
    )

    validate_stage_request(contract, request)

    with pytest.raises(ValueError, match="DOLFINx solver version"):
        validate_stage_request(
            contract.model_copy(update={"solver_version": "0.11.0"}),
            request,
        )


def test_formal_stage_contract_rejects_unmatched_material_or_boundary_hash():
    request = _request()
    request_bytes = canonical_json_bytes(request)
    contract_data = {
        "schema_version": 2,
        "run_id": "8e02d8f8-b1ab-4abc-9fe5-2f65173b6704",
        "stage_id": "fdm-l2-isotropic",
        "operation": "fdm-l2-isotropic",
        "image_reference": "styrkeanalyse-fdm:isotropic-fem",
        "image_digest": "sha256:" + "a" * 64,
        "base_image_reference": "ghcr.io/fenics/dolfinx/dolfinx@sha256:" + "b" * 64,
        "dependency_lock_sha256": "c" * 64,
        "git_commit": "1" * 40,
        "git_dirty": False,
        "solver_name": "DOLFINx",
        "solver_version": "0.11.0.post0",
        "material_profile_id": request.material.profile_id,
        "material_profile_sha256": model_sha256(request.material),
        "boundary_condition_set_id": request.boundary_conditions.set_id,
        "boundary_condition_set_sha256": "0" * 64,
        "mesh_parameters": request.mesh.model_dump(mode="json"),
        "mpi_ranks": 1,
        "omp_threads": 1,
        "cpu_count": 1,
        "memory_limit_bytes": 1024 * 1024 * 1024,
        "inputs": (
            {
                "name": "request.json",
                "sha256": hashlib.sha256(request_bytes).hexdigest(),
                "size_bytes": len(request_bytes),
                "media_type": "application/vnd.styrkeanalyse.fem-request+json",
            },
        ),
        "parameters": {},
        "expected_outputs": EXPECTED_OUTPUTS,
        "entrypoint": ("python", "-m", "fdm_strength.isotropic_fem_stage"),
    }
    contract = StageContract.model_validate(contract_data)

    with pytest.raises(ValueError, match="boundary-condition identity"):
        validate_stage_request(contract, request)


def test_solver_artifact_collection_does_not_require_result_written_later(tmp_path):
    (tmp_path / "mesh.msh").write_bytes(b"mesh")
    (tmp_path / "fields.xdmf").write_bytes(b"xdmf")
    (tmp_path / "fields.h5").write_bytes(b"hdf5")
    (tmp_path / "field-preview.json").write_bytes(b"preview")

    artifacts = _collect_solver_artifacts(tmp_path)

    assert artifacts == {
        "mesh.msh": b"mesh",
        "fields.xdmf": b"xdmf",
        "fields.h5": b"hdf5",
        "field-preview.json": b"preview",
    }


def test_tetrahedron_corner_dofs_uses_p1_and_p2_numpy_geometry_maps():
    p1_geometry = np.asarray([[2, 5, 7, 11]], dtype=np.int32)
    p2_geometry = np.asarray([[2, 5, 7, 11, 13, 17, 19, 23, 29, 31]], dtype=np.int32)

    assert _tetrahedron_corner_dofs(p1_geometry).tolist() == [[2, 5, 7, 11]]
    assert _tetrahedron_corner_dofs(p2_geometry).tolist() == [[2, 5, 7, 11]]


def test_tetrahedron_corner_dofs_rejects_non_tetrahedral_geometry_maps():
    with pytest.raises(ValueError, match="at least four geometry nodes per cell"):
        _tetrahedron_corner_dofs(np.asarray([[0, 1, 2]], dtype=np.int32))


def test_isotropic_fem_uses_a_server_registered_stage_definition():
    stage = stage_for_operation("fdm-l2-isotropic")

    assert stage.stage_id == "fdm-l2-isotropic"
    assert stage.image_reference == "styrkeanalyse-fdm:isotropic-fem"
    assert stage.command == ("python", "-m", "fdm_strength.isotropic_fem_stage")
    assert stage.expected_outputs == (
        "result.json",
        "mesh.msh",
        "fields.xdmf",
        "fields.h5",
        "field-preview.json",
        "provenance.json",
    )
