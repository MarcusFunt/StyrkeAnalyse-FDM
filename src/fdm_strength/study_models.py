"""Validated, versioned campaign and specimen records for saved studies."""

from __future__ import annotations

import math
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, StrictStr, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SensorSource(str, Enum):
    UNKNOWN = "unknown"
    EXTENSOMETER = "extensometer"
    CROSSHEAD = "crosshead"
    CLIP_GAUGE = "clip_gauge"
    DIC = "dic"
    OTHER = "other"


class Geometry(StrictModel):
    width_mm: PositiveFloat | None = Field(default=None, strict=True)
    thickness_mm: PositiveFloat | None = Field(default=None, strict=True)
    gauge_length_mm: PositiveFloat | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def dimensions_are_finite(self) -> Geometry:
        if any(
            value is not None and not math.isfinite(value)
            for value in (self.width_mm, self.thickness_mm, self.gauge_length_mm)
        ):
            raise ValueError("specimen dimensions must be finite")
        return self


class PrintMetadata(StrictModel):
    material: str | None = Field(default=None, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=120)
    material_lot: str | None = Field(default=None, max_length=120)
    printer: str | None = Field(default=None, max_length=120)
    nozzle: str | None = Field(default=None, max_length=120)
    nozzle_diameter_mm: PositiveFloat | None = Field(default=None, strict=True)
    layer_height_mm: PositiveFloat | None = Field(default=None, strict=True)
    raster_orientation: str | None = Field(default=None, max_length=120)
    infill_percent: float | None = Field(default=None, ge=0, le=100, strict=True)
    nozzle_temperature_c: float | None = Field(default=None, strict=True)
    bed_temperature_c: float | None = Field(default=None, strict=True)
    print_date: date | None = None
    gcode_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def finite_process_values(self) -> PrintMetadata:
        if any(
            not math.isfinite(value)
            for value in self.model_dump().values()
            if isinstance(value, float)
        ):
            raise ValueError("print metadata numeric values must be finite")
        return self


