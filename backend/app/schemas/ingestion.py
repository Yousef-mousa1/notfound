"""Ingestion request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImportRequest(BaseModel):
    """Import a detection file that already exists on disk."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, description="Path to the CSV (must be inside the project).")
    force: bool = Field(
        default=False,
        description="Re-run the import even if this exact file content was imported before.",
    )


class SyncRequest(BaseModel):
    """Import every registered source that has not been loaded yet."""

    model_config = ConfigDict(extra="forbid")

    sensors: list[Literal["modis", "viirs"]] | None = None
