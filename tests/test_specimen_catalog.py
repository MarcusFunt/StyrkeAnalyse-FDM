import hashlib
import math

import pytest

from fdm_strength.fem_models import (
    D638BoundaryConditionSet,
    D638IsotropicTensileRequest,
    D638TensileSpecimen,
    GmshMeshSettings,
    IsotropicMaterialProfile,
    TensileLoad,
    analytical_tensile_response,
    canonical_json_bytes,
    parse_isotropic_tensile_request,
)
from fdm_strength.specimen_catalog import (
    D638_SPECIMENS,
    REFERENCE_STANDARD,
    d638_definition,
    d638_geometry_metadata,
    d638_outline_segments,
)


@pytest.mark.parametrize(
    ("specimen_type", "expected"),
    [
        ("I", (165.0, 19.0, 13.0, 57.0, 50.0, 115.0, 76.0, None)),
        ("IV", (115.0, 19.0, 6.0, 33.0, 25.0, 65.0, 14.0, 25.0)),
        ("V", (63.5, 9.53, 3.18, 9.53, 7.62, 25.4, 12.7, None)),
    ],
)
def test_checked_astm_d638_catalog_matches_reference_package(specimen_type, expected):
    definition = d638_definition(specimen_type)

    assert (
        definition.overall_length_mm,
        definition.overall_width_mm,
        definition.gauge_width_mm,
        definition.narrow_length_mm,
        definition.gauge_length_mm,
        definition.grip_separation_mm,
        definition.inner_radius_mm,
        definition.outer_radius_mm,
    ) == expected
    assert definition.nominal_thickness_mm == 3.2


@pytest.mark.parametrize("specimen_type", ["I", "IV", "V"])
def test_astm_d638_outline_has_exact_package_envelope(specimen_type):
    definition = D638_SPECIMENS[specimen_type]
    segments = d638_outline_segments(specimen_type)
    boundary_points = [point for segment in segments for point in segment[1:3]]

    xs = [point[0] for point in boundary_points]
    ys = [point[1] for point in boundary_points]
    assert max(xs) - min(xs) == pytest.approx(definition.overall_length_mm)
    assert max(ys) - min(ys) == pytest.approx(definition.overall_width_mm)


@pytest.mark.parametrize("specimen_type", ["I", "IV", "V"])
def test_astm_d638_arc_centres_preserve_declared_radii(specimen_type):
    definition = D638_SPECIMENS[specimen_type]
    radii = []
    for kind, start, end, center in d638_outline_segments(specimen_type):
        if kind != "arc":
            continue
        assert center is not None
        start_radius = math.dist(start, center)
        end_radius = math.dist(end, center)
        assert start_radius == pytest.approx(end_radius)
        radii.append(start_radius)

    assert any(radius == pytest.approx(definition.inner_radius_mm) for radius in radii)
    if definition.outer_radius_mm is not None:
        assert any(radius == pytest.approx(definition.outer_radius_mm) for radius in radii)


def test_type_iv_grip_line_remains_inside_shoulder_transition():
    definition = d638_definition("IV")

    assert definition.jaw_edge_relative_to_flat_start_mm == pytest.approx(-5.558061137310098)
    assert definition.flat_tab_length_per_end_mm == pytest.approx(19.441938862689902)


def test_d638_request_round_trips_canonically_and_uses_gauge_reference_response():
    request = D638IsotropicTensileRequest(
        specimen=D638TensileSpecimen(
            specimen_id="ASTM-IV-01",
            specimen_type="IV",
            thickness_mm=3.2,
        ),
        material=IsotropicMaterialProfile(
            profile_id="PLA-isotropic-v1",
            youngs_modulus_mpa=2000.0,
            poissons_ratio=0.35,
        ),
        load=TensileLoad(force_n=100.0),
        boundary_conditions=D638BoundaryConditionSet(set_id="astm-d638-end-traction-v1"),
        mesh=GmshMeshSettings(max_cell_size_mm=2.5, element_order=2),
    )
    encoded = canonical_json_bytes(request)
    parsed = parse_isotropic_tensile_request(encoded)
    response = analytical_tensile_response(parsed)

    assert parsed == request
    assert hashlib.sha256(encoded).hexdigest()
    assert request.specimen.standard_revision == REFERENCE_STANDARD
    assert response.cross_section_area_mm2 == pytest.approx(6.0 * 3.2)
    assert response.nominal_stress_mpa == pytest.approx(100.0 / (6.0 * 3.2))
    assert response.axial_displacement_mm == pytest.approx(
        response.nominal_strain * d638_definition("IV").gauge_length_mm
    )
    assert d638_geometry_metadata("IV", 3.2)["reference_step_sha256"] == (
        "afd5da5f53fca22f154ba0fde86a67959b293419ba85cddfc675d1cbd8797289"
    )
