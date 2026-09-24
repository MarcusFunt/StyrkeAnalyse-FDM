"""Small, validated calculations exposed by the local browser interface."""

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from fdm_strength.baseline import nominal_tensile_stress_mpa

_FORCE_TO_NEWTONS = {"N": 1.0, "kN": 1000.0}
_DISPLACEMENT_TO_MM = {"mm": 1.0, "cm": 10.0}


def _positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite positive number") from error
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _measurement(value: Any, row_number: int, column: str, decimal_separator: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"row {row_number}, column '{column}' must contain a number")
    text = str(value).strip()
    if not text:
        raise ValueError(f"row {row_number}, column '{column}' is empty")
    if decimal_separator == ",":
        if "," in text and "." in text:
            raise ValueError(f"row {row_number}, column '{column}' has ambiguous separators")
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError as error:
        raise ValueError(f"row {row_number}, column '{column}' must contain a number") from error
    if not isfinite(number):
        raise ValueError(f"row {row_number}, column '{column}' must be finite")
    return number


def analyze_tensile_rows(
    rows: Sequence[Mapping[str, Any]],
    force_column: str,
    displacement_column: str,
    width_mm: float,
    thickness_mm: float,
    gauge_length_mm: float,
    force_unit: str = "N",
    displacement_unit: str = "mm",
    decimal_separator: str = ".",
    tension_direction: str = "positive",
) -> dict[str, Any]:
    """Calculate nominal stress and engineering strain for mapped tensile rows."""
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise ValueError("rows must contain at least one measurement")
    if not isinstance(force_column, str) or not force_column.strip():
        raise ValueError("force_column must name a CSV column")
    if not isinstance(displacement_column, str) or not displacement_column.strip():
        raise ValueError("displacement_column must name a CSV column")
    if force_column == displacement_column:
        raise ValueError("force and displacement must use different columns")
    if force_unit not in _FORCE_TO_NEWTONS:
        raise ValueError("force_unit must be N or kN")
    if displacement_unit not in _DISPLACEMENT_TO_MM:
        raise ValueError("displacement_unit must be mm or cm")
    if decimal_separator not in {".", ","}:
        raise ValueError("decimal_separator must be '.' or ','")
    if tension_direction not in {"positive", "negative"}:
        raise ValueError("tension_direction must be positive or negative")

    width = _positive(width_mm, "width_mm")
    thickness = _positive(thickness_mm, "thickness_mm")
    gauge_length = _positive(gauge_length_mm, "gauge_length_mm")
    area = width * thickness
    force_scale = _FORCE_TO_NEWTONS[force_unit]
    displacement_scale = _DISPLACEMENT_TO_MM[displacement_unit]
    force_sign = 1.0 if tension_direction == "positive" else -1.0
    points: list[dict[str, float | int]] = []
    initial_displacement: float | None = None

    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"row {row_number} must be a column-to-value mapping")
        if force_column not in row:
            raise ValueError(f"row {row_number} is missing column '{force_column}'")
        if displacement_column not in row:
            raise ValueError(f"row {row_number} is missing column '{displacement_column}'")
        force = _measurement(row[force_column], row_number, force_column, decimal_separator)
        displacement = _measurement(
            row[displacement_column], row_number, displacement_column, decimal_separator
        )
        force_n = force * force_scale * force_sign
        displacement_mm = displacement * displacement_scale
        if initial_displacement is None:
            initial_displacement = displacement_mm
        extension_mm = displacement_mm - initial_displacement
        stress_mpa = nominal_tensile_stress_mpa(force_n, area)
        points.append(
            {
                "row_number": row_number,
                "force_n": force_n,
                "displacement_mm": displacement_mm,
                "extension_mm": extension_mm,
                "strain": extension_mm / gauge_length,
                "stress_mpa": stress_mpa,
            }
        )

    peak_force_point = max(points, key=lambda point: abs(point["force_n"]))
    peak_stress_point = max(points, key=lambda point: abs(point["stress_mpa"]))
    return {
        "sample_count": len(points),
        "cross_section_area_mm2": area,
        "gauge_length_mm": gauge_length,
        "peak_force_n": abs(peak_force_point["force_n"]),
        "peak_force_row": peak_force_point["row_number"],
        "peak_stress_mpa": abs(peak_stress_point["stress_mpa"]),
        "peak_stress_row": peak_stress_point["row_number"],
        "points": points,
    }
