from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

import fdm_strength.study_models as study_models
from fdm_strength.gui_analysis import analyze_tensile_rows
from fdm_strength.study_models import StudyWorkspaceV2


def valid_workspace():
    return {
        "format": "styrkeanalyse-fdm-study",
        "version": 2,
        "study_name": "PLA campaign",
        "campaign": {
            "id": "campaign-1",
            "name": "PLA coupons",
            "configurations": [{"id": "cfg-1", "label": "0/90 baseline"}],
        },
        "specimens": [
            {
                "id": "S01",
                "label": "S01",
                "configuration_id": "cfg-1",
                "geometry": {"width_mm": 10, "thickness_mm": 2, "gauge_length_mm": 50},
                "print_metadata": {
                    "material": "PLA",
                    "material_lot": "lot-23",
                    "printer": "printer-1",
                    "layer_height_mm": 0.2,
                    "raster_orientation": "0/90",
                },
                "test_runs": [
                    {
                        "id": "run-1",
                        "test_date": "2026-09-24",
                        "test_standard": "ASTM D638",
                        "operator": "operator-1",
                        "machine": "UTM-1",
                        "load_cell": "LC-500N",
                        "sensor_source": "extensometer",
                        "compliance_correction": {"method": "not_required"},
                        "input_file": {
                            "filename": "coupon.csv",
                            "media_type": "text/csv",
                            "size_bytes": 128,
                            "sha256": "a" * 64,
                            "imported_at": datetime.now(timezone.utc).isoformat(),
                            "status": "verified",
                        },
                        "columns": ["force_N", "displacement_mm"],
                        "rows": [{"force_N": "10", "displacement_mm": "0.1"}],
                        "settings": {"decimalSeparator": "."},
                        "result": None,
                    }
                ],
            }
        ],
    }


def test_workspace_v2_captures_campaign_specimen_print_test_sensor_and_file_provenance():
    workspace = StudyWorkspaceV2.model_validate(valid_workspace())

    specimen = workspace.specimens[0]
    run = specimen.test_runs[0]
    assert specimen.print_metadata.material_lot == "lot-23"
    assert run.sensor_source == "extensometer"
    assert run.input_file.sha256 == "a" * 64
    assert run.input_file.size_bytes == 128
    assert run.input_file.status == "verified"


def test_test_run_can_link_to_an_immutable_formal_run():
    payload = valid_workspace()
    payload["specimens"][0]["test_runs"][0]["run_id"] = "8e02d8f8-b1ab-4abc-9fe5-2f65173b6704"

    workspace = StudyWorkspaceV2.model_validate(payload)

    assert (
        workspace.specimens[0].test_runs[0].run_id
        == payload["specimens"][0]["test_runs"][0]["run_id"]
    )


def test_workspace_v2_allows_legacy_file_provenance_without_inventing_a_digest():
    payload = valid_workspace()
    input_file = payload["specimens"][0]["test_runs"][0]["input_file"]
    input_file.update(
        {
            "size_bytes": None,
            "sha256": None,
            "imported_at": None,
            "status": "unavailable_legacy",
        }
    )

    parsed = StudyWorkspaceV2.model_validate(payload)
    assert parsed.specimens[0].test_runs[0].input_file.sha256 is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["specimens"][0]["test_runs"][0].update(sensor_source="laser"),
        lambda value: value["specimens"][0]["test_runs"][0]["input_file"].update(sha256="bad"),
        lambda value: value["specimens"][0]["test_runs"][0]["input_file"].update(size_bytes=-1),
        lambda value: value["specimens"][0]["geometry"].update(width_mm=-2),
        lambda value: value["specimens"][0]["geometry"].update(width_mm=float("inf")),
        lambda value: value["specimens"][0]["print_metadata"].update(
            nozzle_temperature_c=float("nan")
        ),
        lambda value: value["specimens"][0]["test_runs"][0].update(
            sensor_source="other", sensor_source_description=None
        ),
        lambda value: value["specimens"][0]["test_runs"][0]["rows"][0].update(
            force_N={"nested": "10"}
        ),
        lambda value: value["specimens"][0]["test_runs"][0]["rows"][0].update(unexpected="20"),
        lambda value: value.update(revision=0),
        lambda value: value.update(unexpected_field=True),
    ],
)
def test_workspace_v2_rejects_malformed_metadata_and_unknown_fields(mutate):
    payload = valid_workspace()
    mutate(payload)

    with pytest.raises(ValidationError):
        StudyWorkspaceV2.model_validate(payload)


def test_workspace_v2_rejects_duplicate_specimen_ids():
    payload = valid_workspace()
    second = {**payload["specimens"][0], "label": "S02"}
    payload["specimens"].append(second)

    with pytest.raises(ValidationError, match="unique"):
        StudyWorkspaceV2.model_validate(payload)


def test_workspace_v2_rejects_duplicate_configuration_ids():
    payload = valid_workspace()
    payload["campaign"]["configurations"].append({"id": "cfg-1", "label": "duplicate"})

    with pytest.raises(ValidationError, match="unique"):
        StudyWorkspaceV2.model_validate(payload)


