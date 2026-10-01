"""Build a bounded, content-addressable surface view from solver mesh values."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from typing import Any

MAX_PREVIEW_TRIANGLES = 20_000
MAX_PREVIEW_BYTES = 16 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TETRA_FACES = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must contain finite numbers")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{label} must contain finite numbers")
    return converted


def build_surface_field_preview(
    points_mm: Sequence[Sequence[float]],
    tetrahedra: Sequence[Sequence[int]],
    von_mises_mpa: Sequence[float],
    axial_stress_mpa: Sequence[float],
    axial_displacement_mm: Sequence[float],
    mesh_sha256: str,
) -> bytes:
    """Serialize boundary triangles and cell-average fields for interactive viewing.

    The full volume mesh and XDMF/HDF5 fields remain the scientific outputs. This
    representation is only a surface preview, bounded to 20,000 triangles.
    """
    if not isinstance(mesh_sha256, str) or _SHA256.fullmatch(mesh_sha256) is None:
        raise ValueError("mesh_sha256 must be a lowercase SHA-256 digest")
    if len(points_mm) == 0 or len(tetrahedra) == 0:
        raise ValueError("preview requires mesh points and tetrahedra")
    point_rows: list[tuple[float, float, float]] = []
    for point_index, point in enumerate(points_mm):
        if len(point) != 3:
            raise ValueError(f"mesh point {point_index} must have three coordinates")
        point_rows.append(
            tuple(_finite_float(value, f"mesh point {point_index}") for value in point)  # type: ignore[arg-type]
        )

    cells: list[tuple[int, int, int, int]] = []
    for cell_index, cell in enumerate(tetrahedra):
        if len(cell) != 4 or any(
            isinstance(index, bool) or not isinstance(index, Integral) for index in cell
        ):
            raise ValueError(f"tetrahedron {cell_index} must contain four integer point indices")
        indices = tuple(int(index) for index in cell)
        if len(set(indices)) != 4 or any(
            index < 0 or index >= len(point_rows) for index in indices
        ):
            raise ValueError(f"tetrahedron {cell_index} contains invalid point indices")
        cells.append(indices)

    fields = {
        "von_mises_stress_mpa": von_mises_mpa,
        "axial_stress_mpa": axial_stress_mpa,
        "axial_displacement_mm": axial_displacement_mm,
    }
    normalized_fields: dict[str, list[float]] = {}
    for field_name, values in fields.items():
        if len(values) != len(cells):
            raise ValueError(f"{field_name} must have one average per tetrahedron")
        normalized_fields[field_name] = [
            _finite_float(value, field_name) for value in values
        ]
    if any(value < 0 for value in normalized_fields["von_mises_stress_mpa"]):
        raise ValueError("von Mises stress must be non-negative")

    face_owners: dict[tuple[int, int, int], list[tuple[int, int, int, int]]] = {}
    for cell_index, cell in enumerate(cells):
        for local_face in _TETRA_FACES:
            face = tuple(cell[position] for position in local_face)
            face_owners.setdefault(tuple(sorted(face)), []).append((cell_index, *face))
    if any(len(owners) > 2 for owners in face_owners.values()):
        raise ValueError("mesh contains a non-manifold tetrahedron face")
    boundary = [
        owner
        for owners in face_owners.values()
        if len(owners) == 1
        for owner in owners
    ]
    total_boundary_count = len(boundary)
    if total_boundary_count == 0:
        raise ValueError("mesh has no boundary surface triangles")

    if total_boundary_count <= MAX_PREVIEW_TRIANGLES:
        selected = boundary
    else:
        selected = [
            boundary[(sample_index * total_boundary_count) // MAX_PREVIEW_TRIANGLES]
            for sample_index in range(MAX_PREVIEW_TRIANGLES)
        ]

    used_point_ids = sorted({point_id for _, *face in selected for point_id in face})
    point_mapping = {source: output for output, source in enumerate(used_point_ids)}
    triangles = []
    for cell_index, first, second, third in selected:
        triangles.append(
            {
                "vertices": [
                    point_mapping[first],
                    point_mapping[second],
                    point_mapping[third],
                ],
                "source_cell": cell_index,
                **{
                    name: values[cell_index]
                    for name, values in normalized_fields.items()
                },
            }
        )

    preview = {
        "schema_version": 1,
        "mesh_sha256": mesh_sha256,
        "coordinate_units": "mm",
        "field_location": "boundary_element_average",
        "preview_sampled": total_boundary_count > MAX_PREVIEW_TRIANGLES,
        "tetrahedron_count": len(cells),
        "total_boundary_triangle_count": total_boundary_count,
        "points_mm": [point_rows[index] for index in used_point_ids],
        "triangles": triangles,
    }
    return (
        json.dumps(
            preview,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def validate_surface_field_preview(
    content: bytes, *, mesh_sha256: str, cell_count: int
) -> dict[str, Any]:
    """Validate a preview artifact against the mesh and cell count in its Run."""
    if len(content) > MAX_PREVIEW_BYTES:
        raise ValueError("FEM field preview exceeds the 16 MiB viewer limit")

    def reject_constant(value: str) -> None:
        raise ValueError(f"FEM field preview contains invalid number {value}")

    try:
        preview = json.loads(content, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("FEM field preview is not valid JSON") from error
    expected_keys = {
        "schema_version",
        "mesh_sha256",
        "coordinate_units",
        "field_location",
        "preview_sampled",
        "tetrahedron_count",
        "total_boundary_triangle_count",
        "points_mm",
        "triangles",
    }
    if not isinstance(preview, Mapping) or set(preview) != expected_keys:
        raise ValueError("FEM field preview has an unsupported schema")
    if (
        preview["schema_version"] != 1
        or preview["mesh_sha256"] != mesh_sha256
        or preview["coordinate_units"] != "mm"
        or preview["field_location"] != "boundary_element_average"
    ):
        raise ValueError("FEM field preview schema or mesh digest does not match its Run")
    if (
        isinstance(cell_count, bool)
        or not isinstance(cell_count, int)
        or cell_count <= 0
        or preview["tetrahedron_count"] != cell_count
    ):
        raise ValueError("FEM field preview cell count does not match its mesh")

    points = preview["points_mm"]
    triangles = preview["triangles"]
    total = preview["total_boundary_triangle_count"]
    sampled = preview["preview_sampled"]
    if (
        not isinstance(points, list)
        or not points
        or not isinstance(triangles, list)
        or not triangles
        or len(triangles) > MAX_PREVIEW_TRIANGLES
        or isinstance(total, bool)
        or not isinstance(total, int)
        or total < len(triangles)
        or not isinstance(sampled, bool)
        or sampled != (total > len(triangles))
    ):
        raise ValueError("FEM field preview counts or sampling metadata are invalid")
    for point in points:
        if (
            not isinstance(point, list)
            or len(point) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in point
            )
        ):
            raise ValueError("FEM field preview contains an invalid coordinate")

    triangle_keys = {
        "vertices",
        "source_cell",
        "von_mises_stress_mpa",
        "axial_stress_mpa",
        "axial_displacement_mm",
    }
    for triangle in triangles:
        if not isinstance(triangle, Mapping) or set(triangle) != triangle_keys:
            raise ValueError("FEM field preview contains an invalid triangle")
        vertices = triangle["vertices"]
        source_cell = triangle["source_cell"]
        if (
            not isinstance(vertices, list)
            or len(vertices) != 3
            or any(
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < len(points)
                for index in vertices
            )
            or len(set(vertices)) != 3
        ):
            raise ValueError("FEM field preview contains an invalid vertex index")
        if (
            isinstance(source_cell, bool)
            or not isinstance(source_cell, int)
            or not 0 <= source_cell < cell_count
        ):
            raise ValueError("FEM field preview contains an invalid source cell")
        for name in triangle_keys - {"vertices", "source_cell"}:
            value = triangle[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("FEM field preview contains a non-finite field value")
        if triangle["von_mises_stress_mpa"] < 0:
            raise ValueError("FEM field preview von Mises stress cannot be negative")
    return dict(preview)
