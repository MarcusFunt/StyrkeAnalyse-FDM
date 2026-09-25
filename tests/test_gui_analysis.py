import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from fdm_strength.experimental_reduction import reduce_campaign_workspace
from fdm_strength.gui_analysis import analyze_tensile_rows
from fdm_strength.web import _validated_workspace, create_gui_server


def test_analyze_tensile_rows_converts_units_and_zeros_extension_at_first_point():
    result = analyze_tensile_rows(
        rows=[
            {"Load": "-0,20", "Travel": "0,5"},
            {"Load": "-0,85", "Travel": "1,5"},
            {"Load": "-0,30", "Travel": "2,0"},
        ],
        force_column="Load",
        displacement_column="Travel",
        width_mm=10,
        thickness_mm=2,
        gauge_length_mm=50,
        force_unit="kN",
        displacement_unit="mm",
        decimal_separator=",",
        tension_direction="negative",
    )

    assert result["sample_count"] == 3
    assert result["cross_section_area_mm2"] == 20
    assert result["peak_force_n"] == 850
    assert result["peak_stress_mpa"] == 42.5
    assert result["points"][0]["extension_mm"] == 0
    assert result["points"][1]["extension_mm"] == 1
    assert result["points"][1]["strain"] == 0.02
    assert result["points"][1]["stress_mpa"] == 42.5


def test_analyze_tensile_rows_rejects_bad_measurements_with_row_context():
    with pytest.raises(ValueError, match=r"row 2.*Travel"):
        analyze_tensile_rows(
            rows=[{"Load": "10", "Travel": "0"}, {"Load": "11", "Travel": "bad"}],
            force_column="Load",
            displacement_column="Travel",
            width_mm=10,
            thickness_mm=2,
            gauge_length_mm=50,
        )


def test_analyze_tensile_rows_rejects_non_positive_geometry():
    with pytest.raises(ValueError, match="width_mm must be positive"):
        analyze_tensile_rows(
            rows=[{"Load": "10", "Travel": "0"}],
            force_column="Load",
            displacement_column="Travel",
            width_mm=0,
            thickness_mm=2,
            gauge_length_mm=50,
        )


@pytest.mark.parametrize("dimensions", [(True, 2, 50), (1e308, 1e308, 50)])
def test_analyze_tensile_rows_rejects_boolean_or_overflowing_dimensions(dimensions):
    with pytest.raises(ValueError):
        analyze_tensile_rows(
            rows=[{"Load": "10", "Travel": "0.1"}],
            force_column="Load",
            displacement_column="Travel",
            width_mm=dimensions[0],
            thickness_mm=dimensions[1],
            gauge_length_mm=dimensions[2],
        )


