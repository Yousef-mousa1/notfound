"""Observation filters and query models.

Values are validated before they reach any SQL builder. Sort columns are
checked against a whitelist, and bounding boxes are range-checked.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harmonizer.store.sql import SORTABLE_COLUMNS


def _parse_timestamp(value: object, end_of_day: bool) -> datetime | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            if len(text) == 10:
                parsed = datetime.fromisoformat(text)
                if end_of_day:
                    parsed = datetime.combine(parsed.date(), time.max)
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(
                f"Invalid timestamp '{value}'. Use ISO 8601, e.g. 2012-01-20 or 2012-01-20T03:22:00."
            ) from error

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_bbox(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be 'min_lon,min_lat,max_lon,max_lat'.")
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as error:
        raise ValueError("bbox values must be numbers.") from error
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise ValueError("bbox is out of range or min/max are inverted.")
    return f"{min_lon},{min_lat},{max_lon},{max_lat}"


class ObservationFilters(BaseModel):
    """Filter fields shared by observation and processing endpoints."""

    model_config = ConfigDict(extra="forbid")

    sensor: Literal["modis", "viirs"] | None = None
    platform: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    min_frp: float | None = Field(default=None, ge=0)
    max_frp: float | None = Field(default=None, ge=0)
    daynight: Literal["D", "N"] | None = None
    fire_type: int | None = None
    confidence_class: Literal["low", "nominal", "high"] | None = None
    source_id: str | None = None
    bbox: str | None = Field(
        default=None,
        description="min_lon,min_lat,max_lon,max_lat in WGS84 degrees.",
    )

    country: str | None = Field(
        default=None,
        description="Country code (ADM0_A3), see /observations/countries.",
    )

    @field_validator("start", mode="before")
    @classmethod
    def _parse_start(cls, value: object) -> datetime | None:
        return _parse_timestamp(value, end_of_day=False)

    @field_validator("end", mode="before")
    @classmethod
    def _parse_end(cls, value: object) -> datetime | None:
        return _parse_timestamp(value, end_of_day=True)

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: str | None) -> str | None:
        return _parse_bbox(value)
    @field_validator("country")
    @classmethod
    def _check_country(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        code = value.strip().upper()
        if not (2 <= len(code) <= 4 and code.isalnum()):
            raise ValueError("country must be a 3-letter code such as EGY.")
        return code

    @model_validator(mode="after")
    def _check_ranges(self) -> "ObservationFilters":
        if self.start and self.end and self.start > self.end:
            raise ValueError("start must be earlier than or equal to end.")
        if self.min_frp is not None and self.max_frp is not None:
            if self.min_frp > self.max_frp:
                raise ValueError("min_frp must be less than or equal to max_frp.")
        return self

    @property
    def bbox_tuple(self) -> tuple[float, float, float, float] | None:
        if self.bbox is None:
            return None
        values = tuple(float(part) for part in self.bbox.split(","))
        return (values[0], values[1], values[2], values[3])  # type: ignore[return-value]

    def as_filters(self) -> dict[str, object]:
        """Convert the validated filters into the SQL builder's filter dict."""
        return {
            "sensor": self.sensor,
            "platform": self.platform,
            "start": self.start,
            "end": self.end,
            "min_frp": self.min_frp,
            "max_frp": self.max_frp,
            "daynight": self.daynight,
            "fire_type": self.fire_type,
            "confidence_class": self.confidence_class,
            "source_id": self.source_id,
            "bbox": self.bbox_tuple,
            "country": self.country,
        }


class ObservationQuery(ObservationFilters):
    """Filters, pagination and sorting for observation endpoints."""

    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    sort: str = "datetime_utc"
    order: Literal["asc", "desc"] = "asc"
    granularity: Literal["day", "month", "year"] = "day"

    @field_validator("sort")
    @classmethod
    def _check_sort(cls, value: str) -> str:
        if value not in SORTABLE_COLUMNS:
            allowed = ", ".join(sorted(SORTABLE_COLUMNS))
            raise ValueError(f"Unsupported sort column. Allowed: {allowed}")
        return value
class GridQuery(ObservationFilters):
    """Filters plus grid settings for /observations/grid."""

    cell_deg: float = Field(default=1.0, ge=0.1, le=30.0)
    limit: int = Field(default=20000, ge=1, le=50000)