def test_workspace_v2_rejects_boolean_dimensions_and_physics_values():
    payload = valid_workspace()
    payload["specimens"][0]["geometry"]["width_mm"] = True
    with pytest.raises(ValidationError):
        StudyWorkspaceV2.model_validate(payload)


def test_configuration_defines_controlled_print_conditions_and_checks_specimens():
    payload = valid_workspace()
    payload["campaign"]["configurations"][0].update(
        {
            "material": "PLA",
            "printer": "printer-1",
            "nozzle_diameter_mm": 0.4,
            "layer_height_mm": 0.2,
            "build_orientation": "XY",
            "raster_strategy": "0/90",
            "test_type": "tensile",
            "test_standard_revision": "ASTM D638-22",
        }
    )
    payload["specimens"][0]["test_runs"][0]["test_standard"] = "ASTM D638-22"

    workspace = StudyWorkspaceV2.model_validate(payload)

    assert workspace.campaign.configurations[0].printer == "printer-1"
    assert workspace.campaign.configurations[0].test_standard_revision == "ASTM D638-22"

    payload["specimens"][0]["print_metadata"]["printer"] = "printer-2"
    with pytest.raises(ValidationError, match="configuration"):
        StudyWorkspaceV2.model_validate(payload)


def test_specimens_with_conflicting_legacy_print_conditions_cannot_share_configuration():
    payload = valid_workspace()
    second = {
        **payload["specimens"][0],
        "id": "S02",
        "label": "S02",
        "test_runs": [
            {**payload["specimens"][0]["test_runs"][0], "id": "run-2"},
        ],
        "print_metadata": {**payload["specimens"][0]["print_metadata"], "material": "ABS"},
    }
    payload["specimens"].append(second)

    with pytest.raises(ValidationError, match="configuration"):
        StudyWorkspaceV2.model_validate(payload)


def test_v2_configuration_migration_promotes_only_observed_values():
    payload = valid_workspace()
    migrated = study_models.migrate_workspace_v2_to_v3(payload)

    assert migrated["version"] == 3
    assert migrated["campaign"]["configurations"][0]["material"] == "PLA"
    assert migrated["campaign"]["configurations"][0]["printer"] == "printer-1"
    assert migrated["campaign"]["configurations"][0]["layer_height_mm"] == 0.2
    assert migrated["campaign"]["configurations"][0]["raster_strategy"] == "0/90"
    assert migrated["campaign"]["configurations"][0]["nozzle_temperature_c"] is None
    assert migrated["specimens"][0]["print_metadata"]["printer"] is None
    assert study_models.StudyWorkspaceV3.model_validate(migrated).version == 3


def test_v2_configuration_migration_rejects_incompatible_replicates():
    payload = valid_workspace()
    second = {
        **payload["specimens"][0],
        "id": "S02",
        "label": "S02",
        "test_runs": [{**payload["specimens"][0]["test_runs"][0], "id": "run-2"}],
        "print_metadata": {**payload["specimens"][0]["print_metadata"], "material": "ABS"},
    }
    payload["specimens"].append(second)

    with pytest.raises(ValueError, match="configuration"):
        study_models.migrate_workspace_v2_to_v3(payload)

    payload = valid_workspace()
    payload["specimens"][0]["print_metadata"]["nozzle_temperature_c"] = True
    with pytest.raises(ValidationError):
        StudyWorkspaceV2.model_validate(payload)

    payload = valid_workspace()
    run = payload["specimens"][0]["test_runs"][0]
    run["settings"].update(
        forceColumn="force_N",
        displacementColumn="displacement_mm",
        widthMm="10",
        thicknessMm="2",
        gaugeLengthMm="50",
    )
    run["result"] = _saved_analysis_result(
        analyze_tensile_rows(run["rows"], "force_N", "displacement_mm", 10, 2, 50)
    )
    run["result"]["points"][0]["force_n"] = True
    with pytest.raises(ValidationError):
        StudyWorkspaceV2.model_validate(payload)


def test_analysis_result_must_match_raw_rows_and_known_specimen_dimensions():
    payload = valid_workspace()
    specimen = payload["specimens"][0]
    run = specimen["test_runs"][0]
    run["settings"].update(
        forceColumn="force_N",
        displacementColumn="displacement_mm",
        widthMm="10",
        thicknessMm="2",
        gaugeLengthMm="50",
    )
    run["result"] = _saved_analysis_result(
        analyze_tensile_rows(run["rows"], "force_N", "displacement_mm", 10, 2, 50)
    )
    StudyWorkspaceV2.model_validate(payload)

    specimen["geometry"]["width_mm"] = 11
    with pytest.raises(ValidationError, match="dimensions"):
        StudyWorkspaceV2.model_validate(payload)

    specimen["geometry"]["width_mm"] = 10
    run["result"] = _saved_analysis_result(
        analyze_tensile_rows(
            [
                {"force_N": "10", "displacement_mm": "0.1"},
                {"force_N": "20", "displacement_mm": "0.2"},
            ],
            "force_N",
            "displacement_mm",
            10,
            2,
            50,
        )
    )
    with pytest.raises(ValidationError, match="sample count"):
        StudyWorkspaceV2.model_validate(payload)


def _saved_analysis_result(result):
    return {
        "summary": {key: value for key, value in result.items() if key != "points"},
        "points": result["points"],
    }
