"""Immutable input and reference models for the formal isotropic FEM stages."""

from __future__ import annotations

import hashlib
import json
import re
from math import isfinite
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdm_strength.specimen_catalog import REFERENCE_STANDARD, d638_definition

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RectangularTensileSpecimen(FrozenModel):
    """Rectangular gauge section in the specimen's x-y-z coordinate frame."""

    specimen_id: str = Field(min_length=1, max_length=128)
    length_mm: float = Field(gt=0, le=1000)
    width_mm: float = Field(gt=0, le=500)
    thickness_mm: float = Field(gt=0, le=100)

    @field_validator("specimen_id")
    @classmethod
    def validate_specimen_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("specimen_id must be a safe identifier")
        return value

    @model_validator(mode="after")
    def require_tensile_proportions(self) -> RectangularTensileSpecimen:
        if self.length_mm <= self.width_mm:
            raise ValueError("length must exceed width for the rectangular tensile fixture")
        if self.width_mm < self.thickness_mm:
            raise ValueError("width must be at least the specimen thickness")
        return self


class D638TensileSpecimen(FrozenModel):
    """Checked ASTM D638 Type I/IV/V geometry with a measured test thickness."""

    specimen_id: str = Field(min_length=1, max_length=128)
    standard_revision: Literal["ASTM D638-22"] = REFERENCE_STANDARD
    specimen_type: Literal["I", "IV", "V"]
    thickness_mm: float = Field(gt=0, le=100)

    @field_validator("specimen_id")
    @classmethod
    def validate_specimen_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("specimen_id must be a safe identifier")
        return value


class IsotropicMaterialProfile(FrozenModel):
    """Linear-elastic isotropic constants, with modulus in MPa."""

    profile_id: str = Field(min_length=1, max_length=128)
    youngs_modulus_mpa: float = Field(gt=0, le=1_000_000)
    poissons_ratio: float = Field(gt=-1, lt=0.5)

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("profile_id must be a safe identifier")
        return value


class TensileLoad(FrozenModel):
    """Positive axial force in newtons; the fixture prescribes its equivalent extension."""

    force_n: float = Field(gt=0, le=1_000_000_000)


class BoundaryConditionSet(FrozenModel):
    """Named, explicit kinematic strategy used by the rectangular tensile fixture."""

    set_id: str = Field(min_length=1, max_length=128)
    axial_axis: Literal["x"] = "x"
    fixed_axial_face: Literal["x_min"] = "x_min"
    prescribed_axial_face: Literal["x_max"] = "x_max"
    transverse_rigid_mode_control: Literal["3d_minimal_rigid_mode_pins"] = (
        "3d_minimal_rigid_mode_pins"
    )
    unloaded_faces: Literal["traction_free"] = "traction_free"

    @field_validator("set_id")
    @classmethod
    def validate_set_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("set_id must be a safe identifier")
        return value


class D638BoundaryConditionSet(FrozenModel):
    """End-face load model for the full ASTM D638 dog-bone geometry."""

    set_id: str = Field(min_length=1, max_length=128)
    axial_axis: Literal["x"] = "x"
    fixed_axial_face: Literal["x_min"] = "x_min"
    loaded_face: Literal["x_max"] = "x_max"
    load_control: Literal["uniform_end_traction"] = "uniform_end_traction"
    transverse_rigid_mode_control: Literal["3d_minimal_rigid_mode_pins"] = (
        "3d_minimal_rigid_mode_pins"
    )
    unloaded_faces: Literal["traction_free"] = "traction_free"

    @field_validator("set_id")
    @classmethod
    def validate_set_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("set_id must be a safe identifier")
        return value


class GmshMeshSettings(FrozenModel):
    """Deterministic first-pass tetrahedral mesh controls."""

    max_cell_size_mm: float = Field(gt=0, le=100)
    element_order: Literal[1, 2] = 1
    optimize: bool = True


class IsotropicTensileRequest(FrozenModel):
    """Complete immutable input to the `fdm-l2-isotropic` tensile stage."""

    schema_version: Literal[1] = 1
    specimen: RectangularTensileSpecimen
    material: IsotropicMaterialProfile
    load: TensileLoad
    boundary_conditions: BoundaryConditionSet
    mesh: GmshMeshSettings


