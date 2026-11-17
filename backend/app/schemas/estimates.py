"""Request models for model-produced estimates.

The models in this module describe *outputs of the offline modeling layer*.
They are deliberately separate from ``observations``: an estimate is never a
detection and is never written into the raw observation table.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import PageQuery

SCALES = ("viirs_harmonized", "modis_raw")
LEVELS = ("region", "country")


class ModelRunCreate(BaseModel):
    """Register the provenance of one modeling-layer run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = Field(default=None, min_length=1, max_length=64)
    model_name: str = Field(default="modis_to_viirs_backcast", min_length=1)
    method: str = Field(default="cell_day_poisson_isotonic", min_length=1)
    trained_years: list[int] | None = None
    test_year: int | None = None
    validation_split: str | None = None
    metrics: dict[str, Any] | None = None
    artifact_path: str | None = None
    notes: str | None = None


class EstimatesImportRequest(BaseModel):
    """Import a harmonized series produced by ``src/harmonize.py``."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    level: Literal["region", "country"] = "region"


class ModelRunQuery(PageQuery):
    """List registered model runs."""

    run_id: str | None = None


class EstimateQuery(PageQuery):
    """Filter stored estimates (defaults to the latest registered run)."""

    run_id: str | None = None
    level: str | None = None
    entity_id: str | None = None
    scale: Literal["viirs_harmonized", "modis_raw"] | None = None
    from_period: date | None = None
    to_period: date | None = None
    is_estimate: bool | None = None
