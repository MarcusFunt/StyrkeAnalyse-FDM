import json
from threading import Thread
from urllib.request import Request, urlopen

import pytest

from fdm_strength.gui_analysis import analyze_tensile_rows
from fdm_strength.web import create_gui_server


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


def test_web_api_returns_the_shared_tensile_analysis():
    server = create_gui_server("127.0.0.1", 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = {
            "rows": [{"F": "10", "D": "0"}, {"F": "30", "D": "1"}],
            "force_column": "F",
            "displacement_column": "D",
            "width_mm": 5,
            "thickness_mm": 2,
            "gauge_length_mm": 25,
        }
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/analysis/tensile",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            result = json.load(response)
        assert result["summary"]["peak_stress_mpa"] == 3
        assert result["points"][1]["strain"] == 0.04
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


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

        def send(method, url, body=None):
            data = json.dumps(body).encode() if body is not None else None
            request = Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"} if body is not None else {},
                method=method,
            )
            with urlopen(request) as response:
                return json.load(response)

        created = send("POST", f"{base_url}/api/studies", study)
        study_id = created["id"]
        assert (tmp_path / "studies" / f"{study_id}.json").is_file()

        updated = {**study, "study_name": "Updated from laptop", "result": {"summary": {}}}
        send("PUT", f"{base_url}/api/studies/{study_id}", updated)

        index = send("GET", f"{base_url}/api/studies")
        loaded = send("GET", f"{base_url}/api/studies/{study_id}")
        assert index["studies"][0]["study_name"] == "Updated from laptop"
        assert loaded["rows"] == study["rows"]
        assert loaded["result"] == {"summary": {}}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
