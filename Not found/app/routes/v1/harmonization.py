"""Harmonization endpoints: /api/v1/harmonization."""

from __future__ import annotations

from flask import Blueprint

from ...db import get_db
from ...errors import ApiError
from ...schemas.harmonization import (
    CalibrateRequest,
    CellMapQuery,
    HarmonizationRunRequest,
    MetricQuery,
    ResultQuery,
    RunQuery,
)
from ...serialization import jsonable
from ...services import harmonization as service
from ..common import ok, page_meta, parse_body, parse_query

harmonization_blueprint = Blueprint("harmonization", __name__)

RANDOM_FOREST_DETAILS = {
    "reason": (
        "random-forest requires labelled training data and a spatial/temporal "
        "validation strategy; MODIS is not ground truth."
    ),
    "checklist": "docs/phases/phase-08-ml.md",
    "alternatives": ["ratio", "linear-regression", "quantile-mapping"],
}


@harmonization_blueprint.get("/harmonization/methods")
def list_methods():
    """List calibration methods and whether they are implemented."""
    return ok(
        service.methods(),
        {"note": "Fits use matched MODIS/VIIRS pairs; MODIS is not ground truth."},
    )


@harmonization_blueprint.post("/harmonization/run")
def run_harmonization():
    """Fit an optional calibration and write per-cell harmonized results."""
    request = parse_body(HarmonizationRunRequest)
    result = service.run(get_db(), request)
    return ok(
        jsonable(result),
        {
            "note": "Only per-cell results are written; observations are never modified.",
            "time_basis": "UTC (assumed; timezone verification pending - dataset-facts.md §2)",
        },
        201,
    )


def _calibrate(method: str):
    request = parse_body(CalibrateRequest)
    result = service.calibrate(get_db(), method, request)
    return ok(jsonable(result), {"method": method}, 201)


@harmonization_blueprint.post("/harmonization/calibrate/ratio")
def calibrate_ratio():
    """Fit VIIRS * median(MODIS/VIIRS) on matched pairs."""
    return _calibrate("ratio")


@harmonization_blueprint.post("/harmonization/calibrate/linear-regression")
def calibrate_linear_regression():
    """Fit MODIS = intercept + slope * VIIRS on matched pairs."""
    return _calibrate("linear-regression")


@harmonization_blueprint.post("/harmonization/calibrate/quantile-mapping")
def calibrate_quantile_mapping():
    """Fit empirical quantile mapping of VIIRS onto MODIS."""
    return _calibrate("quantile-mapping")


@harmonization_blueprint.post("/harmonization/calibrate/random-forest")
def calibrate_random_forest():
    """Deliberately not implemented: no labels and MODIS is not ground truth."""
    raise ApiError(
        "not_implemented",
        "random-forest calibration is not implemented.",
        501,
        RANDOM_FOREST_DETAILS,
    )


@harmonization_blueprint.get("/harmonization/results")
def list_results():
    """List harmonization runs, or return one run's summary."""
    query = parse_query(RunQuery)
    if query.run_id:
        run_row = service.get_run(get_db(), query.run_id)
        if run_row is None:
            raise ApiError(
                "harmonization_run_not_found",
                f"No harmonization run with id '{query.run_id}'.",
                404,
            )
        return ok(jsonable(run_row))

    rows, total = service.list_runs(get_db(), query.limit, query.offset)
    return ok(jsonable(rows), page_meta(total, query.limit, query.offset))


@harmonization_blueprint.get("/harmonization/results/<result_id>")
def get_result(result_id: str):
    """Return a run and its per-cell results."""
    query = parse_query(ResultQuery)
    run_row = service.get_run(get_db(), result_id)
    if run_row is None:
        raise ApiError(
            "harmonization_run_not_found",
            f"No harmonization run with id '{result_id}'.",
            404,
        )
    rows, total = service.results(
        get_db(), result_id, query.limit, query.offset, query.order_by_index
    )
    return ok(
        jsonable({"run": run_row, "results": rows}),
        {
            **page_meta(total, query.limit, query.offset),
            "run_id": result_id,
            "method": run_row.get("method"),
            "ordered_by_index": query.order_by_index,
        },
    )


@harmonization_blueprint.get("/harmonization/comparison")
def comparison():
    """Compare sensor coverage and index behaviour inside a run."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.comparison(get_db(), query.run_id)))


@harmonization_blueprint.get("/harmonization/uncertainty")
def uncertainty():
    """Report coverage and per-cell cross-sensor disagreement."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.uncertainty(get_db(), query.run_id)))


@harmonization_blueprint.get("/harmonization/activity-index")
def activity_index():
    """Rank cells by the unitless harmonized activity index."""
    query = parse_query(ResultQuery)
    payload = service.activity_index(
        get_db(), query.run_id, query.limit, query.offset
    )
    total = payload.pop("total")
    return ok(
        jsonable(payload),
        {**page_meta(total, query.limit, query.offset), "run_id": payload["run_id"]},
    )


@harmonization_blueprint.get("/harmonization/cells")
def cells():
    """Map points for a run's cell-days (grid cell centres, not detections)."""
    query = parse_query(CellMapQuery)
    payload = service.map_cells(
        get_db(), query.run_id, query.both_only, query.limit, query.offset
    )
    total = payload["total"]
    return ok(
        jsonable(payload),
        {
            **page_meta(total, query.limit, query.offset),
            "run_id": payload["run_id"],
            "grid_id": payload["grid_id"],
            "time_basis": "UTC (assumed; timezone verification pending - dataset-facts.md §2)",
        },
    )
