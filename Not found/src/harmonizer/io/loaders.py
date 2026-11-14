"""CSV loaders that map a detection file into the unified schema.

Design rules:
- Every original value is preserved verbatim in ``raw_json``.
- No row is ever dropped. Invalid values become ``NaN``/``NaT`` and are counted.
- ``acq_time`` is read as text so leading zeros survive (``24`` -> ``00:24``).
- ``datetime_utc`` is built from date + time; the label "UTC" is an assumption
  pending verification (``docs/dataset-facts.md`` §2).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..schema.columns import (
    SENSOR_BANDS,
    detected_sensor,
    missing_columns,
    sensor_bands,
)


@dataclass
class LoadedDetections:
    """Unified rows plus auditable loading statistics."""

    frame: pd.DataFrame
    rows_read: int
    duplicate_rows: int
    invalid_datetime: int
    invalid_numeric: dict[str, int] = field(default_factory=dict)
    sensor: str = ""

    def as_stats(self) -> dict[str, object]:
        """Return a JSON-friendly summary of the load."""
        return {
            "rows_read": self.rows_read,
            "duplicate_rows": self.duplicate_rows,
            "invalid_datetime": self.invalid_datetime,
            "invalid_numeric": dict(self.invalid_numeric),
            "sensor": self.sensor,
        }


def read_header(path: str | Path) -> list[str]:
    """Read only the header row of a CSV file."""
    header = pd.read_csv(path, nrows=0)
    return [str(column) for column in header.columns]


def detect_file_sensor(path: str | Path) -> str | None:
    """Detect the sensor of a file from its header (never from its name)."""
    return detected_sensor(read_header(path), read_instrument_values(path))


def read_instrument_values(path: str | Path, nrows: int = 5000) -> set[str]:
    """Read the distinct ``instrument`` values from the first rows of a file."""
    try:
        sample = pd.read_csv(path, usecols=["instrument"], dtype=str, nrows=nrows)
    except (ValueError, KeyError, pd.errors.ParserError):
        return set()
    return {str(value).strip() for value in sample["instrument"].dropna().unique()}


def load_detections(
    path: str | Path,
    sensor: str,
    source_id: str,
    platform_mapping: dict[str, str] | None = None,
) -> LoadedDetections:
    """Load a MODIS or VIIRS CSV into the unified schema.

    Args:
        path: Source CSV (read only).
        sensor: ``"modis"`` or ``"viirs"``; must match the file's header.
        source_id: Registered source identifier, used for stable observation ids.
        platform_mapping: Optional mapping of raw ``satellite`` values to
            platform names (an engineering assumption, kept in config).

    Raises:
        ValueError: If the header does not belong to ``sensor``.
    """
    if sensor not in SENSOR_BANDS:
        raise ValueError(f"Unsupported sensor: {sensor}")

    # dtype=str: prevents silent numeric/date coercion and leading-zero loss.
    raw = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)

    bands = sensor_bands(list(raw.columns), sensor)
    detected = detected_sensor(list(raw.columns), read_instrument_values(path))
    missing = missing_columns(list(raw.columns), sensor, bands)
    if detected != sensor or missing:
        raise ValueError(
            f"File does not match sensor '{sensor}': detected={detected}, missing={missing}"
        )

    rows_read = len(raw)
    duplicate_rows = int(raw.duplicated().sum())
    source_rows = pd.Series(range(2, rows_read + 2), dtype="int64")  # header is row 1

    date_text = raw["acq_date"].astype(str).str.strip()
    time_text = raw["acq_time"].astype(str).str.strip().str.zfill(4)
    stamps = date_text + " " + time_text.str.slice(0, 2) + ":" + time_text.str.slice(2, 4)
    datetime_utc = pd.to_datetime(stamps, format="%Y-%m-%d %H:%M", errors="coerce")

    invalid_numeric: dict[str, int] = {}

    def numeric(column: str) -> pd.Series:
        converted = pd.to_numeric(raw[column], errors="coerce")
        invalid_numeric[column] = int(converted.isna().sum() - raw[column].eq("").sum())
        return converted.astype("float64")

    mapping = platform_mapping or {}
    platform = raw["satellite"].astype(str).str.strip().map(
        lambda value: mapping.get(value, value)
    )
    fire_type = pd.to_numeric(raw["type"], errors="coerce").astype("Int64")

    records = raw.to_dict("records")
    raw_json = [
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records
    ]
    observation_ids = [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_id}:{row}"))
        for row in source_rows.tolist()
    ]

    frame = pd.DataFrame(
        {
            "observation_id": observation_ids,
            "source_id": source_id,
            "source_row": source_rows,
            "sensor": sensor,
            "platform": platform,
            "lat": numeric("latitude"),
            "lon": numeric("longitude"),
            "datetime_utc": datetime_utc,
            "frp_mw": numeric("frp"),
            "confidence_raw": raw["confidence"].astype(str),
            "confidence_class": None,
            "brightness_primary": numeric(bands["primary"]),
            "brightness_secondary": numeric(bands["secondary"]),
            "daynight": raw["daynight"].astype(str),
            "fire_type": fire_type,
            "scan": numeric("scan"),
            "track": numeric("track"),
            "qc_flags": None,
            "raw_json": raw_json,
        }
    )

    return LoadedDetections(
        frame=frame,
        rows_read=rows_read,
        duplicate_rows=duplicate_rows,
        invalid_datetime=int(datetime_utc.isna().sum()),
        invalid_numeric=invalid_numeric,
        sensor=sensor,
    )
