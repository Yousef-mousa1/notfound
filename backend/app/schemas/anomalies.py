"""Anomaly request models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .observations import ObservationFilters


class AnomalyDetectRequest(ObservationFilters):
    """Run statistical anomaly detection on a grid."""

    grid_id: str = Field(min_length=1)
    min_days: int = Field(default=5, ge=3, le=366)
    min_detections: int = Field(default=3, ge=1, le=100_000)
    threshold: float = Field(default=3.5, ge=1.0, le=20.0)


class AnomalyQuery(ObservationFilters):
    """Filters for anomaly result endpoints."""

    run_id: str | None = None
    severity: Literal["moderate", "high", "extreme"] | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
