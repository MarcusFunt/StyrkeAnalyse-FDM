"""Analytical fracture conversions and a calibratable bilinear cohesive envelope."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt


def j_to_k_mpa_sqrt_mm(
    j_n_per_mm: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    *,
    plane: str,
) -> float:
    """Convert isotropic elastic J to K; this is not a J-integral solver."""
    values = (j_n_per_mm, elastic_modulus_mpa, poisson_ratio)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
        for value in values
    ):
        raise ValueError("fracture conversion inputs must be finite")
    if j_n_per_mm < 0 or elastic_modulus_mpa <= 0 or not -1 < poisson_ratio < 0.5:
        raise ValueError("invalid J, modulus, or Poisson ratio")
    if plane not in {"stress", "strain"}:
        raise ValueError("plane must be 'stress' or 'strain'")
    effective_modulus = (
        elastic_modulus_mpa if plane == "stress" else elastic_modulus_mpa / (1 - poisson_ratio**2)
    )
    return sqrt(j_n_per_mm * effective_modulus)


@dataclass(frozen=True)
class BilinearCohesiveLaw:
    """Mode-I traction envelope with initial stiffness, peak traction, and Gc."""

    peak_traction_mpa: float
    fracture_energy_n_per_mm: float
    initial_stiffness_mpa_per_mm: float

    def __post_init__(self) -> None:
        values = (
            self.peak_traction_mpa,
            self.fracture_energy_n_per_mm,
            self.initial_stiffness_mpa_per_mm,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or value <= 0
            for value in values
        ):
            raise ValueError("cohesive law parameters must be finite and positive")
        if self.initiation_separation_mm >= self.final_separation_mm:
            raise ValueError("cohesive stiffness is too low for the specified fracture energy")

    @property
    def initiation_separation_mm(self) -> float:
        return self.peak_traction_mpa / self.initial_stiffness_mpa_per_mm

    @property
    def final_separation_mm(self) -> float:
        return 2 * self.fracture_energy_n_per_mm / self.peak_traction_mpa

    @property
    def envelope_area_n_per_mm(self) -> float:
        """Exact area under the piecewise-linear traction-separation envelope."""
        return self.peak_traction_mpa * self.final_separation_mm / 2

    def traction_mpa(self, separation_mm: float) -> float:
        if (
            isinstance(separation_mm, bool)
            or not isinstance(separation_mm, (int, float))
            or not isfinite(separation_mm)
            or separation_mm < 0
        ):
            raise ValueError("separation must be finite and non-negative")
        if separation_mm >= self.final_separation_mm:
            return 0.0
        if separation_mm <= self.initiation_separation_mm:
            return self.initial_stiffness_mpa_per_mm * separation_mm
        return (
            self.peak_traction_mpa
            * (self.final_separation_mm - separation_mm)
            / (self.final_separation_mm - self.initiation_separation_mm)
        )
