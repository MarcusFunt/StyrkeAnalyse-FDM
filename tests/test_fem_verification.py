"""Numerical utilities used by solver-generated FEM verification evidence."""

from __future__ import annotations

import meshio
import pytest

import fdm_strength.isotropic_fem_verification as solver_verification
import fdm_strength.verification as verification
from fdm_strength.fem_models import (
    BoundaryConditionSet,
    GmshMeshSettings,
    IsotropicMaterialProfile,
    IsotropicTensileRequest,
    RectangularTensileSpecimen,
    TensileLoad,
)


def _verification_function(name: str):
    function = getattr(verification, name, None)
    assert callable(function), f"verification must expose {name}"
    return function


def test_observed_l2_order_uses_all_refinement_levels() -> None:
    observed_order = _verification_function("observed_l2_convergence_order")

    p1_order = observed_order((0.8, 0.4, 0.2, 0.1), (0.64, 0.16, 0.04, 0.01))
    p2_order = observed_order((0.8, 0.4, 0.2, 0.1), (0.512, 0.064, 0.008, 0.001))

    assert p1_order == pytest.approx(2.0)
    assert p2_order == pytest.approx(3.0)


def test_observed_l2_order_rejects_non_refined_or_invalid_samples() -> None:
    observed_order = _verification_function("observed_l2_convergence_order")

    with pytest.raises(ValueError, match="strictly decreasing"):
        observed_order((0.8, 0.4, 0.5), (0.64, 0.16, 0.09))
    with pytest.raises(ValueError, match="positive finite"):
        observed_order((0.8, 0.4), (0.64, 0.0))


def test_relative_error_is_scale_independent_and_rejects_zero_reference() -> None:
    relative_error = _verification_function("relative_error")

    assert relative_error(100.1, 100.0) == pytest.approx(0.001)
    assert relative_error(-2.0, 2.0) == pytest.approx(2.0)
    with pytest.raises(ValueError, match="reference must be non-zero"):
        relative_error(1.0, 0.0)


def test_calculix_deck_preserves_mesh_material_and_effective_boundary_conditions() -> None:
    build_deck = getattr(solver_verification, "calculix_input_text", None)
    assert callable(build_deck), "verification must expose calculix_input_text"
    mesh = meshio.Mesh(
        points=[
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (2.0, 1.0, 1.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
        ],
        cells=[("tetra", [(0, 1, 2, 3), (1, 2, 3, 4), (0, 5, 2, 3), (5, 6, 2, 3)])],
    )
    request = IsotropicTensileRequest(
        specimen=RectangularTensileSpecimen(
            specimen_id="CALCIX-DECK-TEST",
            length_mm=2.0,
            width_mm=1.0,
            thickness_mm=1.0,
        ),
        material=IsotropicMaterialProfile(
            profile_id="material-v1", youngs_modulus_mpa=2000.0, poissons_ratio=0.3
        ),
        load=TensileLoad(force_n=100.0),
        boundary_conditions=BoundaryConditionSet(set_id="boundary-v1"),
        mesh=GmshMeshSettings(max_cell_size_mm=1.0, element_order=1, optimize=False),
    )

    deck = build_deck(mesh, request)

    assert "*ELEMENT, TYPE=C3D4, ELSET=SPECIMEN" in deck
    assert "1, 1, 2, 3, 4" in deck
    assert "*NSET, NSET=FIXED_X\n1, 3, 4" in deck
    assert "*NSET, NSET=LOADED_X\n2, 5" in deck
    assert "*NSET, NSET=ORIGIN\n1" in deck
    assert "*NSET, NSET=TORSION_ANCHOR\n4" in deck
    assert "*NSET, NSET=GAUGE_MID\n6, 7" in deck
    assert "*ELASTIC\n2000.0, 0.3" in deck
    assert "FIXED_X, 1, 1, 0.0" in deck
    assert "LOADED_X, 1, 1, 0.1" in deck
    assert "ORIGIN, 2, 2, 0.0" in deck
    assert "ORIGIN, 3, 3, 0.0" in deck
    assert "TORSION_ANCHOR, 2, 2, 0.0" in deck
    assert "*NODE PRINT, NSET=LOADED_X, TOTALS=YES\nU, RF" in deck
    assert "*NODE PRINT, NSET=GAUGE_MID\nU" in deck


def test_calculix_dat_parser_reads_midspan_displacement_and_total_reaction() -> None:
    parse_dat = getattr(solver_verification, "parse_calculix_dat", None)
    assert callable(parse_dat), "verification must expose parse_calculix_dat"
    dat_text = """
 displacements (vx,vy,vz) for set GAUGE_MID and time  0.1000000E+01

        17  5.000000E-02 -1.000000E-15  0.000000E+00
        18  4.999000E-02  0.000000E+00  1.000000E-15

 forces (fx,fy,fz) for set LOADED_X and time  0.1000000E+01

        17  4.000000E+00  0.000000E+00  0.000000E+00

 total force (fx,fy,fz) for set LOADED_X and time  0.1000000E+01

        1.000000E+02  0.000000E+00  0.000000E+00
"""

    result = parse_dat(dat_text)

    assert result["midspan_axial_displacement_mm"] == pytest.approx(0.049995)
    assert result["loaded_face_reaction_force_n"] == pytest.approx(100.0)
