"""Non-destructive QC flags.

Accepted flag vocabulary (provisional until Phase 03 verifies the official
definitions):

- ``invalid_ti4``      VIIRS ``bright_ti4 == 0`` (dataset observation: looks invalid)
- ``invalid_datetime`` no parseable acquisition timestamp
- ``missing_frp``      FRP is null
- ``night_detection``  ``daynight == "N"`` (informational, not a defect)
- ``type_nonzero``     ``type`` is not 0 (meaning to be verified)
- ``low_confidence``   VIIRS ``confidence == "l"`` (MODIS numeric classes unverified)

Flags are written to ``observations.qc_flags`` as a comma-separated string.
Rows are never removed.
"""

from __future__ import annotations

FLAG_EXPRESSIONS: dict[str, str] = {
    "invalid_ti4": "sensor = 'viirs' AND brightness_primary = 0",
    "invalid_datetime": "datetime_utc IS NULL",
    "missing_frp": "frp_mw IS NULL",
    "night_detection": "daynight = 'N'",
    "type_nonzero": "fire_type IS NOT NULL AND fire_type <> 0",
    "low_confidence": "sensor = 'viirs' AND lower(confidence_raw) = 'l'",
}

FLAGS: tuple[str, ...] = tuple(FLAG_EXPRESSIONS)


def flag_list_sql() -> str:
    """SQL expression building the comma-separated flag string."""
    parts = [
        f"CASE WHEN {expression} THEN '{flag}' END"
        for flag, expression in FLAG_EXPRESSIONS.items()
    ]
    return f"NULLIF(concat_ws(',', {', '.join(parts)}), '')"


def flag_count_expressions() -> dict[str, str]:
    """SQL aggregate expressions counting each flag."""
    return {
        flag: f"sum(CASE WHEN {expression} THEN 1 ELSE 0 END)"
        for flag, expression in FLAG_EXPRESSIONS.items()
    }
