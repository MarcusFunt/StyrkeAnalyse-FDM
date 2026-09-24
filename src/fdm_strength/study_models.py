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
    printer: str | None = Field(default=None, max_length=120)
    print_profile: str | None = Field(default=None, max_length=120)
    nozzle: str | None = Field(default=None, max_length=120)
    nozzle_diameter_mm: PositiveFloat | None = Field(default=None, strict=True)
    layer_height_mm: PositiveFloat | None = Field(default=None, strict=True)
    orientation: str | None = Field(default=None, max_length=120)
    build_orientation: str | None = Field(default=None, max_length=120)
    raster_strategy: str | None = Field(default=None, max_length=120)
    infill_percent: float | None = Field(default=None, ge=0, le=100, strict=True)
    nozzle_temperature_c: float | None = Field(default=None, strict=True)
    bed_temperature_c: float | None = Field(default=None, strict=True)
    nominal_geometry: Geometry | None = None
    test_type: str | None = Field(default=None, max_length=120)
    test_standard_revision: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def controlled_values_are_finite(self) -> Configuration:
        if any(
            value is not None and not math.isfinite(value)
            for value in (
                self.nozzle_diameter_mm,
                self.layer_height_mm,
                self.infill_percent,
                self.nozzle_temperature_c,
                self.bed_temperature_c,
            )
        ):
            raise ValueError("configuration process values must be finite")
        if (
            self.orientation
            and self.build_orientation
            and self.orientation != self.build_orientation
        ):
            raise ValueError("legacy orientation and build_orientation must agree")
        return self


