"""Unified schema helpers.

The unified schema adds harmonized columns while every original value is kept
in ``raw_json`` (never overwritten, never dropped). See
``docs/dataset-facts.md`` §3.
"""

from __future__ import annotations

from .columns import SENSORS, UNIFIED_COLUMNS, detected_sensor, missing_columns

__all__ = ["SENSORS", "UNIFIED_COLUMNS", "detected_sensor", "missing_columns"]
