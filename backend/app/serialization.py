"""JSON serialization helpers.

Timestamps are stored naive and interpreted as UTC, an assumption that is
pending verification (see the ``time_basis`` field added by endpoints).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

TIME_BASIS = "UTC (assumed; timezone verification pending - dataset-facts.md §2)"


def iso_utc(value: datetime) -> str:
    """Format a naive UTC timestamp explicitly."""
    return value.isoformat(timespec="seconds") + "Z"


def jsonable(value: Any) -> Any:
    """Recursively convert a value into something ``jsonify`` can serialize."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "item"):  # numpy scalar
        return jsonable(value.item())
    return value


def maybe_json(text: str | None) -> Any:
    """Parse a JSON text column, returning it unchanged if it is not JSON."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text