class D638IsotropicTensileRequest(FrozenModel):
    """Immutable input for a full ASTM D638 Type I, IV, or V isotropic solve."""

    schema_version: Literal[2] = 2
    specimen: D638TensileSpecimen
    material: IsotropicMaterialProfile
    load: TensileLoad
    boundary_conditions: D638BoundaryConditionSet
    mesh: GmshMeshSettings


AnyIsotropicTensileRequest: TypeAlias = IsotropicTensileRequest | D638IsotropicTensileRequest


def parse_isotropic_tensile_request(content: bytes | str) -> AnyIsotropicTensileRequest:
    """Parse a FEM request while retaining schema-v1 replay compatibility."""

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("FEM request is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("FEM request must be a JSON object")
    if payload.get("schema_version") == 1:
        return IsotropicTensileRequest.model_validate(payload)
    if payload.get("schema_version") == 2:
        return D638IsotropicTensileRequest.model_validate(payload)
    raise ValueError("unsupported isotropic FEM request schema_version")


class AnalyticalTensileResponse(FrozenModel):
    cross_section_area_mm2: float = Field(gt=0)
    nominal_stress_mpa: float = Field(gt=0)
    nominal_strain: float = Field(gt=0)
    axial_displacement_mm: float = Field(gt=0)
    reaction_force_n: float = Field(gt=0)


def analytical_tensile_response(
    request: AnyIsotropicTensileRequest,
) -> AnalyticalTensileResponse:
    """Return the nominal uniaxial Hookean reference response in mm/N/MPa units.

    For schema v1 the reference span is the full rectangular coupon. For ASTM
    D638 schema v2 the nominal stress uses the narrow section and the reference
    extension uses the ASTM gauge length. The full dog-bone FEM solve itself
    does not assume constant area.
    """

    if isinstance(request, D638IsotropicTensileRequest):
        definition = d638_definition(request.specimen.specimen_type)
        area = definition.gauge_width_mm * request.specimen.thickness_mm
        reference_length = definition.gauge_length_mm
    else:
        area = request.specimen.width_mm * request.specimen.thickness_mm
        reference_length = request.specimen.length_mm
    stress = request.load.force_n / area
    strain = stress / request.material.youngs_modulus_mpa
    extension = strain * reference_length
    return AnalyticalTensileResponse(
        cross_section_area_mm2=area,
        nominal_stress_mpa=stress,
        nominal_strain=strain,
        axial_displacement_mm=extension,
        reaction_force_n=request.load.force_n,
    )


def isotropic_lame_parameters(
    youngs_modulus_mpa: float, poissons_ratio: float
) -> tuple[float, float]:
    """Return Lamé's first parameter and shear modulus for a stable isotropic solid."""
    if (
        isinstance(youngs_modulus_mpa, bool)
        or isinstance(poissons_ratio, bool)
        or not isinstance(youngs_modulus_mpa, (int, float))
        or not isinstance(poissons_ratio, (int, float))
        or not isfinite(youngs_modulus_mpa)
        or not isfinite(poissons_ratio)
        or youngs_modulus_mpa <= 0
    ):
        raise ValueError("Young's modulus must be positive and both inputs must be finite numbers")
    if not -1.0 < poissons_ratio < 0.5:
        raise ValueError("Poisson's ratio must describe a stable isotropic material")
    mu = youngs_modulus_mpa / (2.0 * (1.0 + poissons_ratio))
    lame_lambda = (
        youngs_modulus_mpa
        * poissons_ratio
        / ((1.0 + poissons_ratio) * (1.0 - 2.0 * poissons_ratio))
    )
    return lame_lambda, mu


def canonical_json_bytes(model: BaseModel) -> bytes:
    """Encode an immutable input using the same canonical JSON conventions as stage contracts."""
    return (
        json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def model_sha256(model: BaseModel) -> str:
    """Return the SHA-256 digest for canonical model bytes."""
    return hashlib.sha256(canonical_json_bytes(model)).hexdigest()
