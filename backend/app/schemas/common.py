"""Shared request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PageQuery(BaseModel):
    """Standard pagination query."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class ImportListQuery(PageQuery):
    """Filters for the import history."""

    status: Literal["running", "succeeded", "failed", "skipped"] | None = None
    sensor: Literal["modis", "viirs"] | None = None


class JobListQuery(PageQuery):
    """Filters for the job list."""

    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None
    kind: str | None = None


class JobLogsQuery(BaseModel):
    """Incremental log polling."""

    model_config = ConfigDict(extra="forbid")

    after_seq: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=2000)
