"""Column definitions for the two source products.

Nothing here is guessed: the sensor is detected from the actual header of the
file, and the required column list comes from the observed sample files
(``docs/dataset-facts.md`` §1). Official verification of each column's meaning
happens in Phase 03.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Columns every supported detection file must contain.
COMMON_REQUIRED: tuple[str, ...] = (
    "latitude",
    "longitude",
    "scan",
    "track",
    "acq_date",
    "acq_time",
    "satellite",
    "instrument",
    "confidence",
    "version",
    "frp",
    "daynight",
    "type",
)

#: Sensor-specific brightness bands (primary = detection band).
SENSOR_BANDS: dict[str, dict[str, str]] = {
    "modis": {"primary": "brightness", "secondary": "bright_t31"},
    "viirs": {"primary": "bright_ti4", "secondary": "bright_ti5"},
}

SENSORS: tuple[str, ...] = ("modis", "viirs")

#: Values of the ``instrument`` column that identify each product. Some VIIRS
#: extracts are delivered with MODIS-style band headers (``brightness`` /
#: ``bright_t31``), so the instrument column is the tie-breaker.
INSTRUMENT_SENSORS: dict[str, str] = {
    "MODIS": "modis",
    "VIIRS": "viirs",
    # Some extracts put the platform name in `instrument` instead.
    "TERRA": "modis",
    "AQUA": "modis",
    "SNPP": "viirs",
    "NOAA-20": "viirs",
    "NOAA-21": "viirs",
    "JPSS-1": "viirs",
    "JPSS-2": "viirs",
}

#: Unified observation columns, in physical storage order.
UNIFIED_COLUMNS: tuple[str, ...] = (
    "observation_id",
    "source_id",
    "source_row",
    "sensor",
    "platform",
    "lat",
    "lon",
    "datetime_utc",
    "frp_mw",
    "confidence_raw",
    "confidence_class",
    "brightness_primary",
    "brightness_secondary",
    "daynight",
    "fire_type",
    "scan",
    "track",
    "qc_flags",
    "raw_json",
)


def detected_sensor(
    columns: Sequence[str],
    instrument_values: Sequence[str] | None = None,
) -> str | None:
    """Infer the sensor from the presence of its unique brightness band.

    When ``instrument_values`` is given (the distinct values of the
    ``instrument`` column), it takes precedence: a file whose instrument is
    VIIRS but whose bands are named like MODIS is still a VIIRS file.

    Returns ``None`` when the header matches neither product, which is treated
    as an unsupported file rather than guessed.
    """
    normalized = {column.strip().lower() for column in columns}
    if instrument_values:
        named = {
            INSTRUMENT_SENSORS[str(value).strip().upper()]
            for value in instrument_values
            if str(value).strip().upper() in INSTRUMENT_SENSORS
        }
        if len(named) == 1:
            return named.pop()
    for sensor, bands in SENSOR_BANDS.items():
        if bands["primary"] in normalized:
            return sensor
    return None


def sensor_bands(columns: Sequence[str], sensor: str) -> dict[str, str]:
    """Return the brightness columns actually present for ``sensor``.

    VIIRS files normally carry ``bright_ti4``/``bright_ti5``; some extracts
    carry the MODIS names instead. Both are accepted for VIIRS.
    """
    normalized = {column.strip().lower() for column in columns}
    if sensor == "viirs" and "bright_ti4" not in normalized and "brightness" in normalized:
        return SENSOR_BANDS["modis"]
    return SENSOR_BANDS[sensor]


def missing_columns(
    columns: Sequence[str],
    sensor: str,
    bands: dict[str, str] | None = None,
) -> list[str]:
    """Return required columns absent from ``columns`` for ``sensor``."""
    if sensor not in SENSOR_BANDS:
        raise ValueError(f"Unsupported sensor: {sensor}")

    normalized = {column.strip().lower() for column in columns}
    resolved = bands or sensor_bands(columns, sensor)
    required = COMMON_REQUIRED + tuple(resolved.values())
    return [column for column in required if column not in normalized]
