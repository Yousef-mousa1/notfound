"""Anomaly endpoints: /api/v1/anomalies."""

from __future__ import annotations

from flask import Blueprint

from ...db import get_db
from ...errors import ApiError
from ...schemas.anomalies import AnomalyDetectRequest, AnomalyQuery
from ...serialization import TIME_BASIS, jsonable
from ...services import anomalies as service
from ..common import ok, page_meta, parse_body, parse_query

anomalies_blueprint = Blueprint("anomalies", __name__)


@anomalies_blueprint.post("/anomalies/detect")
def detect():
    """Run robust z-score anomaly detection on daily per-cell counts."""
    request = parse_body(AnomalyDetectRequest)
    result = service.run(get_db(), request)
    return ok(jsonable(result), {"time_basis": TIME_BASIS}, 201)


@anomalies_blueprint.get("/anomalies")
def list_anomalies():
    """List flagged anomalies, strongest first."""
    query = parse_query(AnomalyQuery)
    rows, total, run_row = service.list_anomalies(get_db(), query)
    return ok(
        jsonable(rows),
        {
            **page_meta(total, query.limit, query.offset),
            "run_id": run_row["run_id"],
            "method": "robust modified z-score on daily per-cell detection counts",
            "time_basis": TIME_BASIS,
        },
    )


@anomalies_blueprint.get("/anomalies/statistics")
def statistics():
    """Overall, per-sensor and per-severity statistics."""
    query = parse_query(AnomalyQuery)
    return ok(jsonable(service.statistics(get_db(), query)))


@anomalies_blueprint.get("/anomalies/severity")
def severity():
    """Severity bands and their counts."""
    query = parse_query(AnomalyQuery)
    return ok(jsonable(service.severity(get_db(), query)))


@anomalies_blueprint.get("/anomalies/by-region")
def by_region():
    """Anomaly counts per grid cell and sensor."""
    query = parse_query(AnomalyQuery)
    rows, run_row = service.by_region(get_db(), query)
    return ok(
        jsonable(rows),
        {
            "run_id": run_row["run_id"],
            "region_basis": "stored grid cells (not administrative boundaries)",
        },
    )


@anomalies_blueprint.get("/anomalies/by-date")
def by_date():
    """Anomaly counts per day and sensor."""
    query = parse_query(AnomalyQuery)
    return ok(jsonable(service.by_date(get_db(), query)))


@anomalies_blueprint.get("/anomalies/map")
def map_points():
    """Map payload for flagged anomalies."""
    query = parse_query(AnomalyQuery)
    rows = service.map_points(get_db(), query)
    return ok(jsonable(rows), {"returned": len(rows), "time_basis": TIME_BASIS})


@anomalies_blueprint.get("/anomalies/<anomaly_id>")
def get_anomaly(anomaly_id: str):
    """One anomaly with its run parameters."""
    row = service.get_anomaly(get_db(), anomaly_id)
    if row is None:
        raise ApiError(
            "anomaly_not_found", f"No anomaly with id '{anomaly_id}'.", 404
        )
    return ok(jsonable(row))
