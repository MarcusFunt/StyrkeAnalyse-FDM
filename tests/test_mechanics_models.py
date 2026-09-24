from __future__ import annotations

import math

import numpy as np
import pytest

from fdm_strength.analytical import (
    chord_modulus_mpa,
    engineering_strain,
    tensile_stress_mpa,
    three_point_bend_modulus_mpa,
    three_point_bend_strain,
    three_point_bend_stress_mpa,
)
from fdm_strength.clt import Lamina, laminate_abd, laminate_moduli_mpa
from fdm_strength.fracture import (
    BilinearCohesiveLaw,
    j_to_k_mpa_sqrt_mm,
)
from fdm_strength.orthotropic import (
    TransverselyIsotropic,
    maximum_stress_index,
    plane_stress_tsai_wu_index,
)
from fdm_strength.verification import (
    M4_REQUIRED_GATES,
    GateEvidence,
    evaluate_m4_gate,
)


def _general_orthotropic_material():
    import fdm_strength.orthotropic as orthotropic

    return orthotropic.OrthotropicMaterial(
        e1_mpa=10_000,
        e2_mpa=5_000,
        e3_mpa=2_000,
        nu12=0.25,
        nu13=0.3,
        nu23=0.28,
        g12_mpa=2_200,
        g13_mpa=1_300,
        g23_mpa=700,
    )


def test_tensile_reductions_and_documented_compliance_correction() -> None:
    assert tensile_stress_mpa(1000, 10) == pytest.approx(100)
    assert engineering_strain(0.2, 0, 100, 50, machine_compliance_mm_per_n=0.0005) == pytest.approx(
        0.003
    )
    assert chord_modulus_mpa([0, 0.001, 0.003], [0, 2, 6]) == pytest.approx(2000)


def test_tensile_reduction_rejects_invalid_dimensions_and_uncovered_window() -> None:
    with pytest.raises(ValueError, match="area_mm2"):
        tensile_stress_mpa(100, 0)
    with pytest.raises(ValueError, match="cover"):
        chord_modulus_mpa([0, 0.001], [0, 2])


def test_three_point_bend_reference_formulas() -> None:
    assert three_point_bend_stress_mpa(100, 80, 10, 5) == pytest.approx(48)
    assert three_point_bend_strain(2, 80, 5) == pytest.approx(0.009375)
    assert three_point_bend_modulus_mpa(10, 80, 10, 5) == pytest.approx(1024)


def test_clt_unidirectional_laminate_recovers_lamina_and_symmetric_cross_ply_abd() -> None:
    lamina = Lamina(e1_mpa=10_000, e2_mpa=5_000, nu12=0.25, g12_mpa=2_000)
    unidirectional = [lamina.ply(0, 2)]
    moduli = laminate_moduli_mpa(unidirectional)
    assert moduli["ex_mpa"] == pytest.approx(10_000)
    assert moduli["ey_mpa"] == pytest.approx(5_000)
    assert moduli["gxy_mpa"] == pytest.approx(2_000)

    abd = laminate_abd(
        [
            lamina.ply(0, 0.5),
            lamina.ply(90, 0.5),
            lamina.ply(90, 0.5),
            lamina.ply(0, 0.5),
        ]
    )
    q11 = 10_000 / (1 - 0.25 * 0.125)
    q22 = 5_000 / (1 - 0.25 * 0.125)
    q12 = 0.25 * 5_000 / (1 - 0.25 * 0.125)
    assert abd["A"][0][0] == pytest.approx(q11 + q22)
    assert abd["A"][0][1] == pytest.approx(2 * q12)
    assert [value for row in abd["B"] for value in row] == pytest.approx([0] * 9, abs=1e-12)
    assert abd["D"][0][0] == pytest.approx((7 * q11 + q22) / 12)


