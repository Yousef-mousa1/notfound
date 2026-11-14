"""Analytics endpoints: /api/v1/analytics."""

from __future__ import annotations

from flask import Blueprint, current_app

from ...db import get_db
from ...errors import ApiError
from ...schemas.analytics import AnalyticsQuery
from ...serialization import TIME_BASIS, jsonable
from ...services import analytics as service
from ..common import ok, parse_query

analytics_blueprint = Blueprint("analytics", __name__)


def _api_config() -> dict:
    return current_app.config["HARMONIZER"]["api"]


def _query() -> AnalyticsQuery:
    return parse_query(AnalyticsQuery, default_limit=_api_config()["default_limit"])


def _region_grid() -> int:
    return int(
        (current_app.config["HARMONIZER"].get("spatial") or {}).get("region_grid") or 2
    )


@analytics_blueprint.get("/analytics/overview")
def overview():
    """Dataset summary with available downstream outputs."""
    return ok(jsonable(service.overview(get_db(), _query())), {"time_basis": TIME_BASIS})


@analytics_blueprint.get("/analytics/hotspot-trends")
def hotspot_trends():
    """Detection counts per sensor per time bucket."""
    query = _query()
    payload = service.hotspot_trends(get_db(), query)
    return ok(
        jsonable(payload),
        {"granularity": query.granularity, "time_basis": TIME_BASIS},
    )


@analytics_blueprint.get("/analytics/frp-trends")
def frp_trends():
    """FRP statistics per sensor per time bucket (MW, never energy)."""
    query = _query()
    payload = service.frp_trends(get_db(), query)
    return ok(
        jsonable(payload),
        {"granularity": query.granularity, "time_basis": TIME_BASIS},
    )


@analytics_blueprint.get("/analytics/activity-trends")
def activity_trends():
    """Harmonized activity index per time bucket."""
    payload = service.activity_trends(get_db(), _query())
    return ok(jsonable(payload), {"time_basis": TIME_BASIS})


@analytics_blueprint.get("/analytics/daily")
def daily():
    """Daily series per sensor."""
    payload = service.daily(get_db(), _query())
    return ok(jsonable(payload), {"granularity": "day", "time_basis": TIME_BASIS})


@analytics_blueprint.get("/analytics/monthly")
def monthly():
    """Monthly series per sensor."""
    payload = service.monthly(get_db(), _query())
    return ok(jsonable(payload), {"granularity": "month", "time_basis": TIME_BASIS})


@analytics_blueprint.get("/analytics/yearly")
def yearly():
    """Yearly series with an explicit no-trend-claim flag."""
    payload = service.yearly(get_db(), _query())
    return ok(
        jsonable(payload),
        {"granularity": "year", "trend_claim": False, "time_basis": TIME_BASIS},
    )


@analytics_blueprint.get("/analytics/regions")
def regions():
    """Counts per data-extent region."""
    rows = service.regions(get_db(), _query(), _region_grid())
    return ok(
        jsonable(rows),
        {
            "grid": _region_grid(),
            "region_basis": "data extent bounds (not administrative boundaries)",
            "time_basis": TIME_BASIS,
        },
    )


@analytics_blueprint.get("/analytics/land-cover")
def land_cover():
    """Not implemented: no land-cover dataset is registered."""
    raise ApiError(
        "not_implemented",
        "Land-cover analysis is not implemented.",
        501,
        {
            "reason": "No land-cover dataset is registered in this project.",
            "needed": "A classified land-cover raster with a documented CRS and version.",
        },
    )


@analytics_blueprint.get("/analytics/sensor-comparison")
def sensor_comparison():
    """Side-by-side sensor statistics and consistency snapshot."""
    return ok(
        jsonable(service.sensor_comparison(get_db(), _query())),
        {"time_basis": TIME_BASIS},
    )
