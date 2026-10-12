"""ASTM D638 specimen definitions used by the GUI and FEM stage.

The dimensions mirror the checked 2026-10-03 rig-reference package.  The
solver constructs the same analytic outlines directly in Gmsh so formal runs
do not depend on a separate CAD converter at runtime.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

D638SpecimenType = Literal["I", "IV", "V"]
REFERENCE_STANDARD = "ASTM D638-22"
REFERENCE_PACKAGE = "ASTM_D638_FFF_Rig_Reference_Package_checked_2026-10-03"


@dataclass(frozen=True)
class D638SpecimenDefinition:
    specimen_type: D638SpecimenType
    overall_length_mm: float
    overall_width_mm: float
    gauge_width_mm: float
    narrow_length_mm: float
    gauge_length_mm: float
    grip_separation_mm: float
    inner_radius_mm: float
    outer_radius_mm: float | None
    nominal_thickness_mm: float
    flat_tab_length_per_end_mm: float
    jaw_edge_relative_to_flat_start_mm: float
    reference_step_sha256: str

    @property
    def minimum_cross_section_area_mm2(self) -> float:
        return self.gauge_width_mm * self.nominal_thickness_mm


D638_SPECIMENS = MappingProxyType(
    {
        "I": D638SpecimenDefinition(
            specimen_type="I",
            overall_length_mm=165.0,
            overall_width_mm=19.0,
            gauge_width_mm=13.0,
            narrow_length_mm=57.0,
            gauge_length_mm=50.0,
            grip_separation_mm=115.0,
            inner_radius_mm=76.0,
            outer_radius_mm=None,
            nominal_thickness_mm=3.2,
            flat_tab_length_per_end_mm=32.857625488134026,
            jaw_edge_relative_to_flat_start_mm=7.857625488134026,
            reference_step_sha256="d7c025cc03349c6b34407b9a3f80a5bdf2c429e0ccb0cab8a65e4b0c052e5be0",
        ),
        "IV": D638SpecimenDefinition(
            specimen_type="IV",
            overall_length_mm=115.0,
            overall_width_mm=19.0,
            gauge_width_mm=6.0,
            narrow_length_mm=33.0,
            gauge_length_mm=25.0,
            grip_separation_mm=65.0,
            inner_radius_mm=14.0,
            outer_radius_mm=25.0,
            nominal_thickness_mm=3.2,
            flat_tab_length_per_end_mm=19.441938862689902,
            jaw_edge_relative_to_flat_start_mm=-5.558061137310098,
            reference_step_sha256="afd5da5f53fca22f154ba0fde86a67959b293419ba85cddfc675d1cbd8797289",
        ),
        "V": D638SpecimenDefinition(
            specimen_type="V",
            overall_length_mm=63.5,
            overall_width_mm=9.53,
            gauge_width_mm=3.18,
            narrow_length_mm=9.53,
            gauge_length_mm=7.62,
            grip_separation_mm=25.4,
            inner_radius_mm=12.7,
            outer_radius_mm=None,
            nominal_thickness_mm=3.2,
            flat_tab_length_per_end_mm=18.584739587369924,
            jaw_edge_relative_to_flat_start_mm=-0.46526041263007656,
            reference_step_sha256="adba35d2571f068badd0b20fc4713aafcd210c645fd2f9e50be3cec7a701084f",
        ),
    }
)


def d638_definition(specimen_type: D638SpecimenType) -> D638SpecimenDefinition:
    try:
        return D638_SPECIMENS[specimen_type]
    except KeyError as error:
        raise ValueError(f"unsupported ASTM D638 specimen type: {specimen_type}") from error


Point2D = tuple[float, float]
OutlineSegment = tuple[Literal["line", "arc"], Point2D, Point2D, Point2D | None]


def _line(a: Point2D, b: Point2D) -> OutlineSegment:
    return ("line", a, b, None)


def _arc(a: Point2D, b: Point2D, center: Point2D) -> OutlineSegment:
    return ("arc", a, b, center)


def d638_outline_segments(specimen_type: D638SpecimenType) -> tuple[OutlineSegment, ...]:
    """Return the exact 2D outline used by the checked reference package.

    Coordinates are centred on x=0/y=0, matching the source CAD generator.
    The FEM mesher translates the outline so its bounding box starts at x=y=0.
    """

    definition = d638_definition(specimen_type)
    lo = definition.overall_length_mm
    wo = definition.overall_width_mm
    w = definition.gauge_width_mm
    narrow_length = definition.narrow_length_mm
    radius = definition.inner_radius_mm

    xe = lo / 2.0
    yo = wo / 2.0
    yn = w / 2.0
    xn = narrow_length / 2.0

    if specimen_type in {"I", "V"}:
        dx = math.sqrt(radius * radius - (radius - (yo - yn)) ** 2)
        x_flat = xn + dx
        p0 = (-xe, -yo)
        p1 = (-x_flat, -yo)
        p2 = (-xn, -yn)
        p3 = (xn, -yn)
        p4 = (x_flat, -yo)
        p5 = (xe, -yo)
        p6 = (xe, yo)
        p7 = (x_flat, yo)
        p8 = (xn, yn)
        p9 = (-xn, yn)
        p10 = (-x_flat, yo)
        p11 = (-xe, yo)
        return (
            _line(p0, p1),
            _arc(p1, p2, (-xn, -yn - radius)),
            _line(p2, p3),
            _arc(p3, p4, (xn, -yn - radius)),
            _line(p4, p5),
            _line(p5, p6),
            _line(p6, p7),
            _arc(p7, p8, (xn, yn + radius)),
            _line(p8, p9),
            _arc(p9, p10, (-xn, yn + radius)),
            _line(p10, p11),
            _line(p11, p0),
        )

    outer_radius = definition.outer_radius_mm
    if outer_radius is None:
        raise ValueError("ASTM D638 Type IV requires an outer shoulder radius")

    c1 = (xn, yn + radius)
    c2y = yo - outer_radius
    dy = c2y - c1[1]
    dx = math.sqrt((radius + outer_radius) ** 2 - dy**2)
    x_flat = xn + dx
    c2 = (x_flat, c2y)
    joint_x = c1[0] + radius / (radius + outer_radius) * (c2[0] - c1[0])
    joint_y = c1[1] + radius / (radius + outer_radius) * (c2[1] - c1[1])

    p0 = (-xe, -yo)
    p1 = (-x_flat, -yo)
    joint_lower_left = (-joint_x, -joint_y)
    p2 = (-xn, -yn)
    p3 = (xn, -yn)
    joint_lower_right = (joint_x, -joint_y)
    p4 = (x_flat, -yo)
    p5 = (xe, -yo)
    p6 = (xe, yo)
    p7 = (x_flat, yo)
    joint_upper_right = (joint_x, joint_y)
    p8 = (xn, yn)
    p9 = (-xn, yn)
    joint_upper_left = (-joint_x, joint_y)
    p10 = (-x_flat, yo)
    p11 = (-xe, yo)

    return (
        _line(p0, p1),
        _arc(p1, joint_lower_left, (-x_flat, -c2y)),
        _arc(joint_lower_left, p2, (-xn, -(yn + radius))),
        _line(p2, p3),
        _arc(p3, joint_lower_right, (xn, -(yn + radius))),
        _arc(joint_lower_right, p4, (x_flat, -c2y)),
        _line(p4, p5),
        _line(p5, p6),
        _line(p6, p7),
        _arc(p7, joint_upper_right, (x_flat, c2y)),
        _arc(joint_upper_right, p8, (xn, yn + radius)),
        _line(p8, p9),
        _arc(p9, joint_upper_left, (-xn, yn + radius)),
        _arc(joint_upper_left, p10, (-x_flat, c2y)),
        _line(p10, p11),
        _line(p11, p0),
    )


def add_d638_gmsh_volume(gmsh, specimen_type: D638SpecimenType, thickness_mm: float) -> list[int]:
    """Create one analytic ASTM D638 solid in the active Gmsh OCC model."""

    if thickness_mm <= 0:
        raise ValueError("ASTM D638 specimen thickness must be positive")

    definition = d638_definition(specimen_type)
    x_offset = definition.overall_length_mm / 2.0
    y_offset = definition.overall_width_mm / 2.0
    point_tags: dict[Point2D, int] = {}

    def point_tag(point: Point2D) -> int:
        shifted = (point[0] + x_offset, point[1] + y_offset)
        if shifted not in point_tags:
            point_tags[shifted] = gmsh.model.occ.addPoint(shifted[0], shifted[1], 0.0)
        return point_tags[shifted]

    curves: list[int] = []
    for kind, start, end, center in d638_outline_segments(specimen_type):
        start_tag = point_tag(start)
        end_tag = point_tag(end)
        if kind == "line":
            curves.append(gmsh.model.occ.addLine(start_tag, end_tag))
        else:
            if center is None:
                raise ValueError("circular ASTM D638 segment is missing its center")
            curves.append(gmsh.model.occ.addCircleArc(start_tag, point_tag(center), end_tag))

    loop = gmsh.model.occ.addCurveLoop(curves)
    surface = gmsh.model.occ.addPlaneSurface([loop])
    extruded = gmsh.model.occ.extrude([(2, surface)], 0.0, 0.0, thickness_mm)
    volumes = [tag for dimension, tag in extruded if dimension == 3]
    if len(volumes) != 1:
        raise ValueError("ASTM D638 outline did not produce exactly one Gmsh volume")
    return volumes


def d638_geometry_metadata(
    specimen_type: D638SpecimenType,
    thickness_mm: float,
) -> dict[str, float | str | None]:
    definition = d638_definition(specimen_type)
    return {
        "standard_revision": REFERENCE_STANDARD,
        "reference_package": REFERENCE_PACKAGE,
        "specimen_type": definition.specimen_type,
        "overall_length_mm": definition.overall_length_mm,
        "overall_width_mm": definition.overall_width_mm,
        "gauge_width_mm": definition.gauge_width_mm,
        "narrow_length_mm": definition.narrow_length_mm,
        "gauge_length_mm": definition.gauge_length_mm,
        "grip_separation_mm": definition.grip_separation_mm,
        "inner_radius_mm": definition.inner_radius_mm,
        "outer_radius_mm": definition.outer_radius_mm,
        "thickness_mm": thickness_mm,
        "reference_step_sha256": definition.reference_step_sha256,
    }