def test_transverse_isotropic_stiffness_is_symmetric_positive_and_reduces() -> None:
    material = TransverselyIsotropic(
        e1_mpa=10_000,
        e2_mpa=5_000,
        nu12=0.25,
        nu23=0.3,
        g12_mpa=2_000,
    )
    stiffness = material.stiffness_mpa()
    assert [value for row in stiffness for value in row] == pytest.approx(
        [value for row in zip(*stiffness) for value in row]
    )
    assert all(stiffness[i][i] > 0 for i in range(6))
    assert material.constants()["e3_mpa"] == 5_000
    assert material.constants()["g23_mpa"] == pytest.approx(5_000 / (2 * 1.3))
    with pytest.raises(ValueError, match="stable elastic"):
        TransverselyIsotropic(10_000, 5_000, 2, 0.3, 2_000).stiffness_mpa()


def test_general_orthotropy_serializes_full_stiffness_and_compliance_matrices():
    material = _general_orthotropic_material()
    artifact = material.to_dict()
    stiffness = np.asarray(artifact["stiffness_mpa"])
    compliance = np.asarray(artifact["compliance_per_mpa"])

    assert stiffness.shape == (6, 6)
    assert compliance.shape == (6, 6)
    assert stiffness @ compliance == pytest.approx(np.eye(6), abs=1e-10)
    assert artifact["constants"]["e3_mpa"] == 2_000


def test_general_orthotropy_recovers_isotropic_limit():
    import fdm_strength.orthotropic as orthotropic

    young = 3_000.0
    poisson = 0.3
    shear = young / (2 * (1 + poisson))
    lame = young * poisson / ((1 + poisson) * (1 - 2 * poisson))
    material = orthotropic.OrthotropicMaterial(
        e1_mpa=young,
        e2_mpa=young,
        e3_mpa=young,
        nu12=poisson,
        nu13=poisson,
        nu23=poisson,
        g12_mpa=shear,
        g13_mpa=shear,
        g23_mpa=shear,
    )
    expected = np.zeros((6, 6))
    expected[:3, :3] = lame
    np.fill_diagonal(expected[:3, :3], lame + 2 * shear)
    np.fill_diagonal(expected[3:, 3:], shear)

    assert np.asarray(material.stiffness_mpa()) == pytest.approx(expected)


def test_transverse_isotropy_is_an_explicit_constrained_specialization():
    material = TransverselyIsotropic(
        e1_mpa=10_000,
        e2_mpa=5_000,
        nu12=0.25,
        nu23=0.3,
        g12_mpa=2_000,
    ).to_orthotropic()

    assert material.e2_mpa == material.e3_mpa == 5_000
    assert material.nu12 == material.nu13 == 0.25
    assert material.g12_mpa == material.g13_mpa == 2_000
    assert material.g23_mpa == pytest.approx(5_000 / (2 * 1.3))


def test_general_orthotropy_rotates_under_a_quarter_turn_axis_permutation():
    material = _general_orthotropic_material()
    rotated = np.asarray(
        material.rotated_stiffness_mpa(
            ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
        )
    )
    swapped = _general_orthotropic_material().__class__(
        e1_mpa=5_000,
        e2_mpa=10_000,
        e3_mpa=2_000,
        nu12=0.25 * 5_000 / 10_000,
        nu13=0.28,
        nu23=0.3,
        g12_mpa=2_200,
        g13_mpa=700,
        g23_mpa=1_300,
    )

    assert rotated == pytest.approx(np.asarray(swapped.stiffness_mpa()), abs=1e-9)


def test_general_orthotropy_rejects_unstable_compliance():
    import fdm_strength.orthotropic as orthotropic

    material = orthotropic.OrthotropicMaterial(
        e1_mpa=1_000,
        e2_mpa=1_000,
        e3_mpa=1_000,
        nu12=0.9,
        nu13=0.9,
        nu23=0.9,
        g12_mpa=100,
        g13_mpa=100,
        g23_mpa=100,
    )
    with pytest.raises(ValueError, match="stable"):
        material.stiffness_mpa()


