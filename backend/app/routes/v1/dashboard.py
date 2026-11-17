"""Dashboard endpoints: /api/v1/dashboard."""

from __future__ import annotations

from flask import Blueprint, current_app

from ...db import get_db
from ...schemas.analytics import AnalyticsQuery
from ...schemas.estimates import EstimateQuery
from ...schemas.inspect import InspectQuery
from ...serialization import TIME_BASIS, jsonable
from ...services import dashboard as service
from ...services import estimates as estimates_service
from ..common import ok, parse_query

dashboard_blueprint = Blueprint("dashboard", __name__)


def _query() -> AnalyticsQuery:
    api = current_app.config["HARMONIZER"]["api"]
    return parse_query(AnalyticsQuery, default_limit=api["default_limit"])


@dashboard_blueprint.get("/dashboard/overview")
def overview():
    """Main summary panel."""
    return ok(jsonable(service.overview(get_db(), _query())), {"time_basis": TIME_BASIS})


@dashboard_blueprint.get("/dashboard/map")
def map_payload():
    """Bounded map points for observations and anomalies."""
    query = _query()
    api = current_app.config["HARMONIZER"]["api"]
    limit = min(query.limit, api["max_limit"])
    payload = service.map_payload(get_db(), query, limit)
    return ok(
        jsonable(payload),
        {"limit": limit, "time_basis": TIME_BASIS},
    )


@dashboard_blueprint.get("/dashboard/inspect")
def inspect_point():
    """Inspect a map click: recorded detections + model estimate for the block."""
    query = parse_query(InspectQuery)
    payload = service.inspect_point(
        get_db(), query.lat, query.lon, query.radius_km, query.limit
    )
    return ok(
        jsonable(payload),
        {
            "time_basis": TIME_BASIS,
            "note": "No detection record is not proof that no fire occurred.",
        },
    )


@dashboard_blueprint.get("/dashboard/calendar")
def calendar():
    """Daily counts per sensor for a calendar view."""
    return ok(jsonable(service.calendar(get_db(), _query())), {"time_basis": TIME_BASIS})


@dashboard_blueprint.get("/dashboard/estimates-calendar")
def estimates_calendar():
    """Monthly model-produced series, separate from raw detections."""
    query = parse_query(EstimateQuery)
    payload = estimates_service.calendar_series(get_db(), query.run_id)
    return ok(
        jsonable(payload),
        {
            "time_basis": TIME_BASIS,
            "note": "Model estimates only; observations are never modified or merged here.",
        },
    )


@dashboard_blueprint.get("/dashboard/anomalies")
def anomaly_panel():
    """Anomaly summary based on the latest successful run."""
    return ok(
        jsonable(service.anomaly_panel(get_db())),
        {"time_basis": TIME_BASIS},
    )


@dashboard_blueprint.get("/dashboard/trends")
def trends():
    """Daily and monthly trend payloads."""
    return ok(jsonable(service.trends(get_db(), _query())), {"time_basis": TIME_BASIS})


@dashboard_blueprint.get("/dashboard/sensor-comparison")
def sensor_comparison():
    """Side-by-side sensor panel."""
    return ok(
        jsonable(service.sensor_comparison(get_db(), _query())),
        {"time_basis": TIME_BASIS},
    )


@dashboard_blueprint.get("/dashboard/activity-index")
def activity_index():
    """Top harmonized cells from the latest successful run."""
    query = _query()
    payload = service.activity_index(get_db(), query, query.limit)
    return ok(
        jsonable(payload),
        {
            "returned": len(payload["cells"]),
            "time_basis": TIME_BASIS,
        },
    )
