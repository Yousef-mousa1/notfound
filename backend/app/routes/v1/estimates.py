"""Model-estimate endpoints: /api/v1/estimates.

These endpoints expose the offline modeling layer's output. They never create
detections and never modify raw observations.
"""

from __future__ import annotations

from flask import Blueprint, current_app

from ...db import get_db
from ...errors import ApiError
from ...schemas.estimates import (
    EstimateQuery,
    EstimatesImportRequest,
    ModelRunCreate,
    ModelRunQuery,
)
from ...serialization import TIME_BASIS, jsonable
from ...services import estimates as service
from ..common import ok, page_meta, parse_body, parse_query

estimates_blueprint = Blueprint("estimates", __name__)


def _config() -> dict:
    return current_app.config["HARMONIZER"]


PROVENANCE_NOTE = (
    "Estimates are offline model outputs, not FIRMS detections. observations "
    "is never modified."
)


@estimates_blueprint.post("/estimates/runs")
def register_run():
    """Register provenance for one modeling run."""
    request = parse_body(ModelRunCreate)
    return ok(
        jsonable(service.register_run(get_db(), request)),
        {"note": PROVENANCE_NOTE, "time_basis": TIME_BASIS},
        201,
    )


@estimates_blueprint.get("/estimates/runs")
def list_runs():
    """List registered model runs, newest first."""
    query = parse_query(ModelRunQuery)
    if query.run_id:
        row = service.get_run(get_db(), query.run_id)
        if row is None:
            raise ApiError(
                "model_run_not_found",
                f"No model run with id '{query.run_id}'.",
                404,
            )
        return ok(jsonable(row), {"note": PROVENANCE_NOTE})

    rows, total = service.list_runs(get_db(), query.limit, query.offset)
    return ok(
        jsonable(rows),
        {**page_meta(total, query.limit, query.offset), "note": PROVENANCE_NOTE},
    )


@estimates_blueprint.get("/estimates/runs/<run_id>")
def get_run(run_id: str):
    """Return one model run and how many estimates it owns."""
    row = service.get_run(get_db(), run_id)
    if row is None:
        raise ApiError("model_run_not_found", f"No model run with id '{run_id}'.", 404)
    return ok(jsonable(row), {"note": PROVENANCE_NOTE})


@estimates_blueprint.post("/estimates/import")
def import_series():
    """Import a harmonized parquet/CSV written by src/harmonize.py."""
    request = parse_body(EstimatesImportRequest)
    result = service.import_series(get_db(), _config(), request)
    return ok(
        jsonable(result),
        {"note": PROVENANCE_NOTE, "time_basis": TIME_BASIS},
        201,
    )


@estimates_blueprint.get("/estimates")
def list_estimates():
    """Page stored estimates; defaults to the most recent registered run."""
    query = parse_query(EstimateQuery)
    rows, total, run = service.list_estimates(get_db(), query)
    return ok(
        jsonable(rows),
        {
            **page_meta(total, query.limit, query.offset),
            "run_id": run["run_id"],
            "model_name": run["model_name"],
            "note": PROVENANCE_NOTE,
            "time_basis": TIME_BASIS,
        },
    )


@estimates_blueprint.get("/estimates/series")
def monthly_series():
    """Monthly estimates summed over all regions, for a dashboard panel."""
    query = parse_query(EstimateQuery, default_limit=100)
    payload = service.calendar_series(get_db(), query.run_id)
    return ok(jsonable(payload), {"time_basis": TIME_BASIS})
