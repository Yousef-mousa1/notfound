"""Validation request models."""

from __future__ import annotations

from pydantic import Field

from .common import PageQuery
from .observations import ObservationFilters


class ValidationRunRequest(ObservationFilters):
    """Build matched pairs and compute cross-sensor consistency metrics."""

    radius_m: float = Field(gt=0, le=100_000)
    time_window_h: float = Field(gt=0, le=48)
    max_pairs_per_detection: int = Field(default=10, ge=1, le=100)


class ValidationListQuery(PageQuery):
    """List validation runs, or pick one."""

    run_id: str | None = None
