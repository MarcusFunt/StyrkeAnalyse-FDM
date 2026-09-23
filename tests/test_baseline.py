import pytest

from fdm_strength.baseline import nominal_tensile_stress_mpa


def test_nominal_tensile_stress_uses_newton_per_square_millimetre():
    assert nominal_tensile_stress_mpa(850.0, 40.0) == 21.25


@pytest.mark.parametrize("area_mm2", [0.0, -1.0])
def test_nominal_tensile_stress_rejects_non_positive_area(area_mm2):
    with pytest.raises(ValueError, match="area_mm2 must be positive"):
        nominal_tensile_stress_mpa(100.0, area_mm2)