class Campaign(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    reduction_run_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
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
    run_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    primary_for_reduction: bool = Field(default=True, strict=True)
    analysis_time: datetime | None = None
    test_date: date | None = None
    test_type: str | None = Field(default=None, max_length=120)
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
        if self.result is not None and self.test_type not in (None, "tensile"):
            raise ValueError("tensile analysis results require a tensile test type")
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
        configurations = {
            configuration.id: configuration for configuration in self.campaign.configurations
        }
        specimen_ids = [specimen.id for specimen in self.specimens]
        run_ids = [run.id for specimen in self.specimens for run in specimen.test_runs]
        formal_run_ids = [
            run.run_id
            for specimen in self.specimens
            for run in specimen.test_runs
            if run.run_id is not None
        ]
        if len(set(specimen_ids)) != len(specimen_ids):
            raise ValueError("campaign specimen IDs must be unique")
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("test run IDs must be unique within the campaign")
        if len(set(formal_run_ids)) != len(formal_run_ids):
            raise ValueError("formal Run IDs must be unique within the campaign")
        if any(specimen.configuration_id not in configurations for specimen in self.specimens):
            raise ValueError("every specimen must reference a campaign configuration")
        specimens_by_configuration: dict[str, list[Specimen]] = {
            configuration_id: [] for configuration_id in configurations
        }
        for specimen in self.specimens:
            specimens_by_configuration[specimen.configuration_id].append(specimen)

        specimen_field_by_control = {
            "material": "material",
            "material_lot": "material_lot",
            "printer": "printer",
            "nozzle": "nozzle",
            "nozzle_diameter_mm": "nozzle_diameter_mm",
            "layer_height_mm": "layer_height_mm",
            "raster_strategy": "raster_orientation",
            "infill_percent": "infill_percent",
            "nozzle_temperature_c": "nozzle_temperature_c",
            "bed_temperature_c": "bed_temperature_c",
        }
        for configuration_id, group in specimens_by_configuration.items():
            configuration = configurations[configuration_id]
            for control, specimen_field in specimen_field_by_control.items():
                configured = getattr(configuration, control)
                observed = {
                    value
                    for specimen in group
                    if (value := getattr(specimen.print_metadata, specimen_field)) not in (None, "")
                }
                if configured is not None:
                    if any(value != configured for value in observed):
                        raise ValueError(
                            "specimen print metadata conflicts with configuration "
                            f"{configuration_id} field {control}"
                        )
                elif len(observed) > 1:
                    raise ValueError(
                        f"specimens with incompatible {control} values cannot share configuration "
                        f"{configuration_id}"
                    )

            raster_values = {
                value
                for specimen in group
                if (value := specimen.print_metadata.raster_orientation) not in (None, "")
            }
            legacy_raster = configuration.orientation
            raster_control = configuration.raster_strategy
            if (
                legacy_raster is not None
                and raster_control is not None
                and legacy_raster != raster_control
            ):
                raise ValueError(
                    f"configuration {configuration_id} has conflicting legacy orientation "
                    "and raster_strategy"
                )
            configured_raster = raster_control or legacy_raster
            if configured_raster is not None and any(
                value != configured_raster for value in raster_values
            ):
                raise ValueError(
                    f"specimen print metadata conflicts with configuration {configuration_id} "
                    "field raster_strategy"
                )
            if configured_raster is None and len(raster_values) > 1:
                raise ValueError(
                    "specimens with incompatible raster_strategy values cannot share configuration "
                    f"{configuration_id}"
                )

            test_standards = {
                run.test_standard
                for specimen in group
                for run in specimen.test_runs
                if run.test_standard
            }
            if configuration.test_standard_revision is not None:
                if any(value != configuration.test_standard_revision for value in test_standards):
                    raise ValueError(
                        f"test run standard conflicts with configuration {configuration_id} "
                        "field test_standard_revision"
                    )
            elif len(test_standards) > 1:
                raise ValueError(
                    f"specimens with incompatible test standards cannot share configuration "
                    f"{configuration_id}"
                )

            test_types = {
                run.test_type for specimen in group for run in specimen.test_runs if run.test_type
            }
            if configuration.test_type is not None:
                if any(value != configuration.test_type for value in test_types):
                    raise ValueError(
                        f"test run type conflicts with configuration {configuration_id} "
                        "field test_type"
                    )
            elif len(test_types) > 1:
                raise ValueError(
                    "specimens with incompatible test types cannot share configuration "
                    f"{configuration_id}"
                )
        return self


class StudyWorkspaceV3(StudyWorkspaceV2):
    """Study schema with controlled print/test conditions owned by Configuration."""

    version: Literal[3]


def migrate_workspace_v2_to_v3(payload: dict[str, Any]) -> dict[str, Any]:
    """Move recorded controlled conditions from specimens into their configuration.

    Values are promoted only when the v2 specimens sharing a configuration agree.
    Missing observations stay unknown; conflicting observations require the user to
    split the specimens into separate configurations before migration can succeed.
    """
    from pydantic import ValidationError

    if payload.get("version") != 2:
        raise ValueError("Only v2 study workspaces can be migrated to v3")
    try:
        workspace = StudyWorkspaceV2.model_validate(payload)
    except ValidationError as error:
        issues = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False)
        ]
        raise ValueError("Invalid v2 study workspace: " + "; ".join(issues)) from error

    migrated = workspace.model_dump(mode="json")
    configurations = {item["id"]: item for item in migrated["campaign"]["configurations"]}
    groups: dict[str, list[dict[str, Any]]] = {
        configuration_id: [] for configuration_id in configurations
    }
    for specimen in migrated["specimens"]:
        groups[specimen["configuration_id"]].append(specimen)

    controls = {
        "material": ("material", "material"),
        "material_lot": ("material_lot", "material_lot"),
        "printer": ("printer", "printer"),
        "nozzle": ("nozzle", "nozzle"),
        "nozzle_diameter_mm": ("nozzle_diameter_mm", "nozzle_diameter_mm"),
        "layer_height_mm": ("layer_height_mm", "layer_height_mm"),
        "infill_percent": ("infill_percent", "infill_percent"),
        "nozzle_temperature_c": ("nozzle_temperature_c", "nozzle_temperature_c"),
        "bed_temperature_c": ("bed_temperature_c", "bed_temperature_c"),
    }
    specimen_control_fields = {source for _, source in controls.values()}
    specimen_control_fields.add("raster_orientation")

    for configuration_id, specimens in groups.items():
        configuration = configurations[configuration_id]
        for target, (_, source) in controls.items():
            observed = {
                specimen["print_metadata"][source]
                for specimen in specimens
                if specimen["print_metadata"][source] not in (None, "")
            }
            configured = configuration.get(target)
            if configured is not None and any(value != configured for value in observed):
                raise ValueError(
                    f"specimen value conflicts with configuration {configuration_id} field {target}"
                )
            if configured is None and len(observed) > 1:
                raise ValueError(
                    f"specimens with incompatible {target} values cannot share configuration "
                    f"{configuration_id}"
                )
            if configured is None and observed:
                configuration[target] = next(iter(observed))

        raster_values = {
            specimen["print_metadata"]["raster_orientation"]
            for specimen in specimens
            if specimen["print_metadata"]["raster_orientation"] not in (None, "")
        }
        configured_raster = configuration.get("raster_strategy") or configuration.get("orientation")
        if configured_raster is not None and any(
            value != configured_raster for value in raster_values
        ):
            raise ValueError(
                f"specimen raster strategy conflicts with configuration {configuration_id}"
            )
        if configured_raster is None and len(raster_values) > 1:
            raise ValueError(
                f"specimens with incompatible raster strategies cannot share configuration "
                f"{configuration_id}"
            )
        if configured_raster is None and raster_values:
            configured_raster = next(iter(raster_values))
        if configured_raster is not None:
            configuration["raster_strategy"] = configured_raster

        standards = {
            run["test_standard"]
            for specimen in specimens
            for run in specimen["test_runs"]
            if run["test_standard"]
        }
        configured_standard = configuration.get("test_standard_revision")
        if configured_standard is not None and any(
            value != configured_standard for value in standards
        ):
            raise ValueError(f"test standard conflicts with configuration {configuration_id}")
        if configured_standard is None and len(standards) > 1:
            raise ValueError(
                f"specimens with incompatible test standards cannot share configuration "
                f"{configuration_id}"
            )
        if configured_standard is None and standards:
            configuration["test_standard_revision"] = next(iter(standards))

        test_types = {
            run["test_type"]
            for specimen in specimens
            for run in specimen["test_runs"]
            if run["test_type"]
        }
        configured_type = configuration.get("test_type")
        if configured_type is not None and any(value != configured_type for value in test_types):
            raise ValueError(f"test type conflicts with configuration {configuration_id}")
        if configured_type is None and len(test_types) > 1:
            raise ValueError(
                "specimens with incompatible test types cannot share configuration "
                f"{configuration_id}"
            )
        if configured_type is None and test_types:
            configuration["test_type"] = next(iter(test_types))

        for specimen in specimens:
            for field in specimen_control_fields:
                specimen["print_metadata"][field] = None

    migrated["version"] = 3
    StudyWorkspaceV3.model_validate(migrated)
    return migrated
