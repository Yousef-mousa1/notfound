"""Loader unit tests.

``synthetic_time_padding.csv`` is synthetic and is used only to exercise the
``acq_time`` zero-padding path: the real sample files happen to contain no
short ``acq_time`` values, so the case cannot be cut from them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harmonizer.io import load_detections, read_header
from harmonizer.schema.columns import detected_sensor

FIXTURES = Path(__file__).parent / "fixtures"
MODis_HEAD = FIXTURES / "modis_head.csv"
SYNTHETIC = FIXTURES / "synthetic_time_padding.csv"


def test_sensor_is_detected_from_header():
    assert detected_sensor(read_header(MODis_HEAD)) == "modis"
    assert detected_sensor(read_header(FIXTURES / "viirs_head.csv")) == "viirs"
    assert detected_sensor(["a", "b"]) is None


def test_acq_time_is_zero_padded():
    loaded = load_detections(SYNTHETIC, "modis", "src_test")

    first = loaded.frame.iloc[0]
    assert first["datetime_utc"].strftime("%Y-%m-%d %H:%M") == "2012-01-01 00:24"


def test_no_rows_are_dropped_and_duplicates_are_counted():
    loaded = load_detections(SYNTHETIC, "modis", "src_test")

    assert loaded.rows_read == 3
    assert len(loaded.frame) == 3
    assert loaded.duplicate_rows == 1


def test_raw_json_preserves_original_values():
    loaded = load_detections(SYNTHETIC, "modis", "src_test")

    raw = json.loads(loaded.frame.iloc[0]["raw_json"])
    assert raw["acq_time"] == "24"
    assert raw["confidence"] == "80"
    assert raw["brightness"] == "320.1"
    assert raw["satellite"] == "Terra"


def test_platform_mapping_is_applied():
    loaded = load_detections(SYNTHETIC, "modis", "src_test", {"Terra": "Terra", "Aqua": "Aqua"})
    assert set(loaded.frame["platform"]) == {"Terra", "Aqua"}


def test_wrong_sensor_raises():
    with pytest.raises(ValueError):
        load_detections(SYNTHETIC, "viirs", "src_test")


def test_real_modis_fixture_keeps_every_row():
    loaded = load_detections(MODis_HEAD, "modis", "src_test")

    assert loaded.rows_read == 25
    assert len(loaded.frame) == 25
    assert loaded.invalid_datetime == 0
