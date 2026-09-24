"""Transversely isotropic elasticity and plane-stress failure criteria."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite, sqrt

import numpy as np


@dataclass(frozen=True)
class TransverselyIsotropic:
    """Five engineering constants with axis 1 aligned to the raster direction."""

    e1_mpa: float
    e2_mpa: float
    nu12: float
    nu23: float
    g12_mpa: float

    def constants(self) -> dict[str, float]:
        values = (self.e1_mpa, self.e2_mpa, self.nu12, self.nu23, self.g12_mpa)
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            for value in values
        ):
            raise ValueError("orthotropic constants must be finite")
        if self.e1_mpa <= 0 or self.e2_mpa <= 0 or self.g12_mpa <= 0:
            raise ValueError("elastic moduli must be positive")
        if self.nu23 <= -1:
            raise ValueError("nu23 must be greater than -1")
        return {
            "e1_mpa": self.e1_mpa,
            "e2_mpa": self.e2_mpa,
            "e3_mpa": self.e2_mpa,
            "nu12": self.nu12,
            "nu13": self.nu12,
            "nu23": self.nu23,
            "g12_mpa": self.g12_mpa,
            "g13_mpa": self.g12_mpa,
            "g23_mpa": self.e2_mpa / (2 * (1 + self.nu23)),
        }

    def stiffness_mpa(self) -> tuple[tuple[float, ...], ...]:
        c = self.constants()
        compliance = np.zeros((6, 6), dtype=float)
        compliance[0, 0] = 1 / c["e1_mpa"]
        compliance[1, 1] = 1 / c["e2_mpa"]
        compliance[2, 2] = 1 / c["e3_mpa"]
        compliance[0, 1] = compliance[1, 0] = -c["nu12"] / c["e1_mpa"]
        compliance[0, 2] = compliance[2, 0] = -c["nu13"] / c["e1_mpa"]
        compliance[1, 2] = compliance[2, 1] = -c["nu23"] / c["e2_mpa"]
        compliance[3, 3] = 1 / c["g23_mpa"]
        compliance[4, 4] = 1 / c["g13_mpa"]
        compliance[5, 5] = 1 / c["g12_mpa"]
        if not np.isfinite(compliance).all() or np.min(np.linalg.eigvalsh(compliance)) <= 0:
            raise ValueError("engineering constants do not define a stable elastic material")
        stiffness = np.linalg.inv(compliance)
        if not np.isfinite(stiffness).all():
            raise ValueError("engineering constants produce non-finite stiffness")
        return tuple(tuple(float(value) for value in row) for row in stiffness)


def maximum_stress_index(
    stress_mpa: Sequence[float], strengths_mpa: Mapping[str, float]
) -> dict[str, float | str]:
    """Return the maximum absolute component/allowable and its mode.

    Stress ordering is (σ1, σ2, σ3, τ23, τ13, τ12). Only strengths for nonzero
    components are required, which supports plane-stress coupon reductions.
    """
    if len(stress_mpa) != 6 or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
        for value in stress_mpa
    ):
        raise ValueError("stress_mpa must contain six finite components")
    normal_modes = (
        ("sigma1_tension", "xt_mpa", "sigma1_compression", "xc_mpa"),
        ("sigma2_tension", "yt_mpa", "sigma2_compression", "yc_mpa"),
        ("sigma3_tension", "zt_mpa", "sigma3_compression", "zc_mpa"),
    )
    indices: list[tuple[float, str]] = []
    for component, (tension_mode, tension_key, compression_mode, compression_key) in enumerate(
        normal_modes
    ):
        stress = float(stress_mpa[component])
        if stress == 0:
            continue
        mode, key = (
            (tension_mode, tension_key) if stress >= 0 else (compression_mode, compression_key)
        )
        indices.append((abs(stress) / _positive(strengths_mpa.get(key), key), mode))
    for component, mode, key in (
        (3, "tau23", "s23_mpa"),
        (4, "tau13", "s13_mpa"),
        (5, "tau12", "s12_mpa"),
    ):
        if stress_mpa[component] != 0:
            indices.append(
                (abs(float(stress_mpa[component])) / _positive(strengths_mpa.get(key), key), mode)
            )
    if not indices:
        return {"index": 0.0, "critical_mode": "none"}
    index, mode = max(indices)
    return {"index": index, "critical_mode": mode}


def plane_stress_tsai_wu_index(
    stress_mpa: Sequence[float],
    strengths_mpa: Mapping[str, float],
    *,
    interaction_factor: float,
) -> dict[str, float | str]:
    """Plane-stress Tsai–Wu index; interaction factor must be explicitly recorded.

    `interaction_factor` is the dimensionless value f12 in F12 = f12√(F11 F22).
    Its value is a modelling assumption and must not be inferred from the elastic
    constants. This plane-stress form uses (σ1, σ2, τ12).
    """
    if len(stress_mpa) != 3 or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
        for value in stress_mpa
    ):
        raise ValueError("plane-stress input must contain three finite components")
    if (
        isinstance(interaction_factor, bool)
        or not isinstance(interaction_factor, (int, float))
        or not isfinite(interaction_factor)
        or not -1 <= interaction_factor <= 1
    ):
        raise ValueError("interaction_factor must be finite and between -1 and 1")
    xt, xc = (
        _positive(strengths_mpa.get("xt_mpa"), "xt_mpa"),
        _positive(strengths_mpa.get("xc_mpa"), "xc_mpa"),
    )
    yt, yc = (
        _positive(strengths_mpa.get("yt_mpa"), "yt_mpa"),
        _positive(strengths_mpa.get("yc_mpa"), "yc_mpa"),
    )
    shear = _positive(strengths_mpa.get("s12_mpa"), "s12_mpa")
    f1, f2 = 1 / xt - 1 / xc, 1 / yt - 1 / yc
    f11, f22, f66 = 1 / (xt * xc), 1 / (yt * yc), 1 / shear**2
    f12 = interaction_factor * sqrt(f11 * f22)
    s1, s2, t12 = (float(value) for value in stress_mpa)
    index = f1 * s1 + f2 * s2 + f11 * s1**2 + f22 * s2**2 + 2 * f12 * s1 * s2 + f66 * t12**2
    return {
        "index": index,
        "assumption": f"interaction_factor={interaction_factor:g}; F12=f12*sqrt(F11*F22)",
    }


def _positive(value: float | None, name: str) -> float:
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be finite and positive")
    return float(value)