def test_maximum_stress_and_tsai_wu_indices_name_mode_and_assumption() -> None:
    strengths = {"xt_mpa": 100, "xc_mpa": 80, "yt_mpa": 50, "yc_mpa": 45, "s12_mpa": 30}
    maximum = maximum_stress_index((50, 0, 0, 0, 0, 0), strengths)
    assert maximum["index"] == pytest.approx(0.5)
    assert maximum["critical_mode"] == "sigma1_tension"
    compression = maximum_stress_index((-40, 0, 0, 0, 0, 0), strengths)
    assert compression["index"] == pytest.approx(0.5)
    assert compression["critical_mode"] == "sigma1_compression"
    tsai_wu = plane_stress_tsai_wu_index((100, 0, 0), strengths, interaction_factor=0)
    assert tsai_wu["index"] == pytest.approx(1)
    assert "interaction_factor=0" in tsai_wu["assumption"]


def test_fracture_conversion_and_bilinear_cohesive_law_energy() -> None:
    assert j_to_k_mpa_sqrt_mm(10, 3_000, 0.3, plane="stress") == pytest.approx(math.sqrt(30_000))
    law = BilinearCohesiveLaw(
        peak_traction_mpa=30, fracture_energy_n_per_mm=0.09, initial_stiffness_mpa_per_mm=10_000
    )
    assert law.final_separation_mm == pytest.approx(0.006)
    assert law.traction_mpa(0.003) == pytest.approx(30)
    assert law.traction_mpa(0.0045) == pytest.approx(15)
    assert law.traction_mpa(0.006) == 0
    assert law.fracture_energy_n_per_mm == pytest.approx(0.09)
    assert law.envelope_area_n_per_mm == pytest.approx(0.09)


def test_m4_verification_gate_fails_closed_for_missing_evidence_and_pins() -> None:
    model_digest = "sha256:" + "d" * 64
    missing = evaluate_m4_gate([], {}, model_digest=model_digest)
    assert not missing.comparison_allowed
    assert set(missing.missing_gates) == set(M4_REQUIRED_GATES)

    pins = {"dolfinx": "sha256:" + "a" * 64, "calculix": "sha256:" + "b" * 64}
    evidence = [
        GateEvidence(
            name=name,
            passed=True,
            model_digest=model_digest,
            artifact_sha256="c" * 64,
            solver_image_digests=pins,
            metrics=_passing_metrics(name),
            recorded_at="2026-09-24T10:00:00Z",
        )
        for name in M4_REQUIRED_GATES
    ]
    allowed = evaluate_m4_gate(evidence, pins, model_digest=model_digest)
    assert allowed.comparison_allowed

    stale = evaluate_m4_gate(evidence, pins, model_digest="sha256:" + "e" * 64)
    assert not stale.comparison_allowed
    assert stale.blockers

    out_of_tolerance = [
        GateEvidence(
            name=evidence[0].name,
            passed=True,
            model_digest=model_digest,
            artifact_sha256="c" * 64,
            solver_image_digests=pins,
            metrics={"p1_l2_order": 1.2, "p2_l2_order": 2.8},
            recorded_at="2026-09-24T10:00:00Z",
        ),
        *evidence[1:],
    ]
    rejected = evaluate_m4_gate(out_of_tolerance, pins, model_digest=model_digest)
    assert not rejected.comparison_allowed
    assert "manufactured_solution" in rejected.failed_gates


def _passing_metrics(gate: str) -> dict[str, float]:
    return {
        "manufactured_solution": {"p1_l2_order": 2.0, "p2_l2_order": 3.0},
        "uniform_stress_patch": {"relative_error": 1e-13},
        "analytical_agreement": {
            "tensile_relative_error": 0.0005,
            "bend_relative_error": 0.005,
            "clt_relative_error": 0.005,
        },
        "calculix_crosscheck": {"relative_displacement_error": 0.004},
    }[gate]
