"""Scientific data reduction called only by the isolated stage runtime."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict
from typing import Any

from pydantic import ValidationError

from fdm_strength.gui_analysis import analyze_tensile_rows
from fdm_strength.replicates import (
    CampaignModulus,
    SpecimenModulus,
    aggregate_modulus,
    reduce_tensile_modulus,
)
from fdm_strength.study_models import StudyWorkspaceV3, migrate_workspace_v2_to_v3

MAX_ROW_COUNT = 100_000
MAX_COLUMN_COUNT = 200


def parse_csv_bytes(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Parse the original UTF-8 CSV bytes under the GUI's header/row constraints."""
    if not content:
        raise ValueError("The file is empty. It needs a header row and measurement rows.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("The uploaded CSV must be UTF-8 encoded") from error
    if not text.strip():
        raise ValueError("The file is empty. It needs a header row and measurement rows.")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    parsed = list(csv.reader(io.StringIO(text, newline=""), dialect))
    parsed = [row for row in parsed if any(value.strip() for value in row)]
    if not parsed:
        raise ValueError("Could not find a header row. Add column names to the first row.")
    columns = [value.strip() for value in parsed[0]]
    if not columns or any(not column for column in columns):
        raise ValueError("An empty header is invalid. Name every column in the first row.")
    if len(columns) > MAX_COLUMN_COUNT:
        raise ValueError(f"At most {MAX_COLUMN_COUNT} CSV columns are supported")
    if len(set(columns)) != len(columns):
        raise ValueError("Duplicate CSV headers after trimming are invalid")
    rows: list[dict[str, str]] = []
    for row_number, values in enumerate(parsed[1:], start=2):
        if len(values) > len(columns):
            raise ValueError(
                f"A data row has more values than the CSV header (near row {row_number}). "
                "Check the delimiter and header columns."
            )
        rows.append(
            {
                column: values[index] if index < len(values) else ""
                for index, column in enumerate(columns)
            }
        )
        if len(rows) > MAX_ROW_COUNT:
            raise ValueError(f"At most {MAX_ROW_COUNT:,} rows can be analysed at once")
    if not rows:
        raise ValueError("The file has headers but no measurement rows.")
    return columns, rows


def analyze_uploaded_csv(content: bytes, parameters: dict[str, Any]) -> dict[str, Any]:
    """Analyze CSV source bytes and reduce its specimen modulus in one stage."""
    _, rows = parse_csv_bytes(content)
    analysis = analyze_tensile_rows(rows=rows, **_analysis_parameters(parameters))
    specimen_id = parameters.get("specimen_id")
    if not isinstance(specimen_id, str) or not specimen_id.strip():
        raise ValueError("specimen_id must be provided")
    sensor_source = parameters.get("sensor_source", "unknown")
    correction = parameters.get("compliance_correction", {})
    if not isinstance(correction, dict):
        raise ValueError("compliance_correction must be an object")
    modulus = reduce_tensile_modulus(
        specimen_id,
        analysis["points"],
        gauge_length_mm=parameters["gauge_length_mm"],
        sensor_source=sensor_source,
        compliance_correction=correction,
    )
    return {
        "analysis": {"summary": _summary(analysis), "points": analysis["points"]},
        "specimen_reduction": asdict(modulus),
    }


def reduce_campaign_workspace(
    payload: dict[str, Any],
    upstream_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate immutable specimen reductions into campaign statistics.

    Once a specimen is linked to a formal tensile Run, the editable workspace is
    only the campaign/index document. Numerical campaign values come exclusively
    from the linked Run result artifacts supplied by the runner.
    """
    try:
        normalized = migrate_workspace_v2_to_v3(payload) if payload.get("version") == 2 else payload
        workspace = StudyWorkspaceV3.model_validate(normalized)
    except (ValidationError, ValueError) as error:
        raise ValueError(f"Invalid campaign workspace: {error}") from error
    if not isinstance(upstream_results, dict):
        raise ValueError("campaign upstream results must be an object")

    configurations = {item.id: item for item in workspace.campaign.configurations}
    reductions_by_configuration: dict[str, list[SpecimenModulus]] = {
        configuration_id: [] for configuration_id in configurations
    }
    referenced_run_ids: set[str] = set()
    for specimen in workspace.specimens:
        primary = next((run for run in specimen.test_runs if run.primary_for_reduction), None)
        if primary is None:
            reduction = SpecimenModulus(
                specimen_id=specimen.id,
                modulus_mpa=None,
                status="ineligible",
                reason="No primary test run is selected for reduction.",
            )
        elif primary.run_id is None:
            reduction = SpecimenModulus(
                specimen_id=specimen.id,
                modulus_mpa=None,
                status="ineligible",
                reason="Primary test run is not linked to an immutable tensile Run.",
            )
        else:
            referenced_run_ids.add(primary.run_id)
            immutable_result = upstream_results.get(primary.run_id)
            if immutable_result is None:
                raise ValueError(
                    f"immutable result for linked tensile Run {primary.run_id} is missing"
                )
            reduction = _specimen_modulus_from_immutable_result(
                specimen.id,
                primary.run_id,
                immutable_result,
            )
        reductions_by_configuration[specimen.configuration_id].append(reduction)

    unexpected = set(upstream_results) - referenced_run_ids
    if unexpected:
        raise ValueError(
            "campaign received immutable results for unreferenced Runs: "
            + ", ".join(sorted(unexpected))
        )

    summaries = []
    for configuration_id, configuration in configurations.items():
        reductions = reductions_by_configuration[configuration_id]
        aggregate: CampaignModulus = aggregate_modulus(reductions)
        aggregate_payload = asdict(aggregate)
        # Keep schema-v1 consumers readable while the canonical name changes.
        aggregate_payload["ready_for_validation"] = aggregate.replicate_ready
        summaries.append(
            {
                "configuration_id": configuration_id,
                "configuration_label": configuration.label,
                "specimen_reductions": [asdict(reduction) for reduction in reductions],
                "aggregate": aggregate_payload,
            }
        )
    return {"campaign_name": workspace.campaign.name, "configurations": summaries}


def _specimen_modulus_from_immutable_result(
    specimen_id: str,
    run_id: str,
    immutable_result: dict[str, Any],
) -> SpecimenModulus:
    if not isinstance(immutable_result, dict):
        raise ValueError(f"linked Run {run_id} result must be an object")
    raw = immutable_result.get("specimen_reduction")
    if not isinstance(raw, dict):
        raise ValueError(f"linked Run {run_id} omitted specimen_reduction")
    if raw.get("specimen_id") != specimen_id:
        raise ValueError(
            f"linked Run {run_id} specimen reduction belongs to a different specimen"
        )
    interval = raw.get("strain_interval", (0.0005, 0.0025))
    if (
        not isinstance(interval, (list, tuple))
        or len(interval) != 2
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in interval)
    ):
        raise ValueError(f"linked Run {run_id} has an invalid strain interval")
    status = raw.get("status")
    if status not in {"eligible", "ineligible"}:
        raise ValueError(f"linked Run {run_id} has an invalid specimen reduction status")
    modulus = raw.get("modulus_mpa")
    if modulus is not None and (
        isinstance(modulus, bool) or not isinstance(modulus, (int, float))
    ):
        raise ValueError(f"linked Run {run_id} has an invalid modulus")
    return SpecimenModulus(
        specimen_id=specimen_id,
        modulus_mpa=float(modulus) if modulus is not None else None,
        status=status,
        reason=raw.get("reason") if isinstance(raw.get("reason"), str) else None,
        strain_interval=(float(interval[0]), float(interval[1])),
        sensor_source=str(raw.get("sensor_source", "unknown")),
        correction_method=str(raw.get("correction_method", "unknown")),
    )


def _analysis_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    names = (
        "force_column",
        "displacement_column",
        "width_mm",
        "thickness_mm",
        "gauge_length_mm",
        "force_unit",
        "displacement_unit",
        "decimal_separator",
        "tension_direction",
    )
    missing = [name for name in names[:5] if name not in parameters]
    if missing:
        raise ValueError(f"Missing required analysis settings: {', '.join(missing)}")
    return {name: parameters[name] for name in names if name in parameters}


def _summary(analysis: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in analysis.items() if key != "points"}