def test_gui_proxies_formal_run_submission_to_the_runner(monkeypatch):
    received = {}

    class FakeRunnerHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            received["path"] = self.path
            received["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({"run": {"id": "run-1"}, "result": {"ok": True}}).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    runner = ThreadingHTTPServer(("127.0.0.1", 0), FakeRunnerHandler)
    runner_thread = Thread(target=runner.serve_forever, daemon=True)
    runner_thread.start()
    monkeypatch.setenv("FDM_RUNNER_URL", f"http://127.0.0.1:{runner.server_port}")
    server = create_gui_server("127.0.0.1", 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = {"operation": "tensile", "input_file": {"filename": "raw.csv"}}
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/runs",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            result = json.load(response)
        assert result == {"run": {"id": "run-1"}, "result": {"ok": True}}
        assert received == {"path": "/api/runs", "payload": payload}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        runner.shutdown()
        runner.server_close()
        runner_thread.join(timeout=2)


def test_web_api_persists_studies_on_the_host_and_can_update_them(tmp_path):
    server = create_gui_server("127.0.0.1", 0, data_dir=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        study = {
            "format": "styrkeanalyse-fdm-study",
            "version": 1,
            "study_name": "Phone upload",
            "source_file_name": "coupon.csv",
            "columns": ["F", "D"],
            "rows": [{"F": "10", "D": "0"}],
            "settings": {"forceColumn": "F"},
            "result": None,
        }

        def send(method, url, body=None, extra_headers=None):
            data = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json"} if body is not None else {}
            headers.update(extra_headers or {})
            request = Request(
                url,
                data=data,
                headers=headers,
                method=method,
            )
            with urlopen(request) as response:
                return json.load(response)

        created = send("POST", f"{base_url}/api/studies", study)
        study_id = created["id"]
        assert (tmp_path / "studies" / f"{study_id}.json").is_file()

        updated = {
            **study,
            "study_name": "Updated from laptop",
            "result": {
                "summary": {
                    "sample_count": 1,
                    "cross_section_area_mm2": 10,
                    "gauge_length_mm": 25,
                    "peak_force_n": 10,
                    "peak_force_row": 1,
                    "peak_stress_mpa": 1,
                    "peak_stress_row": 1,
                },
                "points": [
                    {
                        "row_number": 1,
                        "force_n": 10,
                        "displacement_mm": 0,
                        "extension_mm": 0,
                        "strain": 0,
                        "stress_mpa": 1,
                    }
                ],
            },
        }
        send(
            "PUT",
            f"{base_url}/api/studies/{study_id}",
            updated,
            {"If-Match": f'"{created["revision"]}"'},
        )

        index = send("GET", f"{base_url}/api/studies")
        loaded = send("GET", f"{base_url}/api/studies/{study_id}")
        assert index["studies"][0]["study_name"] == "Updated from laptop"
        assert loaded["rows"] == study["rows"]
        assert loaded["result"] == updated["result"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "patch",
    [
        {"columns": ["F", 7]},
        {"columns": ["F", "F"]},
        {"columns": []},
        {"rows": [{"F": "10"}]},
        {"rows": [{"F": {"nested": "10"}}]},
        {"settings": []},
        {"settings": {"widthMm": float("nan")}},
        {"result": {"summary": {}, "points": []}},
        {"extra_field": "must not be ignored"},
        {"analysis_time": "not a timestamp"},
    ],
)
def test_workspace_validator_rejects_malformed_nested_data(patch):
    payload = {
        "format": "styrkeanalyse-fdm-study",
        "version": 1,
        "study_name": "Valid study",
        "source_file_name": "test.csv",
        "columns": ["F", "D"],
        "rows": [{"F": "10", "D": "0"}],
        "settings": {},
        "result": None,
    }

    with pytest.raises(ValueError):
        _validated_workspace({**payload, **patch})


def test_v1_saved_result_must_match_rows_and_known_dimensions():
    payload = {
        "format": "styrkeanalyse-fdm-study",
        "version": 1,
        "study_name": "Valid study",
        "source_file_name": "test.csv",
        "columns": ["F", "D"],
        "rows": [{"F": "10", "D": "0.1"}],
        "settings": {"widthMm": "10", "thicknessMm": "2", "gaugeLengthMm": "50"},
        "result": _saved_analysis_result(
            analyze_tensile_rows([{"F": "10", "D": "0.1"}], "F", "D", 10, 2, 50)
        ),
    }
    _validated_workspace(payload)

    payload["settings"]["widthMm"] = "11"
    with pytest.raises(ValueError, match="area"):
        _validated_workspace(payload)

    payload["settings"]["widthMm"] = "10"
    payload["rows"].append({"F": "20", "D": "0.2"})
    with pytest.raises(ValueError, match="sample count"):
        _validated_workspace(payload)


def _saved_analysis_result(result):
    return {
        "summary": {key: value for key, value in result.items() if key != "points"},
        "points": result["points"],
    }


def test_workspace_validator_accepts_v2_campaigns_with_specimen_provenance():
    payload = {
        "format": "styrkeanalyse-fdm-study",
        "version": 2,
        "study_name": "PLA campaign",
        "campaign": {
            "id": "campaign-1",
            "name": "PLA campaign",
            "configurations": [{"id": "cfg-1", "label": "0/90"}],
        },
        "specimens": [
            {
                "id": "S01",
                "label": "S01",
                "configuration_id": "cfg-1",
                "geometry": {"width_mm": 10, "thickness_mm": 2, "gauge_length_mm": 50},
                "print_metadata": {"material": "PLA", "layer_height_mm": 0.2},
                "test_runs": [
                    {
                        "id": "run-1",
                        "sensor_source": "unknown",
                        "compliance_correction": {"method": "unknown"},
                        "input_file": {
                            "filename": "coupon.csv",
                            "media_type": "text/csv",
                            "size_bytes": None,
                            "sha256": None,
                            "imported_at": None,
                            "status": "unavailable_legacy",
                        },
                        "columns": ["F", "D"],
                        "rows": [{"F": "10", "D": "0"}],
                    }
                ],
            }
        ],
    }

    normalized = _validated_workspace(payload)
    assert normalized["version"] == 3
    assert normalized["specimens"][0]["test_runs"][0]["sensor_source"] == "unknown"


def test_web_api_migrates_v2_campaign_metadata_before_persisting(tmp_path):
    server = create_gui_server("127.0.0.1", 0, data_dir=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        payload = {
            "format": "styrkeanalyse-fdm-study",
            "version": 2,
            "study_name": "PLA campaign",
            "campaign": {
                "id": "campaign-1",
                "name": "PLA campaign",
                "configurations": [{"id": "cfg-1", "label": "0/90"}],
            },
            "specimens": [
                {
                    "id": "S01",
                    "label": "S01",
                    "configuration_id": "cfg-1",
                    "geometry": {"width_mm": 10, "thickness_mm": 2, "gauge_length_mm": 50},
                    "print_metadata": {"material": "PLA"},
                    "test_runs": [
                        {
                            "id": "run-1",
                            "sensor_source": "crosshead",
                            "compliance_correction": {"method": "unknown"},
                            "input_file": {
                                "filename": "phone.csv",
                                "status": "unavailable_legacy",
                            },
                            "columns": ["F", "D"],
                            "rows": [{"F": "10", "D": "0"}],
                        }
                    ],
                }
            ],
        }
        request = Request(
            f"{base_url}/api/studies",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            created = json.load(response)
        with urlopen(f"{base_url}/api/studies/{created['id']}") as response:
            loaded = json.load(response)
        with urlopen(f"{base_url}/api/studies") as response:
            index = json.load(response)

        assert loaded["version"] == 3
        assert loaded["campaign"]["configurations"][0]["material"] == "PLA"
        assert loaded["specimens"][0]["print_metadata"]["material"] is None
        assert index["studies"][0]["source_file_name"] == "phone.csv"
        delete_request = Request(
            f"{base_url}/api/studies/{created['id']}",
            headers={"If-Match": '"1"'},
            method="DELETE",
        )
        with urlopen(delete_request):
            pass
        with urlopen(f"{base_url}/api/trash") as response:
            trash = json.load(response)
        assert trash["studies"][0]["id"] == created["id"]
        restore_request = Request(
            f"{base_url}/api/studies/{created['id']}/restore",
            headers={"If-Match": '"2"'},
            method="POST",
        )
        with urlopen(restore_request):
            pass
        with urlopen(f"{base_url}/api/studies/{created['id']}") as response:
            restored = json.load(response)
        assert not restored.get("deleted_at")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_campaign_reduction_stage_counts_specimens_not_measurement_rows_and_applies_gate():
    specimens = []
    upstream_results = {}
    for index, modulus in enumerate([2000, 2100, 1900, 2000, 2000], start=1):
        run_id = f"00000000-0000-4000-8000-{index:012d}"
        specimens.append(
            {
                "id": f"S{index:02}",
                "label": f"Specimen {index}",
                "configuration_id": "cfg-1",
                "geometry": {"width_mm": 10, "thickness_mm": 2, "gauge_length_mm": 50},
                "print_metadata": {"material": "PLA"},
                "test_runs": [
                    {
                        "id": f"run-{index}",
                        "run_id": run_id,
                        "primary_for_reduction": True,
                        "sensor_source": "extensometer",
                        "compliance_correction": {"method": "not_required"},
                        "input_file": {
                            "filename": f"specimen-{index}.csv",
                            "status": "unavailable_legacy",
                        },
                        "columns": ["F", "D"],
                        # These copied rows are intentionally not used by campaign reduction.
                        "rows": [{"F": "999999", "D": "999999"}],
                        "settings": {"forceColumn": "F", "displacementColumn": "D"},
                    }
                ],
            }
        )
        upstream_results[run_id] = {
            "specimen_reduction": {
                "specimen_id": f"S{index:02}",
                "modulus_mpa": modulus,
                "status": "eligible",
                "reason": None,
                "strain_interval": [0.0005, 0.0025],
                "sensor_source": "extensometer",
                "correction_method": "not_required",
            }
        }
    payload = {
        "format": "styrkeanalyse-fdm-study",
        "version": 2,
        "study_name": "Campaign",
        "campaign": {
            "id": "campaign-1",
            "name": "Campaign",
            "configurations": [{"id": "cfg-1", "label": "PLA 0/90"}],
        },
        "specimens": specimens,
    }

    result = reduce_campaign_workspace(payload, upstream_results)

    aggregate = result["configurations"][0]["aggregate"]
    assert aggregate["n_total"] == 5
    assert aggregate["n_valid"] == 5
    assert aggregate["mean_mpa"] == pytest.approx(2000)
    assert aggregate["replicate_ready"] is True


def test_study_updates_use_etag_revisions_and_reject_stale_writes(tmp_path):
    server = create_gui_server("127.0.0.1", 0, data_dir=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        study = {
            "format": "styrkeanalyse-fdm-study",
            "version": 1,
            "study_name": "Conflict test",
            "source_file_name": "test.csv",
            "columns": ["F", "D"],
            "rows": [{"F": "10", "D": "0"}],
            "settings": {},
            "result": None,
        }
        create_request = Request(
            f"{base_url}/api/studies",
            data=json.dumps(study).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(create_request) as response:
            created = json.load(response)
            study_id = created["id"]
            assert created["revision"] == 1
            assert response.headers["ETag"] == '"1"'
        update_url = f"{base_url}/api/studies/{study_id}"
        update = {**study, "study_name": "Updated"}

        for headers, expected_status in [({}, 428), ({"If-Match": '"0"'}, 409)]:
            request = Request(
                update_url,
                data=json.dumps(update).encode(),
                headers={"Content-Type": "application/json", **headers},
                method="PUT",
            )
            with pytest.raises(HTTPError) as error:
                urlopen(request)
            body = json.load(error.value)
            assert error.value.code == expected_status
            if expected_status == 409:
                assert body["current_revision"] == 1

        current_request = Request(
            update_url,
            data=json.dumps(update).encode(),
            headers={"Content-Type": "application/json", "If-Match": '"1"'},
            method="PUT",
        )
        with urlopen(current_request) as response:
            updated = json.load(response)
            assert updated["revision"] == 2
            assert response.headers["ETag"] == '"2"'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_study_soft_delete_restore_and_permanent_purge(tmp_path):
    server = create_gui_server("127.0.0.1", 0, data_dir=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        study = {
            "format": "styrkeanalyse-fdm-study",
            "version": 1,
            "study_name": "Retention test",
            "source_file_name": "test.csv",
            "columns": ["F", "D"],
            "rows": [{"F": "10", "D": "0"}],
            "settings": {},
            "result": None,
        }
        create_request = Request(
            f"{base_url}/api/studies",
            data=json.dumps(study).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(create_request) as response:
            study_id = json.load(response)["id"]
        delete_request = Request(
            f"{base_url}/api/studies/{study_id}",
            headers={"If-Match": '"1"'},
            method="DELETE",
        )
        with urlopen(delete_request) as response:
            deleted = json.load(response)
            assert deleted["revision"] == 2
        with urlopen(f"{base_url}/api/studies") as response:
            assert json.load(response)["studies"] == []
        with urlopen(f"{base_url}/api/trash") as response:
            assert json.load(response)["studies"][0]["id"] == study_id

        restore_request = Request(
            f"{base_url}/api/studies/{study_id}/restore",
            headers={"If-Match": '"2"'},
            method="POST",
        )
        with urlopen(restore_request) as response:
            restored = json.load(response)
            assert restored["revision"] == 3
        with urlopen(f"{base_url}/api/studies") as response:
            assert json.load(response)["studies"][0]["id"] == study_id

        delete_again = Request(
            f"{base_url}/api/studies/{study_id}",
            headers={"If-Match": '"3"'},
            method="DELETE",
        )
        with urlopen(delete_again):
            pass
        permanent_request = Request(
            f"{base_url}/api/studies/{study_id}/permanent",
            headers={"If-Match": '"4"'},
            method="DELETE",
        )
        with urlopen(permanent_request) as response:
            assert response.status == 204
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_retention_policy_is_readable_and_bounded(tmp_path):
    server = create_gui_server("127.0.0.1", 0, data_dir=tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        with urlopen(f"{base_url}/api/retention") as response:
            assert json.load(response)["retention_days"] == 30
        update_request = Request(
            f"{base_url}/api/retention",
            data=json.dumps({"retention_days": 7}).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(update_request) as response:
            assert json.load(response)["retention_days"] == 7
        invalid_request = Request(
            f"{base_url}/api/retention",
            data=json.dumps({"retention_days": 0}).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(invalid_request)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
