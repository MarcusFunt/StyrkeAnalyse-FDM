import pytest

from fdm_strength.experimental_reduction import analyze_uploaded_csv, parse_csv_bytes


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
