"""Validation endpoints: /api/v1/validation.

Metrics are cross-sensor consistency on matched pairs, not accuracy against true
fire occurrence. The offline modeling layer separately evaluates held-out years
against observed VIIRS; these endpoints do not perform that validation.
"""

from __future__ import annotations

from flask import Blueprint

from ...db import get_db
from ...errors import ApiError
from ...schemas.harmonization import MetricQuery
from ...schemas.validation import ValidationListQuery, ValidationRunRequest
from ...serialization import TIME_BASIS, jsonable
from ...services import validation as service
from ..common import ok, page_meta, parse_body, parse_query

validation_blueprint = Blueprint("validation", __name__)


@validation_blueprint.post("/validation/run")
def run_validation():
    """Build matched pairs and store cross-sensor consistency metrics."""
    request = parse_body(ValidationRunRequest)
    result = service.run(get_db(), request)
    return ok(
        jsonable(result),
        {
            "note": "Cross-sensor consistency on matched pairs, not accuracy against true fire occurrence.",
            "time_basis": TIME_BASIS,
        },
        201,
    )


@validation_blueprint.get("/validation/results")
def list_results():
    """List validation runs, or return one run's stored metrics."""
    query = parse_query(ValidationListQuery)
    if query.run_id:
        run_row = service.get_run(get_db(), query.run_id)
        if run_row is None:
            raise ApiError(
                "validation_run_not_found",
                f"No validation run with id '{query.run_id}'.",
                404,
            )
        return ok(jsonable(run_row))

    rows, total = service.list_runs(get_db(), query.limit, query.offset)
    return ok(jsonable(rows), page_meta(total, query.limit, query.offset))


@validation_blueprint.get("/validation/metrics/mae")
def metric_mae():
    """Mean absolute MODIS-vs-VIIRS difference on matched pairs."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.mae_metric(get_db(), query.run_id)))


@validation_blueprint.get("/validation/metrics/rmse")
def metric_rmse():
    """Root mean squared MODIS-vs-VIIRS difference on matched pairs."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.rmse_metric(get_db(), query.run_id)))


@validation_blueprint.get("/validation/metrics/bias")
def metric_bias():
    """Signed mean difference (MODIS minus VIIRS) on matched pairs."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.bias_metric(get_db(), query.run_id)))


@validation_blueprint.get("/validation/metrics/correlation")
def metric_correlation():
    """Pearson and Spearman association between the two sensors."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.correlation_metric(get_db(), query.run_id)))


@validation_blueprint.get("/validation/distribution")
def distribution():
    """Quantiles of both sensors on matched pairs, plus a KS statistic."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.distribution(get_db(), query.run_id)))


@validation_blueprint.get("/validation/temporal")
def temporal():
    """Consistency by absolute overpass-time difference."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.temporal(get_db(), query.run_id)))


@validation_blueprint.get("/validation/spatial")
def spatial():
    """Consistency by geodesic distance between paired detections."""
    query = parse_query(MetricQuery)
    return ok(jsonable(service.spatial(get_db(), query.run_id)))
