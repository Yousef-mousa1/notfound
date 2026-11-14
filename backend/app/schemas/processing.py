"""Processing request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .observations import ObservationFilters, _parse_bbox

PROCESSING_KINDS = (
    "clean",
    "filter",
    "normalize",
    "spatial-matching",
    "temporal-matching",
    "grid",
    "aggregate",
    "features",
)


class CleanRequest(ObservationFilters):
    """Recompute QC flags for the selected rows."""

    dry_run: bool = Field(default=True, description="Count flags without writing them.")


class FilterRequest(ObservationFilters):
    """Persist a non-destructive selection."""

    name: str | None = Field(default=None, max_length=120)
    preview_limit: int = Field(default=10, ge=0, le=100)


class NormalizeRequest(BaseModel):
    """Structural normalization checks (and optional confidence mapping)."""

    model_config = ConfigDict(extra="forbid")

    apply_confidence: bool = False


class SpatialMatchRequest(ObservationFilters):
    """Link MODIS to VIIRS by geodesic distance."""

    radius_m: float = Field(gt=0, le=100_000, description="Maximum geodesic distance in metres.")
    time_window_h: float | None = Field(default=None, gt=0, le=48)
    max_pairs_per_detection: int = Field(default=10, ge=1, le=100)
    max_links: int = Field(default=200_000, ge=1, le=1_000_000)


class TemporalMatchRequest(ObservationFilters):
    """Link MODIS to VIIRS by acquisition time only."""

    time_window_h: float = Field(gt=0, le=48, description="Maximum |dt| in hours.")
    max_pairs_per_detection: int = Field(default=5, ge=1, le=100)
    max_links: int = Field(default=200_000, ge=1, le=1_000_000)


class GridGenerateRequest(BaseModel):
    """Create a common spatial grid."""

    model_config = ConfigDict(extra="forbid")

    cell_km: float = Field(gt=0, le=1000, description="Nominal cell size in km.")
    name: str | None = Field(default=None, max_length=120)
    bbox: str | None = None

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: str | None) -> str | None:
        return _parse_bbox(value)

    @property
    def bbox_tuple(self) -> tuple[float, float, float, float] | None:
        if self.bbox is None:
            return None
        values = tuple(float(part) for part in self.bbox.split(","))
        return (values[0], values[1], values[2], values[3])  # type: ignore[return-value]


class GridListQuery(BaseModel):
    """Grid lookup / listing."""

    model_config = ConfigDict(extra="forbid")

    grid_id: str | None = None
    limit: int = Field(default=500, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)


class AggregateRequest(ObservationFilters):
    """Aggregate detections per grid cell, sensors kept separate."""

    grid_id: str
    time_bucket: Literal["none", "day", "month"] = "none"


class FeaturesRequest(ObservationFilters):
    """Extract per-cell features, sensors kept separate."""

    grid_id: str


class ProcessingJobRequest(BaseModel):
    """Submit a processing operation to the background runner."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "clean",
        "filter",
        "normalize",
        "spatial-matching",
        "temporal-matching",
        "grid",
        "aggregate",
        "features",
    ]
    params: dict = Field(default_factory=dict)


PROCESSING_SCHEMAS: dict[str, type[BaseModel]] = {
    "clean": CleanRequest,
    "filter": FilterRequest,
    "normalize": NormalizeRequest,
    "spatial-matching": SpatialMatchRequest,
    "temporal-matching": TemporalMatchRequest,
    "grid": GridGenerateRequest,
    "aggregate": AggregateRequest,
    "features": FeaturesRequest,
}
