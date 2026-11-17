"""Validation for point-inspection queries on the map.

A point inspection asks two independent questions about one location:
what detections are recorded near it (``observations``), and what the model
estimates for the 1-degree block that contains it (``estimates``). The two
are never merged and the response states that a missing record is not proof
that no fire occurred.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InspectQuery(BaseModel):
    """A map click: a WGS84 point and a search radius."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90, description="Click latitude in WGS84 degrees.")
    lon: float = Field(ge=-180, le=180, description="Click longitude in WGS84 degrees.")
    radius_km: float = Field(
        default=10.0,
        gt=0,
        le=500,
        description="Search radius in kilometres (geodesic, not degrees).",
    )
    limit: int = Field(default=20, ge=1, le=200, description="Maximum sample rows returned.")
