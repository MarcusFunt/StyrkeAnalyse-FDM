"""Classical laminate theory for plane-stress orthotropic raster plies."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, radians, sin

import numpy as np

Matrix3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


@dataclass(frozen=True)
class Lamina:
    e1_mpa: float
    e2_mpa: float
    nu12: float
    g12_mpa: float

    def __post_init__(self) -> None:
        values = (self.e1_mpa, self.e2_mpa, self.nu12, self.g12_mpa)
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            for value in values
        ):
            raise ValueError("lamina constants must be finite")
        if self.e1_mpa <= 0 or self.e2_mpa <= 0 or self.g12_mpa <= 0:
            raise ValueError("lamina elastic moduli must be positive")
        if 1 - self.nu12**2 * self.e2_mpa / self.e1_mpa <= 0:
            raise ValueError(
                "lamina constants do not define a positive-definite plane-stress material"
            )

    def q_mpa(self) -> np.ndarray:
        nu21 = self.nu12 * self.e2_mpa / self.e1_mpa
        denominator = 1 - self.nu12 * nu21
        return np.array(
            [
                [self.e1_mpa / denominator, self.nu12 * self.e2_mpa / denominator, 0],
                [self.nu12 * self.e2_mpa / denominator, self.e2_mpa / denominator, 0],
                [0, 0, self.g12_mpa],
            ],
            dtype=float,
        )

    def ply(self, angle_degrees: float, thickness_mm: float) -> Ply:
        return Ply(self, angle_degrees, thickness_mm)


@dataclass(frozen=True)
class Ply:
    lamina: Lamina
    angle_degrees: float
    thickness_mm: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.angle_degrees, bool)
            or not isinstance(self.angle_degrees, (int, float))
            or not isfinite(self.angle_degrees)
        ):
            raise ValueError("ply angle must be finite")
        if (
            isinstance(self.thickness_mm, bool)
            or not isinstance(self.thickness_mm, (int, float))
            or not isfinite(self.thickness_mm)
            or self.thickness_mm <= 0
        ):
            raise ValueError("ply thickness must be finite and positive")


def transformed_q_mpa(lamina: Lamina, angle_degrees: float) -> Matrix3:
    """Transform the reduced stiffness Q into laminate x-y axes."""
    q = lamina.q_mpa()
    q11, q22, q12, q66 = q[0, 0], q[1, 1], q[0, 1], q[2, 2]
    m, n = cos(radians(angle_degrees)), sin(radians(angle_degrees))
    m2, n2, m4, n4 = m * m, n * n, m**4, n**4
    common = q12 + 2 * q66
    qbar = np.array(
        [
            [
                q11 * m4 + 2 * common * m2 * n2 + q22 * n4,
                (q11 + q22 - 4 * q66) * m2 * n2 + q12 * (m4 + n4),
                (q11 - q12 - 2 * q66) * m**3 * n - (q22 - q12 - 2 * q66) * m * n**3,
            ],
            [
                (q11 + q22 - 4 * q66) * m2 * n2 + q12 * (m4 + n4),
                q11 * n4 + 2 * common * m2 * n2 + q22 * m4,
                (q11 - q12 - 2 * q66) * m * n**3 - (q22 - q12 - 2 * q66) * m**3 * n,
            ],
            [
                (q11 - q12 - 2 * q66) * m**3 * n - (q22 - q12 - 2 * q66) * m * n**3,
                (q11 - q12 - 2 * q66) * m * n**3 - (q22 - q12 - 2 * q66) * m**3 * n,
                (q11 + q22 - 2 * q12 - 2 * q66) * m2 * n2 + q66 * (m4 + n4),
            ],
        ],
        dtype=float,
    )
    return _matrix_tuple(qbar)


def laminate_abd(plies: list[Ply]) -> dict[str, Matrix3 | float]:
    """Integrate transformed ply stiffnesses through thickness about the midplane."""
    if not plies:
        raise ValueError("a laminate requires at least one ply")
    total_thickness = sum(ply.thickness_mm for ply in plies)
    if not isfinite(total_thickness):
        raise ValueError("total laminate thickness must be finite")
    z = -total_thickness / 2
    a, b, d = np.zeros((3, 3)), np.zeros((3, 3)), np.zeros((3, 3))
    for ply in plies:
        next_z = z + ply.thickness_mm
        qbar = np.asarray(transformed_q_mpa(ply.lamina, ply.angle_degrees))
        a += qbar * (next_z - z)
        b += qbar * (next_z**2 - z**2) / 2
        d += qbar * (next_z**3 - z**3) / 3
        z = next_z
    if not all(np.isfinite(matrix).all() for matrix in (a, b, d)):
        raise ValueError("laminate stiffness matrices must be finite")
    return {
        "A": _matrix_tuple(a),
        "B": _matrix_tuple(b),
        "D": _matrix_tuple(d),
        "thickness_mm": total_thickness,
    }


def laminate_moduli_mpa(plies: list[Ply]) -> dict[str, float]:
    """Effective uniaxial extensional and flexural moduli for free transverse edges."""
    abd = laminate_abd(plies)
    thickness = float(abd["thickness_mm"])
    a = np.asarray(abd["A"])
    b = np.asarray(abd["B"])
    d = np.asarray(abd["D"])
    # With free resultants, extension-bending coupling changes both effective
    # stiffness blocks for an unsymmetric laminate.
    effective_a = a - b @ np.linalg.solve(d, b)
    effective_d = d - b @ np.linalg.solve(a, b)
    compliance_a = np.linalg.inv(effective_a)
    compliance_d = np.linalg.inv(effective_d)
    return {
        "ex_mpa": float(1 / (compliance_a[0, 0] * thickness)),
        "ey_mpa": float(1 / (compliance_a[1, 1] * thickness)),
        "gxy_mpa": float(1 / (compliance_a[2, 2] * thickness)),
        "ex_flexural_mpa": float(12 / (compliance_d[0, 0] * thickness**3)),
        "ey_flexural_mpa": float(12 / (compliance_d[1, 1] * thickness**3)),
    }


def _matrix_tuple(matrix: np.ndarray) -> Matrix3:
    return tuple(tuple(float(value) for value in row) for row in matrix)  # type: ignore[return-value]
