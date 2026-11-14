"""Observation endpoints: /api/v1/observations."""

from __future__ import annotations

from flask import Blueprint, current_app

from ...db import get_db
from ...errors import ApiError
from ...schemas.observations import ObservationQuery
from ...serialization import TIME_BASIS, jsonable
from ...services import observations as service
from ..common import ok, page_meta, parse_query

observations_blueprint = Blueprint("observations", __name__)


def _api_config() -> dict:
    return current_app.config["HARMONIZER"]["api"]


def _query() -> ObservationQuery:
    return parse_query(ObservationQuery, default_limit=_api_config()["default_limit"])


def _list_response(query: ObservationQuery):
    rows, total = service.list_observations(get_db(), query)
    meta = page_meta(total, query.limit, query.offset)
    meta["time_basis"] = TIME_BASIS
    meta["filters"] = jsonable({k: v for k, v in query.as_filters().items() if v is not None})
    return ok(jsonable(rows), meta)


@observations_blueprint.get("/observations")
def list_observations():
    """List observations with filtering and pagination."""
    return _list_response(_query())


@observations_blueprint.get("/observations/modis")
def list_modis():
    """List MODIS observations."""
    query = _query()
    query = query.model_copy(update={"sensor": "modis"})
    return _list_response(query)


@observations_blueprint.get("/observations/viirs")
def list_viirs():
    """List VIIRS observations."""
    query = _query()
    query = query.model_copy(update={"sensor": "viirs"})
    return _list_response(query)


@observations_blueprint.get("/observations/map")
def observations_map():
    """Point payload for a map view (bounded by the API max limit)."""
    query = _query()
    limit = min(query.limit, _api_config()["max_limit"])
    points = service.map_points(get_db(), query, limit)
    meta = {
        "returned": len(points),
        "limit": limit,
        "time_basis": TIME_BASIS,
    }
    return ok(jsonable(points), meta)


@observations_blueprint.get("/observations/statistics")
def observations_statistics():
    """Detection counts and FRP statistics, overall and per sensor."""
    query = _query()
    payload = service.statistics(get_db(), query)
    return ok(jsonable(payload), {"time_basis": TIME_BASIS})


@observations_blueprint.get("/observations/by-region")
def observations_by_region():
    """Detections per box on a grid derived from the data extent."""
    query = _query()
    grid = int((current_app.config["HARMONIZER"].get("spatial") or {}).get("region_grid") or 2)
    regions = service.regions(get_db(), query, grid)
    return ok(
        jsonable(regions),
        {
            "grid": grid,
            "region_basis": "data extent bounds (not administrative boundaries)",
            "time_basis": TIME_BASIS,
        },
    )


@observations_blueprint.get("/observations/by-date")
def observations_by_date():
    """Detection counts per day or month bucket."""
    query = _query()
    rows = service.by_date(get_db(), query)
    return ok(
        jsonable(rows),
        {"granularity": query.granularity, "time_basis": TIME_BASIS},
    )


@observations_blueprint.get("/observations/by-sensor")
def observations_by_sensor():
    """Detection counts and FRP statistics per sensor and platform."""
    query = _query()
    rows = service.by_sensor(get_db(), query)
    return ok(jsonable(rows), {"time_basis": TIME_BASIS})


@observations_blueprint.get("/observations/<observation_id>")
def get_observation(observation_id: str):
    """One observation, including its untouched original row."""
    row = service.get_observation(get_db(), observation_id)
    if row is None:
        raise ApiError(
            "observation_not_found", f"No observation with id '{observation_id}'.", 404
        )
    return ok(jsonable(row), {"time_basis": TIME_BASIS})
