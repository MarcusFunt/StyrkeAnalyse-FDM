"""Normalize supported FDM G-code moves into traceable millimeter geometry."""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
import re
from typing import Literal

from gcodeparser import parse_gcode_lines
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_TOOLPATH_BYTES = 64 * 1024 * 1024
MAX_TOOLPATH_MOVES = 1_000_000
_EPSILON_MM = 1e-12
_LAYER_INDEX = re.compile(r"(?:^|\s)LAYER\s*:\s*(\d+)", re.IGNORECASE)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ToolpathPoint(_FrozenModel):
    x_mm: float
    y_mm: float
    z_mm: float

    @field_validator("x_mm", "y_mm", "z_mm")
    @classmethod
    def coordinates_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("toolpath coordinates must be finite")
        return value


class ToolpathBounds(_FrozenModel):
    min_x_mm: float
    min_y_mm: float
    min_z_mm: float
    max_x_mm: float
    max_y_mm: float
    max_z_mm: float

    @model_validator(mode="after")
    def validate_bounds(self) -> ToolpathBounds:
        values = (
            self.min_x_mm,
            self.min_y_mm,
            self.min_z_mm,
            self.max_x_mm,
            self.max_y_mm,
            self.max_z_mm,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("toolpath bounds must be finite")
        if (
            self.max_x_mm < self.min_x_mm
            or self.max_y_mm < self.min_y_mm
            or self.max_z_mm < self.min_z_mm
        ):
            raise ValueError("toolpath maximum bounds cannot be below minimum bounds")
        return self


class ToolpathMove(_FrozenModel):
    move_index: int = Field(ge=0)
    source_line: int = Field(ge=1)
    layer_index: int | None = Field(default=None, ge=0)
    tool_index: int = Field(ge=0)
    kind: Literal["travel", "deposition"]
    start: ToolpathPoint
    end: ToolpathPoint
    path_length_mm: float = Field(gt=0)
    extrusion_delta_mm: float
    feed_rate_mm_min: float | None = Field(default=None, gt=0)
    direction: tuple[float, float, float]
    raster_angle_deg: float | None = Field(default=None, ge=0, lt=180)

    @model_validator(mode="after")
    def validate_move(self) -> ToolpathMove:
        values = (
            self.path_length_mm,
            self.extrusion_delta_mm,
            *self.direction,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("toolpath move values must be finite")
        if len(self.direction) != 3:
            raise ValueError("toolpath direction must have three components")
        direction_norm = math.sqrt(sum(component * component for component in self.direction))
        if not math.isclose(direction_norm, 1.0, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("toolpath direction must be a unit vector")
        if self.kind == "deposition" and self.extrusion_delta_mm <= 0:
            raise ValueError("deposition moves require positive commanded extrusion")
        if self.raster_angle_deg is not None and self.raster_angle_deg >= 180:
            raise ValueError("in-plane raster angle must be modulo 180 degrees")
        return self


class ToolpathModel(_FrozenModel):
    schema_version: Literal[1] = 1
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size_bytes: int = Field(ge=1, le=MAX_TOOLPATH_BYTES)
    parser_name: Literal["gcodeparser"] = "gcodeparser"
    parser_version: str = Field(min_length=1, max_length=32)
    coordinate_units: Literal["mm"] = "mm"
    coordinate_frame: Literal["program"] = "program"
    moves: tuple[ToolpathMove, ...] = Field(min_length=1, max_length=MAX_TOOLPATH_MOVES)
    deposition_bounds: ToolpathBounds | None
    warnings: tuple[str, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def validate_toolpath(self) -> ToolpathModel:
        if tuple(move.move_index for move in self.moves) != tuple(range(len(self.moves))):
            raise ValueError("toolpath move indices must be contiguous and zero-based")
        if any(
            current.source_line <= previous.source_line
            for previous, current in zip(self.moves, self.moves[1:])
        ):
            raise ValueError("toolpath moves must preserve source-line order")
        expected_bounds = _bounds_for_moves(
            [move for move in self.moves if move.kind == "deposition"]
        )
        if self.deposition_bounds != expected_bounds:
            raise ValueError("deposition bounds must match the deposition moves")
        return self


def parse_toolpath(source_bytes: bytes) -> ToolpathModel:
    """Parse supported linear FDM moves from the exact original G-code bytes.

    XYZ coordinates, feed rate, and commanded filament travel are normalized to
    millimeters. Curved moves and coordinate transforms that cannot be resolved
    from the source are rejected instead of approximated as straight segments.
    """
    if not isinstance(source_bytes, bytes):
        raise TypeError("G-code source must be bytes")
    if not source_bytes:
        raise ValueError("G-code source is empty")
    if len(source_bytes) > MAX_TOOLPATH_BYTES:
        raise ValueError(f"G-code source exceeds {MAX_TOOLPATH_BYTES // (1024 * 1024)} MB")
    try:
        source_text = source_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("G-code source must be UTF-8 encoded") from error
    if not source_text.strip():
        raise ValueError("G-code source is empty")

    scale_mm = 1.0
    absolute_xyz = True
    absolute_extrusion = True
    feed_rate_mm_min: float | None = None
    tool_index = 0
    motion_command: int | None = None
    current_position = [0.0, 0.0, 0.0]
    coordinate_offset = [0.0, 0.0, 0.0]
    extrusion_position: dict[int, float] = {tool_index: 0.0}
    layer_index: int | None = None
    moves: list[ToolpathMove] = []
    warnings: list[str] = []
    saw_home = False

    try:
        parsed_lines = parse_gcode_lines(source_text, include_comments=True)
        for fallback_index, line in enumerate(parsed_lines):
            source_line = int(getattr(line, "line_index", fallback_index)) + 1
            comment = str(getattr(line, "comment", "") or "")
            layer_match = _LAYER_INDEX.search(comment)
            if layer_match:
                layer_index = int(layer_match.group(1))
            elif "LAYER_CHANGE" in comment.upper():
                layer_index = 0 if layer_index is None else layer_index + 1

            parameters = {
                str(key).upper(): value
                for key, value in (getattr(line, "params", {}) or {}).items()
            }
            command = getattr(line, "command", None)
            if command and len(command) == 2 and command[1] is not None:
                command_kind, raw_number = command
                command_kind = str(command_kind).upper()
                command_number: int | None = _command_number(raw_number, source_line)
            else:
                command_kind = ""
                command_number = None

            if command_kind == "T":
                if command_number < 0:
                    raise ValueError(f"line {source_line}: tool index cannot be negative")
                tool_index = command_number
                extrusion_position.setdefault(tool_index, 0.0)
                continue

            if command_kind == "M":
                if command_number == 82:
                    absolute_extrusion = True
                elif command_number == 83:
                    absolute_extrusion = False
                elif command_number == 200 and _number(parameters, "D", source_line, 0.0) > 0:
                    raise ValueError(
                        f"line {source_line}: volumetric extrusion (M200) is unsupported"
                    )
                elif command_number == 420 and _number(parameters, "S", source_line, 0.0) > 0:
                    raise ValueError(
                        f"line {source_line}: active bed-mesh compensation (M420) is unsupported"
                    )
                elif command_number == 221:
                    warnings.append(
                        f"line {source_line}: flow override is not applied to commanded extrusion"
                    )
                continue

            if command_kind != "G":
                if command_kind:
                    continue
                if set(parameters).intersection({"X", "Y", "Z", "E"}):
                    if motion_command is None:
                        raise ValueError(
                            f"line {source_line}: coordinate words have no active G0/G1 motion mode"
                        )
                    command_kind = "G"
                    command_number = motion_command
                elif "F" in parameters:
                    feed_value = _number(parameters, "F", source_line)
                    if feed_value is not None:
                        if feed_value <= 0:
                            raise ValueError(f"line {source_line}: feed rate must be positive")
                        feed_rate_mm_min = feed_value * scale_mm
                    continue
                else:
                    continue

            if command_number is None:
                raise ValueError(f"line {source_line}: G-code command number is missing")

            if command_number == 20:
                scale_mm = 25.4
                continue
            if command_number == 21:
                scale_mm = 1.0
                continue
            if command_number == 90:
                absolute_xyz = True
                continue
            if command_number == 91:
                absolute_xyz = False
                continue
            if command_number in {93, 95}:
                raise ValueError(
                    f"line {source_line}: inverse-time or per-revolution feed modes are unsupported"
                )
            if command_number == 92:
                for axis, axis_index in (("X", 0), ("Y", 1), ("Z", 2)):
                    value = _number(parameters, axis, source_line)
                    if value is not None:
                        coordinate_offset[axis_index] = current_position[axis_index] - (
                            value * scale_mm
                        )
                extrusion_value = _number(parameters, "E", source_line)
                if extrusion_value is not None:
                    extrusion_position[tool_index] = extrusion_value * scale_mm
                continue
            if command_number == 28:
                if not saw_home:
                    warnings.append(
                        f"line {source_line}: homing origin is unknown; "
                        "coordinates remain in program frame"
                    )
                    saw_home = True
                continue
            if command_number in {2, 3}:
                raise ValueError(f"line {source_line}: G{command_number} arc moves are unsupported")
            if command_number in {
                29,
                43,
                49,
                50,
                51,
                52,
                53,
                54,
                55,
                56,
                57,
                58,
                59,
                68,
                69,
            }:
                raise ValueError(
                    f"line {source_line}: G{command_number} bed, tool, or work-coordinate "
                    "transform is unsupported"
                )
            if command_number in {10, 11}:
                raise ValueError(
                    f"line {source_line}: firmware retract moves G{command_number} are unsupported"
                )
            if command_number not in {0, 1}:
                if set(parameters).intersection({"X", "Y", "Z", "E"}):
                    raise ValueError(
                        f"line {source_line}: G{command_number} changes coordinates "
                        "in an unsupported way"
                    )
                continue
            motion_command = command_number

            unknown_axes = set(parameters).intersection(
                {"A", "B", "C", "U", "V", "W", "I", "J", "K", "R"}
            )
            if unknown_axes:
                axes = ", ".join(sorted(unknown_axes))
                raise ValueError(f"line {source_line}: unsupported motion axes {axes}")

            feed_value = _number(parameters, "F", source_line)
            if feed_value is not None:
                if feed_value <= 0:
                    raise ValueError(f"line {source_line}: feed rate must be positive")
                feed_rate_mm_min = feed_value * scale_mm

            start = current_position.copy()
            target = current_position.copy()
            for axis, axis_index in (("X", 0), ("Y", 1), ("Z", 2)):
                value = _number(parameters, axis, source_line)
                if value is not None:
                    if absolute_xyz:
                        target[axis_index] = value * scale_mm - coordinate_offset[axis_index]
                    else:
                        target[axis_index] += value * scale_mm

            extrusion_value = _number(parameters, "E", source_line)
            extrusion_delta_mm = 0.0
            if extrusion_value is not None:
                extrusion_value *= scale_mm
                previous_extrusion = extrusion_position.get(tool_index, 0.0)
                if absolute_extrusion:
                    extrusion_delta_mm = extrusion_value - previous_extrusion
                    extrusion_position[tool_index] = extrusion_value
                else:
                    extrusion_delta_mm = extrusion_value
                    extrusion_position[tool_index] = previous_extrusion + extrusion_value

            delta = [target[index] - start[index] for index in range(3)]
            path_length_mm = math.sqrt(sum(component * component for component in delta))
            current_position = target
            if path_length_mm <= _EPSILON_MM:
                if extrusion_delta_mm > _EPSILON_MM:
                    warnings.append(
                        f"line {source_line}: positive extrusion without spatial travel "
                        "was omitted from raster geometry"
                    )
                continue
            if len(moves) >= MAX_TOOLPATH_MOVES:
                raise ValueError(
                    f"G-code contains more than {MAX_TOOLPATH_MOVES} spatial moves"
                )

            direction = tuple(component / path_length_mm for component in delta)
            xy_length = math.hypot(delta[0], delta[1])
            raster_angle = (
                math.degrees(math.atan2(delta[1], delta[0])) % 180.0
                if xy_length > _EPSILON_MM
                else None
            )
            moves.append(
                ToolpathMove(
                    move_index=len(moves),
                    source_line=source_line,
                    layer_index=layer_index,
                    tool_index=tool_index,
                    kind="deposition"
                    if extrusion_delta_mm > _EPSILON_MM
                    else "travel",
                    start=ToolpathPoint(x_mm=start[0], y_mm=start[1], z_mm=start[2]),
                    end=ToolpathPoint(x_mm=target[0], y_mm=target[1], z_mm=target[2]),
                    path_length_mm=path_length_mm,
                    extrusion_delta_mm=extrusion_delta_mm,
                    feed_rate_mm_min=feed_rate_mm_min,
                    direction=direction,
                    raster_angle_deg=raster_angle,
                )
            )
    except (TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("line "):
            raise
        raise ValueError(f"Could not parse G-code toolpath: {error}") from error

    if not moves:
        raise ValueError("G-code contains no supported spatial moves")

    deposition_moves = [move for move in moves if move.kind == "deposition"]
    bounds = _bounds_for_moves(deposition_moves)
    return ToolpathModel(
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        source_size_bytes=len(source_bytes),
        parser_version=importlib.metadata.version("gcodeparser"),
        moves=tuple(moves),
        deposition_bounds=bounds,
        warnings=tuple(warnings),
    )


def _command_number(value: object, source_line: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"line {source_line}: command number is invalid")
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"line {source_line}: command number is invalid")
    return int(number)


def _number(
    parameters: dict[str, object],
    name: str,
    source_line: int,
    default: float | None = None,
) -> float | None:
    value = parameters.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"line {source_line}: parameter {name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"line {source_line}: parameter {name} must be finite")
    return number


def _bounds_for_moves(moves: list[ToolpathMove]) -> ToolpathBounds | None:
    if not moves:
        return None
    points = [point for move in moves for point in (move.start, move.end)]
    return ToolpathBounds(
        min_x_mm=min(point.x_mm for point in points),
        min_y_mm=min(point.y_mm for point in points),
        min_z_mm=min(point.z_mm for point in points),
        max_x_mm=max(point.x_mm for point in points),
        max_y_mm=max(point.y_mm for point in points),
        max_z_mm=max(point.z_mm for point in points),
    )
