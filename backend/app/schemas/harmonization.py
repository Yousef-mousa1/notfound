"""Harmonization request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import PageQuery
from .observations import ObservationFilters


class HarmonizationRunRequest(ObservationFilters):
    """Run a harmonization over a grid with a chosen calibration."""

    grid_id: str = Field(min_length=1)
    time_bucket: Literal["none", "day", "month"] = "day"
    method: Literal["none", "ratio", "linear-regression", "quantile-mapping"] = "none"
    radius_m: float | None = Field(default=None, gt=0, le=100_000)
    time_window_h: float | None = Field(default=None, gt=0, le=48)
    max_pairs_per_detection: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def _require_radius_for_calibration(self) -> "HarmonizationRunRequest":
        if self.method != "none" and self.radius_m is None:
            raise ValueError("radius_m is required when a calibration method is used.")
        return self


class CalibrateRequest(ObservationFilters):
    """Fit a calibration without producing a grid result."""

    radius_m: float = Field(gt=0, le=100_000)
    time_window_h: float | None = Field(default=None, gt=0, le=48)
    max_pairs_per_detection: int = Field(default=10, ge=1, le=100)


class RunQuery(PageQuery):
    """Run listing / lookup."""

    run_id: str | None = None


class CellMapQuery(PageQuery):
    """Map points for a run's per-cell results."""

    run_id: str | None = None
    both_only: bool = False


class ResultQuery(PageQuery):
    """Page through a run's per-cell results."""

    run_id: str | None = None
    order_by_index: bool = True


class MetricQuery(BaseModel):
    """Pick a stored validation run (defaults to the latest)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
