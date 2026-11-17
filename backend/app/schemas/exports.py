"""Export request models (Slice E).

An export never changes stored data; it writes new files and a metadata record.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import PageQuery
from .observations import ObservationFilters

EXPORT_SOURCE = Literal[
    "observations",
    "harmonization-results",
    "validation-pairs",
    "anomalies",
]

EXPORT_KIND = Literal[
    "csv", "observations", "harmonized-data", "validation-report", "estimate-series"
]


def _filters_used(model: ObservationFilters) -> bool:
    """Return True when any observation filter was supplied."""
    return any(value is not None for value in model.as_filters().values())


class CsvExportRequest(ObservationFilters):
    """Generic CSV export of a stored table or a filtered observation query."""

    source: EXPORT_SOURCE
    run_id: str | None = Field(
        default=None,
        description="Run to export; defaults to the latest successful run.",
    )
    include_raw_json: bool = Field(
        default=False,
        description="Only valid for source=observations; adds the untouched source row.",
    )
    file_name: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _check_combination(self) -> "CsvExportRequest":
        run_scoped = self.source != "observations"
        if self.source == "observations" and self.run_id is not None:
            raise ValueError("run_id is only used by run-scoped sources.")
        if run_scoped and _filters_used(self):
            raise ValueError(
                "Observation filters only apply to source='observations'; "
                f"source='{self.source}' exports the whole stored run."
            )
        if self.include_raw_json and self.source != "observations":
            raise ValueError("include_raw_json is only valid for observations.")
        return self


class ObservationExportRequest(ObservationFilters):
    """CSV export of observations matching the given filters."""

    include_raw_json: bool = Field(default=False)
    file_name: str | None = Field(default=None, max_length=80)


class HarmonizedExportRequest(BaseModel):
    """CSV export of a stored harmonization run plus a metadata sidecar."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = Field(
        default=None, description="Defaults to the latest successful run."
    )
    file_name: str | None = Field(default=None, max_length=80)


class EstimateExportRequest(BaseModel):
    """CSV export of the model-produced harmonized estimate series.

    This reads the ``estimates`` table imported from the offline modeling
    layer. It never reads or writes ``observations``. Values are model
    estimates (including backcasts), not FIRMS detections.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = Field(
        default=None, description="Defaults to the latest registered model run."
    )
    # Keep in sync with SCALES in schemas/estimates.py.
    scale: Literal["viirs_harmonized", "modis_raw"] | None = Field(
        default=None,
        description="Export one scale only; defaults to both, kept in separate rows.",
    )
    file_name: str | None = Field(default=None, max_length=80)


class ValidationReportRequest(BaseModel):
    """JSON report of a validation run, optionally with the pair table."""

    model_config = ConfigDict(extra="forbid")

    run_id: str | None = Field(
        default=None, description="Defaults to the latest successful run."
    )
    include_pairs: bool = Field(
        default=True, description="Also write the stored matched-pair table as CSV."
    )


class ExportHistoryQuery(PageQuery):
    """Filters for the export history."""

    kind: EXPORT_KIND | None = None
    status: Literal["succeeded", "failed"] | None = None


class ExportFileQuery(BaseModel):
    """Choose between the JSON record and a file download."""

    model_config = ConfigDict(extra="forbid")

    download: bool = Field(default=False, description="Return the file instead of JSON.")
    file: str | None = Field(
        default=None,
        description="File inside the export (defaults to the primary data file).",
    )
