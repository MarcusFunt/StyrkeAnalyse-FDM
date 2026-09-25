import pytest

from fdm_strength.replicates import aggregate_modulus, reduce_tensile_modulus


def points(strains, stresses, forces=None, gauge_length_mm=50, compliance_mm_per_n=0):
    forces = forces or [0 for _ in strains]
    return [
        {
            "row_number": index + 1,
            "force_n": force,
            "displacement_mm": strain * gauge_length_mm,
            "extension_mm": strain * gauge_length_mm + force * compliance_mm_per_n,
            "strain": strain + force * compliance_mm_per_n / gauge_length_mm,
            "stress_mpa": stress,
        }
        for index, (strain, stress, force) in enumerate(zip(strains, stresses, forces, strict=True))
    ]


def reduce(specimen_id, modulus_mpa=1000):
    strains = [0, 0.001, 0.003]
    return reduce_tensile_modulus(
        specimen_id,
        points(strains, [modulus_mpa * strain for strain in strains]),
        gauge_length_mm=50,
        sensor_source="extensometer",
        compliance_correction={"method": "not_required"},
    )


def test_chord_modulus_interpolates_the_project_strain_window():
    result = reduce_tensile_modulus(
        "S01",
        points([0, 0.001, 0.003], [0, 2, 6]),
        gauge_length_mm=50,
        sensor_source="extensometer",
        compliance_correction={"method": "not_required"},
    )

    assert result.status == "eligible"
    assert result.modulus_mpa == pytest.approx(2000)
    assert result.strain_interval == (0.0005, 0.0025)


def test_crosshead_modulus_uses_documented_machine_compliance_correction():
    strains = [0, 0.001, 0.003]
    force = [0, 10, 30]
    compliance = 0.02
    raw_extension = [
        strain * 50 + load * compliance for strain, load in zip(strains, force, strict=True)
    ]
    raw_points = [
        {
            "row_number": index + 1,
            "force_n": force[index],
            "displacement_mm": raw_extension[index],
            "extension_mm": raw_extension[index],
            "strain": raw_extension[index] / 50,
            "stress_mpa": 2000 * strains[index],
        }
        for index in range(len(strains))
    ]
    result = reduce_tensile_modulus(
        "S02",
        raw_points,
        gauge_length_mm=50,
        sensor_source="crosshead",
        compliance_correction={
            "method": "machine_compliance",
            "compliance_mm_per_n": compliance,
            "calibration_source": "rig compliance calibration 2026-09-01",
        },
    )

    assert result.status == "eligible"
    assert result.modulus_mpa == pytest.approx(2000)


@pytest.mark.parametrize(
    ("sensor", "correction", "expected_reason"),
    [
        ("unknown", {"method": "unknown"}, "sensor source"),
        ("crosshead", {"method": "unknown"}, "compliance correction"),
        ("crosshead", {"method": "not_required"}, "compliance correction"),
    ],
)
def test_uncorrected_or_unknown_sensor_is_not_validation_eligible(
    sensor, correction, expected_reason
):
    result = reduce_tensile_modulus(
        "S03",
        points([0, 0.001, 0.003], [0, 2, 6]),
        gauge_length_mm=50,
        sensor_source=sensor,
        compliance_correction=correction,
    )

    assert result.status == "ineligible"
    assert result.modulus_mpa is None
    assert expected_reason in result.reason.lower()


def test_modulus_is_ineligible_when_the_test_does_not_cover_the_full_window():
    result = reduce_tensile_modulus(
        "S04",
        points([0, 0.001], [0, 2]),
        gauge_length_mm=50,
        sensor_source="extensometer",
        compliance_correction={"method": "not_required"},
    )

    assert result.status == "ineligible"
    assert "strain window" in result.reason.lower()


def test_modulus_is_ineligible_for_non_monotonic_corrected_strain():
    result = reduce_tensile_modulus(
        "S05",
        points([0, 0.001, 0.0008, 0.003], [0, 2, 1.6, 6]),
        gauge_length_mm=50,
        sensor_source="extensometer",
        compliance_correction={"method": "not_required"},
    )

    assert result.status == "ineligible"
    assert "non-monotonic" in result.reason.lower()


def test_campaign_reduction_uses_specimens_sample_standard_deviation_and_cv():
    specimens = [
        reduce("S01", 1000),
        reduce("S02", 1100),
        reduce("S03", 900),
        reduce("S04", 1000),
        reduce("S05", 1000),
    ]
    campaign = aggregate_modulus(specimens)

    assert campaign.n_valid == 5
    assert campaign.n_total == 5
    assert campaign.mean_mpa == pytest.approx(1000)
    assert campaign.sample_standard_deviation_mpa == pytest.approx(70.71067811865476)
    assert campaign.coefficient_of_variation_percent == pytest.approx(7.071067811865476)
    assert campaign.replicate_ready is True
    assert campaign.ready_for_validation is True  # compatibility alias


def test_campaign_gate_requires_five_valid_specimens_and_cv_at_most_fifteen_percent():
    too_few = aggregate_modulus([reduce("S01"), reduce("S02"), reduce("S03"), reduce("S04")])
    high_cv = aggregate_modulus(
        [
            reduce(f"S{index}", value)
            for index, value in enumerate([500, 800, 1000, 1200, 1500], start=1)
        ]
    )

    assert too_few.replicate_ready is False
    assert too_few.reason and "5" in too_few.reason
    assert high_cv.n_valid == 5
    assert high_cv.replicate_ready is False
    assert high_cv.coefficient_of_variation_percent > 15


def test_campaign_reports_undefined_statistics_without_enough_valid_specimens():
    invalid = reduce_tensile_modulus(
        "S00",
        points([0, 0.001, 0.003], [0, 2, 6]),
        gauge_length_mm=50,
        sensor_source="unknown",
        compliance_correction={"method": "unknown"},
    )
    campaign = aggregate_modulus([invalid])

    assert campaign.n_valid == 0
    assert campaign.mean_mpa is None
    assert campaign.sample_standard_deviation_mpa is None
    assert campaign.coefficient_of_variation_percent is None
    assert campaign.replicate_ready is False
