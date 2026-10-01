import pytest

from fdm_strength.experimental_reduction import (
    analyze_uploaded_csv,
    parse_csv_bytes,
    reduce_campaign_workspace,
)


def test_original_csv_bytes_drive_tensile_and_specimen_reduction():
    source = b"Load (N);Travel (mm)\r\n0;0\r\n5;0,005\r\n15;0,015\r\n25;0,025\r\n"
    parameters = {
        "force_column": "Load (N)",
        "displacement_column": "Travel (mm)",
        "width_mm": 5,
        "thickness_mm": 2,
        "gauge_length_mm": 10,
        "force_unit": "N",
        "displacement_unit": "mm",
        "decimal_separator": ",",
        "tension_direction": "positive",
        "specimen_id": "coupon-1",
        "sensor_source": "extensometer",
        "compliance_correction": {"method": "not_required"},
    }

    result = analyze_uploaded_csv(source, parameters)

    assert result["analysis"]["summary"]["sample_count"] == 4
    assert result["analysis"]["points"][2]["strain"] == pytest.approx(0.0015)
    assert result["specimen_reduction"]["status"] == "eligible"
    assert result["specimen_reduction"]["modulus_mpa"] == pytest.approx(1000)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (b"\xef\xbb\xbfforce,travel\n1,2\n", "headers"),
        (b"force,force\n1,2\n", "Duplicate CSV headers"),
        (b"force,travel\n1,2,3\n", "more values than the CSV header"),
        (b"force,travel\n", "no measurement rows"),
        (b"force,travel\n1,2\n3,4,5\n", "more values than the CSV header"),
    ],
)
def test_original_csv_parser_rejects_malformed_headers_and_rows(source, message):
    if source.startswith(b"\xef\xbb\xbf"):
        # BOM handling should succeed; the fixture is valid CSV.
        assert parse_csv_bytes(source) == (["force", "travel"], [{"force": "1", "travel": "2"}])
        return
    with pytest.raises(ValueError, match=message):
        parse_csv_bytes(source)



def test_campaign_reduction_uses_immutable_upstream_result_not_editable_rows():
    run_id = "8e02d8f8-b1ab-4abc-9fe5-2f65173b6704"
    workspace = {
        "format": "styrkeanalyse-fdm-study",
        "version": 3,
        "study_name": "Immutable campaign",
        "campaign": {
            "id": "campaign-1",
            "name": "Immutable campaign",
            "reduction_run_id": None,
            "configurations": [{"id": "cfg-1", "label": "baseline"}],
        },
        "specimens": [
            {
                "id": "S01",
                "label": "S01",
                "configuration_id": "cfg-1",
                "geometry": {
                    "width_mm": 10.0,
                    "thickness_mm": 2.0,
                    "gauge_length_mm": 50.0,
                },
                "print_metadata": {},
                "test_runs": [
                    {
                        "id": "test-1",
                        "run_id": run_id,
                        "primary_for_reduction": True,
                        "test_type": "tensile",
                        "sensor_source": "extensometer",
                        "compliance_correction": {"method": "not_required"},
                        "input_file": {
                            "filename": "S01.csv",
                            "media_type": "text/csv",
                            "size_bytes": 4,
                            "sha256": "a" * 64,
                            "imported_at": "2026-09-25T06:00:00Z",
                            "status": "verified",
                        },
                        "columns": ["force_N", "displacement_mm"],
                        # Deliberately nonsense/tampered values. Campaign aggregation must
                        # never recompute from these editable copies once a formal Run exists.
                        "rows": [{"force_N": "999999", "displacement_mm": "999999"}],
                        "settings": {},
                        "result": None,
                    }
                ],
            }
        ],
    }
    immutable = {
        run_id: {
            "analysis": {"ignored": "campaigns do not recompute specimen mechanics"},
            "specimen_reduction": {
                "specimen_id": "S01",
                "modulus_mpa": 1234.5,
                "status": "eligible",
                "reason": None,
                "strain_interval": [0.0005, 0.0025],
                "sensor_source": "extensometer",
                "correction_method": "not_required",
            },
        }
    }

    reduced = reduce_campaign_workspace(workspace, immutable)

    specimen = reduced["configurations"][0]["specimen_reductions"][0]
    assert specimen["modulus_mpa"] == pytest.approx(1234.5)
    assert reduced["configurations"][0]["aggregate"]["n_valid"] == 1
