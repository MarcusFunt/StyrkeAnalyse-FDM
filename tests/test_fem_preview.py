"""Tests for the bounded, solver-derived mesh surface preview."""

from __future__ import annotations

import json

import pytest

from fdm_strength.fem_preview import (
    MAX_PREVIEW_BYTES,
    MAX_PREVIEW_TRIANGLES,
    build_surface_field_preview,
    validate_surface_field_preview,
)


def test_build_surface_field_preview_emits_all_faces_for_single_tetrahedron() -> None:
    preview = json.loads(
        build_surface_field_preview(
            points_mm=((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
            tetrahedra=((0, 1, 2, 3),),
            von_mises_mpa=(11.0,),
            axial_stress_mpa=(8.0,),
            axial_displacement_mm=(0.02,),
            mesh_sha256="a" * 64,
        )
    )

    assert preview["schema_version"] == 1
    assert preview["mesh_sha256"] == "a" * 64
    assert preview["total_boundary_triangle_count"] == 4
    assert preview["preview_sampled"] is False
    assert len(preview["points_mm"]) == 4
    assert len(preview["triangles"]) == 4
    assert {triangle["von_mises_stress_mpa"] for triangle in preview["triangles"]} == {11.0}
    assert {triangle["axial_stress_mpa"] for triangle in preview["triangles"]} == {8.0}
    assert {triangle["axial_displacement_mm"] for triangle in preview["triangles"]} == {0.02}


def test_build_surface_field_preview_excludes_shared_internal_face() -> None:
    preview = json.loads(
        build_surface_field_preview(
            points_mm=((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, -1)),
            tetrahedra=((0, 1, 2, 3), (0, 1, 2, 4)),
            von_mises_mpa=(11.0, 17.0),
            axial_stress_mpa=(8.0, 12.0),
            axial_displacement_mm=(0.02, 0.03),
            mesh_sha256="b" * 64,
        )
    )

    assert preview["total_boundary_triangle_count"] == 6
    assert len(preview["triangles"]) == 6
    triangles_per_cell = [
        sum(triangle["source_cell"] == cell for triangle in preview["triangles"])
        for cell in (0, 1)
    ]
    assert sorted(triangles_per_cell) == [3, 3]


def test_build_surface_field_preview_samples_deterministically_over_triangle_limit() -> None:
    points: list[tuple[float, float, float]] = []
    tetrahedra: list[tuple[int, int, int, int]] = []
    for cell in range(5_001):
        base = len(points)
        x = float(cell * 2)
        points.extend(((x, 0, 0), (x + 1, 0, 0), (x, 1, 0), (x, 0, 1)))
        tetrahedra.append((base, base + 1, base + 2, base + 3))
    fields = tuple(float(cell) for cell in range(len(tetrahedra)))

    first = build_surface_field_preview(
        points, tetrahedra, fields, fields, fields, "c" * 64
    )
    second = build_surface_field_preview(
        points, tetrahedra, fields, fields, fields, "c" * 64
    )

    preview = json.loads(first)
    assert first == second
    assert MAX_PREVIEW_TRIANGLES == 20_000
    assert preview["total_boundary_triangle_count"] == 4 * len(tetrahedra)
    assert len(preview["triangles"]) == MAX_PREVIEW_TRIANGLES
    assert preview["preview_sampled"] is True


@pytest.mark.parametrize(
    ("field_values", "mesh_sha256"),
    [((float("nan"),), "d" * 64), ((1.0,), "not-a-digest")],
)
def test_build_surface_field_preview_rejects_invalid_values(
    field_values: tuple[float, ...], mesh_sha256: str
) -> None:
    with pytest.raises(ValueError):
        build_surface_field_preview(
            points_mm=((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
            tetrahedra=((0, 1, 2, 3),),
            von_mises_mpa=field_values,
            axial_stress_mpa=(8.0,),
            axial_displacement_mm=(0.02,),
            mesh_sha256=mesh_sha256,
        )


def test_validate_surface_field_preview_binds_mesh_and_cell_indices() -> None:
    content = build_surface_field_preview(
        points_mm=((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        tetrahedra=((0, 1, 2, 3),),
        von_mises_mpa=(11.0,),
        axial_stress_mpa=(8.0,),
        axial_displacement_mm=(0.02,),
        mesh_sha256="e" * 64,
    )
    validate_surface_field_preview(content, mesh_sha256="e" * 64, cell_count=1)

    malformed = json.loads(content)
    malformed["triangles"][0]["vertices"][0] = 100
    with pytest.raises(ValueError, match="vertex index"):
        validate_surface_field_preview(
            json.dumps(malformed).encode(), mesh_sha256="e" * 64, cell_count=1
        )

    with pytest.raises(ValueError, match="mesh digest"):
        validate_surface_field_preview(content, mesh_sha256="f" * 64, cell_count=1)


def test_validate_surface_field_preview_rejects_oversized_content() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        validate_surface_field_preview(
            b" " * (MAX_PREVIEW_BYTES + 1), mesh_sha256="e" * 64, cell_count=1
        )
