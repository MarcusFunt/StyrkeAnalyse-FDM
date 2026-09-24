"""Hand-calculable mechanics references in mm, N, and MPa."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite


def _positive(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite and positive")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite and positive") from error
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def tensile_stress_mpa(force_n: float, area_mm2: float) -> float:
    """Engineering tensile stress F/A; N/mm² is MPa."""
    if isinstance(force_n, bool) or not isinstance(force_n, (int, float)) or not isfinite(force_n):
        raise ValueError("force_n must be finite")
    return float(force_n) / _positive(area_mm2, "area_mm2")


def engineering_strain(
    displacement_mm: float,
    initial_displacement_mm: float,
    force_change_n: float,
    gauge_length_mm: float,
    *,
    machine_compliance_mm_per_n: float = 0.0,
) -> float:
    """Engineering strain with optional frame-extension subtraction.

    Compliance correction is C_machine × ΔF. Use only when the compliance has
    been measured for the relevant machine/grip configuration.
    """
    length = _positive(gauge_length_mm, "gauge_length_mm")
    values = (displacement_mm, initial_displacement_mm, force_change_n)
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in values
    ):
        raise ValueError("displacement and force values must be finite")
    compliance = machine_compliance_mm_per_n
    if (
        isinstance(compliance, bool)
        or not isinstance(compliance, (int, float))
        or not isfinite(compliance)
    ):
        raise ValueError("machine compliance must be finite and non-negative")
    if compliance < 0:
        raise ValueError("machine compliance must be finite and non-negative")
    extension = float(displacement_mm) - float(initial_displacement_mm)
    extension -= float(force_change_n) * float(compliance)
    strain = extension / length
    if not isfinite(strain):
        raise ValueError("engineering strain is outside the finite measurement range")
    return strain


def chord_modulus_mpa(strains: Sequence[float], stresses_mpa: Sequence[float]) -> float:
    """Chord modulus between engineering strain 0.0005 and 0.0025.

    Values at both bounds are linearly interpolated. Acquisition data must be
    strictly increasing in strain; it is never sorted to conceal reversals.
    """
    if len(strains) != len(stresses_mpa) or len(strains) < 2:
        raise ValueError("strain and stress sequences must have equal length >= 2")
    all_values = [*strains, *stresses_mpa]
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) for value in all_values
    ):
        raise ValueError("strain and stress values must be numeric")
    try:
        strain_values = [float(value) for value in strains]
        stress_values = [float(value) for value in stresses_mpa]
    except OverflowError as error:
        raise ValueError("strain and stress values must be finite") from error
    if any(not isfinite(value) for value in strain_values + stress_values):
        raise ValueError("strain and stress values must be finite")
    if any(right <= left for left, right in zip(strain_values, strain_values[1:])):
        raise ValueError("strain values must be strictly increasing")

    def at(target: float) -> float:
        if target < strain_values[0] or target > strain_values[-1]:
            raise ValueError("measurements must cover the full 0.0005–0.0025 strain window")
        for index in range(1, len(strain_values)):
            if strain_values[index] >= target:
                fraction = (target - strain_values[index - 1]) / (
                    strain_values[index] - strain_values[index - 1]
                )
                return stress_values[index - 1] + fraction * (
                    stress_values[index] - stress_values[index - 1]
                )
        return stress_values[-1]

    modulus = (at(0.0025) - at(0.0005)) / 0.002
    if not isfinite(modulus) or modulus <= 0:
        raise ValueError("chord modulus must be finite and positive")
    return modulus


def three_point_bend_stress_mpa(
    force_n: float, span_mm: float, width_mm: float, depth_mm: float
) -> float:
    """Maximum nominal flexural stress for a simply supported centre-loaded beam."""
    force = _positive(force_n, "force_n")
    span = _positive(span_mm, "span_mm")
    width = _positive(width_mm, "width_mm")
    depth = _positive(depth_mm, "depth_mm")
    stress = 3 * force * span / (2 * width * depth**2)
    if not isfinite(stress):
        raise ValueError("flexural stress is outside the finite measurement range")
    return stress


def three_point_bend_strain(deflection_mm: float, span_mm: float, depth_mm: float) -> float:
    """Nominal outer-fibre strain for small-deflection three-point bending."""
    deflection = _positive(deflection_mm, "deflection_mm")
    span = _positive(span_mm, "span_mm")
    depth = _positive(depth_mm, "depth_mm")
    strain = 6 * deflection * depth / span**2
    if not isfinite(strain):
        raise ValueError("flexural strain is outside the finite measurement range")
    return strain


def three_point_bend_modulus_mpa(
    force_deflection_slope_n_per_mm: float,
    span_mm: float,
    width_mm: float,
    depth_mm: float,
    *,
    shear_modulus_mpa: float | None = None,
    shear_correction_factor: float = 5 / 6,
) -> float:
    """Flexural modulus from beam slope, optionally correcting Timoshenko shear.

    The uncorrected Euler–Bernoulli expression is the roadmap baseline. When a
    measured shear modulus is supplied, the centre-deflection shear compliance
    L/(4 κ G b h) is subtracted from the total compliance before solving for E.
    """
    slope = _positive(force_deflection_slope_n_per_mm, "force_deflection_slope_n_per_mm")
    span = _positive(span_mm, "span_mm")
    width = _positive(width_mm, "width_mm")
    depth = _positive(depth_mm, "depth_mm")
    total_compliance = 1 / slope
    bending_compliance = total_compliance
    if shear_modulus_mpa is not None:
        shear = _positive(shear_modulus_mpa, "shear_modulus_mpa")
        kappa = _positive(shear_correction_factor, "shear_correction_factor")
        bending_compliance -= span / (4 * kappa * shear * width * depth)
        if bending_compliance <= 0:
            raise ValueError("measured slope is too stiff for the supplied shear compliance")
    modulus = span**3 / (4 * width * depth**3 * bending_compliance)
    if not isfinite(modulus):
        raise ValueError("flexural modulus is outside the finite measurement range")
    return modulus