class Configuration(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    material: str | None = Field(default=None, max_length=120)
    material_lot: str | None = Field(default=None, max_length=120)
    print_profile: str | None = Field(default=None, max_length=120)
    orientation: str | None = Field(default=None, max_length=120)


class Campaign(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)
    configurations: list[Configuration] = Field(min_length=1, max_length=500)
    created_at: datetime | None = None

    @model_validator(mode="after")
    def unique_configuration_ids(self) -> Campaign:
        ids = [configuration.id for configuration in self.configurations]
        if len(set(ids)) != len(ids):
            raise ValueError("campaign configuration IDs must be unique")
        if self.created_at is not None and self.created_at.utcoffset() is None:
            raise ValueError("campaign created_at must include a timezone")
        return self


class ComplianceCorrection(StrictModel):
    method: Literal["unknown", "not_required", "machine_compliance", "other"]
    compliance_mm_per_n: PositiveFloat | None = Field(default=None, strict=True)
    calibration_source: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def machine_correction_has_calibration(self) -> ComplianceCorrection:
        if self.compliance_mm_per_n is not None and not math.isfinite(self.compliance_mm_per_n):
            raise ValueError("compliance value must be finite")
        if self.method == "machine_compliance" and (
            self.compliance_mm_per_n is None or not self.calibration_source
        ):
            raise ValueError(
                "machine-compliance correction requires a positive compliance value "
                "and calibration source"
            )
        if self.method != "machine_compliance" and self.compliance_mm_per_n is not None:
            raise ValueError("compliance value is only valid for machine-compliance correction")
        return self


class InputFileProvenance(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    media_type: str | None = Field(default=None, max_length=120)
    size_bytes: int | None = Field(default=None, ge=0, strict=True)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    imported_at: datetime | None = None
    status: Literal["verified", "unavailable_legacy"]

    @model_validator(mode="after")
    def provenance_is_consistent(self) -> InputFileProvenance:
        verified_fields = (self.size_bytes, self.sha256, self.imported_at)
        if self.status == "verified" and any(value is None for value in verified_fields):
            raise ValueError("verified input provenance requires size, SHA-256, and import time")
        if self.status == "unavailable_legacy" and any(
            value is not None for value in verified_fields
        ):
            raise ValueError(
                "legacy input provenance must not claim unverified size, hash, or import time"
            )
        if self.imported_at is not None and self.imported_at.utcoffset() is None:
            raise ValueError("imported_at must include a timezone")
        return self


class AnalysisPoint(StrictModel):
    row_number: int = Field(ge=1, strict=True)
    force_n: float = Field(strict=True)
    displacement_mm: float = Field(strict=True)
    extension_mm: float = Field(strict=True)
    strain: float = Field(strict=True)
    stress_mpa: float = Field(strict=True)

    @model_validator(mode="after")
    def finite_values(self) -> AnalysisPoint:
        if any(
            not math.isfinite(value)
            for value in self.model_dump().values()
            if isinstance(value, float)
        ):
            raise ValueError("analysis point values must be finite")
        return self


class AnalysisSummary(StrictModel):
    sample_count: int = Field(ge=1, strict=True)
    cross_section_area_mm2: PositiveFloat = Field(strict=True)
    gauge_length_mm: PositiveFloat = Field(strict=True)
    peak_force_n: float = Field(ge=0, strict=True)
    peak_force_row: int = Field(ge=1, strict=True)
    peak_stress_mpa: float = Field(ge=0, strict=True)
    peak_stress_row: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def finite_values(self) -> AnalysisSummary:
        if any(
            not math.isfinite(value)
            for value in self.model_dump().values()
            if isinstance(value, float)
        ):
            raise ValueError("analysis summary values must be finite")
        if self.peak_force_row > self.sample_count or self.peak_stress_row > self.sample_count:
            raise ValueError("analysis peak row must be within the sample count")
        return self


class TensileAnalysisResult(StrictModel):
    summary: AnalysisSummary
    points: list[AnalysisPoint] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def point_count_matches_summary(self) -> TensileAnalysisResult:
        if len(self.points) != self.summary.sample_count:
            raise ValueError("analysis point count must match summary sample_count")
        if [point.row_number for point in self.points] != list(range(1, len(self.points) + 1)):
            raise ValueError("analysis point row numbers must be sequential")
        return self


def _finite_scalar(value: Any) -> bool:
    return (
        value is None
        or isinstance(value, (str, bool, int))
        or (isinstance(value, float) and math.isfinite(value))
    )


class TestRun(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    primary_for_reduction: bool = Field(default=True, strict=True)
    analysis_time: datetime | None = None
    test_date: date | None = None
    test_standard: str | None = Field(default=None, max_length=200)
    operator: str | None = Field(default=None, max_length=120)
    machine: str | None = Field(default=None, max_length=120)
    load_cell: str | None = Field(default=None, max_length=120)
    sensor_source: SensorSource
    sensor_source_description: str | None = Field(default=None, max_length=500)
    compliance_correction: ComplianceCorrection
    input_file: InputFileProvenance
    columns: list[StrictStr] = Field(min_length=1, max_length=200)
    rows: list[dict[StrictStr, StrictStr]] = Field(min_length=1, max_length=100_000)
    settings: dict[str, Any] = Field(default_factory=dict)
    result: TensileAnalysisResult | None = None

    @model_validator(mode="after")
    def run_data_is_consistent(self) -> TestRun:
        if self.analysis_time is not None and self.analysis_time.utcoffset() is None:
            raise ValueError("analysis_time must include a timezone")
        if self.sensor_source == SensorSource.OTHER and not self.sensor_source_description:
            raise ValueError("other sensor source requires a description")
        if any(not column or column != column.strip() for column in self.columns):
            raise ValueError("test columns must be non-empty and trimmed")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("test columns must be unique")
        if any(
            not key or any(not _finite_scalar(value) for value in row.values())
            for row in self.rows
            for key in row
        ):
            raise ValueError("test rows must contain finite scalar values with named columns")
        expected_columns = set(self.columns)
        if any(set(row) != expected_columns for row in self.rows):
            raise ValueError("each test row must contain exactly the named test columns")
        if any(not key or not _finite_scalar(value) for key, value in self.settings.items()):
            raise ValueError("test settings must contain finite scalar values")
        if self.result is not None and self.result.summary.sample_count != len(self.rows):
            raise ValueError("analysis result sample count must match test row count")
        return self


class Specimen(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    configuration_id: str = Field(min_length=1, max_length=120)
    geometry: Geometry
    print_metadata: PrintMetadata
    test_runs: list[TestRun] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def at_most_one_primary_run(self) -> Specimen:
        if sum(run.primary_for_reduction for run in self.test_runs) > 1:
            raise ValueError("a specimen may have at most one primary test run for reduction")
        for run in self.test_runs:
            if run.result is None:
                continue
            geometry = self.geometry
            summary = run.result.summary
            if (
                geometry.width_mm is not None
                and geometry.thickness_mm is not None
                and not math.isclose(
                    summary.cross_section_area_mm2,
                    geometry.width_mm * geometry.thickness_mm,
                    rel_tol=1e-9,
                )
            ) or (
                geometry.gauge_length_mm is not None
                and not math.isclose(
                    summary.gauge_length_mm,
                    geometry.gauge_length_mm,
                    rel_tol=1e-9,
                )
            ):
                raise ValueError("analysis result dimensions do not match the specimen geometry")
        return self


class StudyWorkspaceV2(StrictModel):
    format: Literal["styrkeanalyse-fdm-study"]
    version: Literal[2]
    id: str | None = None
    revision: int | None = Field(default=None, ge=1, strict=True)
    saved_at: datetime | None = None
    deleted_at: datetime | None = None
    study_name: str = Field(min_length=1, max_length=200)
    campaign: Campaign
    specimens: list[Specimen] = Field(min_length=1, max_length=5_000)

    @model_validator(mode="after")
    def workspace_references_are_valid(self) -> StudyWorkspaceV2:
        if any(
            value is not None and value.utcoffset() is None
            for value in (self.saved_at, self.deleted_at)
        ):
            raise ValueError("workspace timestamps must include a timezone")
        configurations = {configuration.id for configuration in self.campaign.configurations}
        specimen_ids = [specimen.id for specimen in self.specimens]
        run_ids = [run.id for specimen in self.specimens for run in specimen.test_runs]
        if len(set(specimen_ids)) != len(specimen_ids):
            raise ValueError("campaign specimen IDs must be unique")
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("test run IDs must be unique within the campaign")
        if any(specimen.configuration_id not in configurations for specimen in self.specimens):
            raise ValueError("every specimen must reference a campaign configuration")
        return self
