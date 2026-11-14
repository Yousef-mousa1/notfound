"""Observation queries and analytics."""

from __future__ import annotations

import math
from typing import Any

from harmonizer.store import Database
from harmonizer.store import sql

from ..schemas.observations import ObservationQuery


def list_observations(
    database: Database, query: ObservationQuery
) -> tuple[list[dict[str, Any]], int]:
    """Return a page of observations and the total count for the filters."""
    filters = query.as_filters()
    rows_sql, rows_params = sql.observations_select(
        filters, query.sort, query.order, query.limit, query.offset
    )
    count_sql, count_params = sql.observations_count(filters)
    rows = database.fetch_all(rows_sql, rows_params)
    total = int(database.fetch_scalar(count_sql, count_params) or 0)
    return rows, total


def get_observation(database: Database, observation_id: str) -> dict[str, Any] | None:
    """Return one observation including its original row, or ``None``."""
    row_sql, row_params = sql.observation_by_id(observation_id)
    return database.fetch_one(row_sql, row_params)


def statistics(database: Database, query: ObservationQuery) -> dict[str, Any]:
    """Overall and per-sensor statistics for the filtered observations."""
    filters = query.as_filters()

    overall_sql, overall_params = sql.summary(filters)
    overall = database.fetch_one(overall_sql, overall_params) or {}

    per_sensor_sql, per_sensor_params = sql.statistics(filters)
    per_sensor = database.fetch_all(per_sensor_sql, per_sensor_params)

    return {
        "overall": overall,
        "per_sensor": per_sensor,
        "notes": {
            "frp": "FRP is instantaneous radiative power (MW); it is never summed into energy.",
            "coverage": (
                "Source files contain detections only. A missing row does not imply "
                "no fire; it may be no observation (Phase 06)."
            ),
        },
    }


def by_date(database: Database, query: ObservationQuery) -> list[dict[str, Any]]:
    """Detection counts per sensor per day/month bucket."""
    query_sql, params = sql.by_date(query.as_filters(), query.granularity)
    return database.fetch_all(query_sql, params)


def by_sensor(database: Database, query: ObservationQuery) -> list[dict[str, Any]]:
    """Detection counts and FRP statistics per sensor and platform."""
    query_sql, params = sql.by_sensor(query.as_filters())
    return database.fetch_all(query_sql, params)


def map_points(
    database: Database, query: ObservationQuery, limit: int
) -> list[dict[str, Any]]:
    """Point payload for a map view."""
    query_sql, params = sql.map_points(query.as_filters(), limit)
    return database.fetch_all(query_sql, params)


def regions(
    database: Database, query: ObservationQuery, grid: int
) -> list[dict[str, Any]]:
    """Counts per box on a data-extent grid.

    Regions are derived from the filtered data extent, not from administrative
    boundaries (none exist in the source data). Rows run south to north, columns
    west to east.
    """
    filters = query.as_filters()
    extent_sql, extent_params = sql.extent(filters)
    extent = database.fetch_one(extent_sql, extent_params) or {}
    if extent.get("min_lat") is None:
        return []

    min_lat = float(extent["min_lat"])
    max_lat = float(extent["max_lat"])
    min_lon = float(extent["min_lon"])
    max_lon = float(extent["max_lon"])
    # A tiny epsilon keeps the extreme edge inside the last cell.
    lat_step = (max_lat - min_lat) / grid if max_lat > min_lat else 0.0
    lon_step = (max_lon - min_lon) / grid if max_lon > min_lon else 0.0

    output: list[dict[str, Any]] = []
    for row in range(grid):
        for column in range(grid):
            box_min_lat = min_lat + row * lat_step
            box_max_lat = max_lat if row == grid - 1 else min_lat + (row + 1) * lat_step
            box_min_lon = min_lon + column * lon_step
            box_max_lon = max_lon if column == grid - 1 else min_lon + (column + 1) * lon_step

            cell_filters = dict(filters)
            cell_filters["bbox"] = (box_min_lon, box_min_lat, box_max_lon, box_max_lat)
            cell_sql, cell_params = sql.summary(cell_filters)
            cell = database.fetch_one(cell_sql, cell_params) or {}

            output.append(
                {
                    "region": f"R{row + 1}C{column + 1}",
                    "bbox": {
                        "min_lon": box_min_lon,
                        "min_lat": box_min_lat,
                        "max_lon": box_max_lon,
                        "max_lat": box_max_lat,
                    },
                    "detections": int(cell.get("detections") or 0),
                    "mean_frp_mw": _nan_to_none(cell.get("mean_frp_mw")),
                    "max_frp_mw": _nan_to_none(cell.get("max_frp_mw")),
                }
            )
    return output


def _nan_to_none(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
