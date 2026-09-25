"""Specimen-level tensile reduction and campaign replicate statistics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Any

MODULUS_STRAIN_WINDOW = (0.0005, 0.0025)
MINIMUM_SPECIMENS_PER_CONFIGURATION = 5
MAXIMUM_CAMPAIGN_CV_PERCENT = 15.0
_DIRECT_STRAIN_SENSORS = {"extensometer", "clip_gauge", "dic"}


@dataclass(frozen=True)
class SpecimenModulus:
    specimen_id: str
    modulus_mpa: float | None
    status: str
    reason: str | None
    strain_interval: tuple[float, float] = MODULUS_STRAIN_WINDOW
    sensor_source: str = "unknown"
    correction_method: str = "unknown"


@dataclass(frozen=True)
class CampaignModulus:
    n_total: int
    n_valid: int
    mean_mpa: float | None
    sample_standard_deviation_mpa: float | None
    coefficient_of_variation_percent: float | None
    minimum_specimens: int
    maximum_cv_percent: float
    replicate_ready: bool
    reason: str | None

    @property
    def ready_for_validation(self) -> bool:
        """Backward-compatible alias; this gate only establishes replicate readiness."""
        return self.replicate_ready


def _finite_point_value(point: dict[str, Any], key: str) -> float:
    value = point.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"analysis point {key} must be finite")
    return float(value)


def _interpolate_at(target: float, strains: list[float], stresses: list[float]) -> float | None:
    for index, strain in enumerate(strains):
        if strain == target:
            return stresses[index]
        if index == 0:
            continue
        previous_strain = strains[index - 1]
        if previous_strain < target < strain:
            fraction = (target - previous_strain) / (strain - previous_strain)
            return stresses[index - 1] + fraction * (stresses[index] - stresses[index - 1])
    return None


def _ineligible(
    specimen_id: str,
    reason: str,
    sensor_source: str,
    correction_method: str,
) -> SpecimenModulus:
    return SpecimenModulus(
        specimen_id=specimen_id,
        modulus_mpa=None,
        status="ineligible",
        reason=reason,
        sensor_source=sensor_source,
        correction_method=correction_method,
    )


def reduce_tensile_modulus(
    specimen_id: str,
    points: list[dict[str, Any]],
    *,
    gauge_length_mm: float,
    sensor_source: str,
    compliance_correction: dict[str, Any],
) -> SpecimenModulus:
    """Calculate the project chord modulus from strain 0.0005 through 0.0025.

    Direct gauge-strain sensors use the recorded engineering strain. Crosshead
    displacement is eligible only with a documented machine compliance, which
    is subtracted using the force change from the first recorded point.
    Acquisition order is retained; non-monotonic corrected strain is rejected
    rather than sorted into a potentially different loading path.
    """
    correction_method = str(compliance_correction.get("method", "unknown"))
    sensor = sensor_source.strip().lower()
    if sensor not in _DIRECT_STRAIN_SENSORS and sensor != "crosshead":
        return _ineligible(
            specimen_id,
            "A supported gauge-strain sensor source must be recorded before modulus reduction.",
            sensor,
            correction_method,
        )
    if not isinstance(gauge_length_mm, (int, float)) or isinstance(gauge_length_mm, bool):
        return _ineligible(
            specimen_id, "Gauge length must be finite and positive.", sensor, correction_method
        )
    if not math.isfinite(gauge_length_mm) or gauge_length_mm <= 0:
        return _ineligible(
            specimen_id, "Gauge length must be finite and positive.", sensor, correction_method
        )
    compliance = 0.0
    if sensor == "crosshead":
        compliance = compliance_correction.get("compliance_mm_per_n")
        calibration = compliance_correction.get("calibration_source")
        if (
            correction_method != "machine_compliance"
            or isinstance(compliance, bool)
            or not isinstance(compliance, (int, float))
            or not math.isfinite(compliance)
            or compliance <= 0
            or not isinstance(calibration, str)
            or not calibration.strip()
        ):
            return _ineligible(
                specimen_id,
                "Crosshead strain requires a positive, documented machine compliance correction.",
                sensor,
                correction_method,
            )
    if not points:
        return _ineligible(
            specimen_id, "No analysis points are available.", sensor, correction_method
        )

    strains: list[float] = []
    stresses: list[float] = []
    forces: list[float] = []
    try:
        for point in points:
            if sensor == "crosshead":
                forces.append(_finite_point_value(point, "force_n"))
                stresses.append(_finite_point_value(point, "stress_mpa"))
            else:
                strains.append(_finite_point_value(point, "strain"))
                stresses.append(_finite_point_value(point, "stress_mpa"))
    except (KeyError, TypeError, ValueError) as error:
        return _ineligible(specimen_id, str(error), sensor, correction_method)

    if sensor == "crosshead":
        first_force = forces[0]
        try:
            strains = [
                (_finite_point_value(point, "extension_mm") - (force - first_force) * compliance)
                / gauge_length_mm
                for point, force in zip(points, forces, strict=True)
            ]
        except (KeyError, TypeError, ValueError) as error:
            return _ineligible(specimen_id, str(error), sensor, correction_method)

    if any(current < previous for previous, current in zip(strains, strains[1:], strict=False)):
        return _ineligible(
            specimen_id,
            "Corrected strain is non-monotonic; the loading interval is ambiguous.",
            sensor,
            correction_method,
        )
    lower, upper = MODULUS_STRAIN_WINDOW
    stress_lower = _interpolate_at(lower, strains, stresses)
    stress_upper = _interpolate_at(upper, strains, stresses)
    if stress_lower is None or stress_upper is None:
        return _ineligible(
            specimen_id,
            f"The measured strain curve does not cover the full {lower:g}–{upper:g} strain window.",
            sensor,
            correction_method,
        )
    modulus = (stress_upper - stress_lower) / (upper - lower)
    if not math.isfinite(modulus) or modulus <= 0:
        return _ineligible(
            specimen_id,
            "The chord slope over the project strain window is not finite and positive.",
            sensor,
            correction_method,
        )
    return SpecimenModulus(
        specimen_id=specimen_id,
        modulus_mpa=modulus,
        status="eligible",
        reason=None,
        sensor_source=sensor,
        correction_method=correction_method,
    )


def aggregate_modulus(
    specimen_reductions: list[SpecimenModulus],
    *,
    minimum_specimens: int = MINIMUM_SPECIMENS_PER_CONFIGURATION,
    maximum_cv_percent: float = MAXIMUM_CAMPAIGN_CV_PERCENT,
) -> CampaignModulus:
    """Reduce one eligible modulus per physical specimen using sample SD."""
    if minimum_specimens < 2:
        raise ValueError("minimum_specimens must be at least two")
    if not math.isfinite(maximum_cv_percent) or maximum_cv_percent < 0:
        raise ValueError("maximum_cv_percent must be finite and non-negative")
    specimen_ids = [reduction.specimen_id for reduction in specimen_reductions]
    if len(set(specimen_ids)) != len(specimen_ids):
        raise ValueError("specimen reductions must have unique specimen IDs")
    valid = [
        reduction.modulus_mpa
        for reduction in specimen_reductions
        if reduction.status == "eligible"
        and reduction.modulus_mpa is not None
        and math.isfinite(reduction.modulus_mpa)
        and reduction.modulus_mpa > 0
    ]
    n_valid = len(valid)
    average = mean(valid) if valid else None
    standard_deviation = stdev(valid) if n_valid >= 2 else None
    coefficient_of_variation = (
        100 * standard_deviation / abs(average)
        if standard_deviation is not None and average not in (None, 0)
        else None
    )
    reasons: list[str] = []
    if n_valid < minimum_specimens:
        reasons.append(
            f"At least {minimum_specimens} valid specimens are required; {n_valid} are available."
        )
    if coefficient_of_variation is None:
        reasons.append(
            "Coefficient of variation is undefined for fewer than two valid specimens "
            "or a zero mean."
        )
    elif coefficient_of_variation > maximum_cv_percent:
        reasons.append(
            f"Coefficient of variation {coefficient_of_variation:.2f}% exceeds the "
            f"{maximum_cv_percent:.2f}% limit."
        )
    ready = (
        n_valid >= minimum_specimens
        and coefficient_of_variation is not None
        and coefficient_of_variation <= maximum_cv_percent
    )
    return CampaignModulus(
        n_total=len(specimen_reductions),
        n_valid=n_valid,
        mean_mpa=average,
        sample_standard_deviation_mpa=standard_deviation,
        coefficient_of_variation_percent=coefficient_of_variation,
        minimum_specimens=minimum_specimens,
        maximum_cv_percent=maximum_cv_percent,
        replicate_ready=ready,
        reason=" ".join(reasons) or None,
    )
