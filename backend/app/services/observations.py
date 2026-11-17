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


def nearby(
    database: Database, lat: float, lon: float, radius_km: float, limit: int
) -> dict[str, Any]:
    """Detections recorded within a geodesic radius of a point.

    A bounding box is used only as a cheap pre-filter; the final test is a
    haversine distance in metres. ``count`` is the exact number of stored
    detections in the circle, while ``sample`` is a bounded nearest-first
    list. Absence of rows is explicitly NOT absence of fire.
    """
    from harmonizer.matching.links import haversine_m

    # Degrees per km, generous latitude padding; longitude uses cos(lat) so the
    # box never excludes a point that the haversine test would accept.
    from math import cos, radians

    lat_pad = radius_km / 110.574
    lon_pad = radius_km / max(111.320 * abs(cos(radians(lat))), 1e-6)
    # Near the poles the longitude band spans the globe.
    if abs(lat) + lat_pad >= 90:
        lon_pad = 180.0
    bbox = (
        max(-180.0, lon - lon_pad),
        max(-90.0, lat - lat_pad),
        min(180.0, lon + lon_pad),
        min(90.0, lat + lat_pad),
    )
    # Bounded scan: the box is small for realistic radii, but cap it so a
    # pathological request cannot pull the whole table.
    rows = database.fetch_all(
        """
        SELECT observation_id, sensor, lat, lon, datetime_utc, frp_mw
        FROM observations
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
        LIMIT 100000
        """,
        [bbox[1], bbox[3], bbox[0], bbox[2]],
    )
    if not rows:
        return {"count": 0, "sample": [], "last_detected": None, "sensors": {}}

    distances = haversine_m(lat, lon, [float(r["lat"]) for r in rows], [float(r["lon"]) for r in rows])
    within = [i for i, d in enumerate(distances) if d <= radius_km * 1000.0]
    matched = [rows[i] for i in within]

    sensors: dict[str, int] = {}
    for row in matched:
        key = str(row["sensor"] or "unknown").upper()
        sensors[key] = sensors.get(key, 0) + 1

    ordered = sorted(
        zip(within, [float(distances[i]) for i in within]), key=lambda pair: pair[1]
    )[:limit]
    sample = []
    for index, distance_m in ordered:
        row = rows[index]
        sample.append(
            {
                "observation_id": row["observation_id"],
                "sensor": row["sensor"],
                "datetime_utc": row["datetime_utc"],
                "frp_mw": row["frp_mw"],
                "distance_km": round(distance_m / 1000.0, 3),
            }
        )

    dated = [r for r in matched if r["datetime_utc"] is not None]
    last = max((r["datetime_utc"] for r in dated), default=None)
    return {
        "count": len(matched),
        "sample": sample,
        "last_detected": last,
        "sensors": sensors,
    }


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


def grid_counts(database: Database, query: Any) -> list[dict[str, Any]]:
    """Detections per fixed lat/lon cell (sensors counted separately).

    Cells are aligned to the global grid, so a place keeps the same cell id on
    every request. FRP is reported as mean/max power only, never summed.
    """
    cell = float(query.cell_deg)
    n_rows = math.ceil(round(180.0 / cell, 6))
    n_cols = math.ceil(round(360.0 / cell, 6))
    query_sql, params = sql.grid_counts(
        query.as_filters(), cell, n_rows, n_cols, query.limit
    )
    rows = database.fetch_all(query_sql, params)

    cells: list[dict[str, Any]] = []
    for row in rows:
        r = int(row["row_index"])
        c = int(row["col_index"])
        min_lat = -90.0 + r * cell
        min_lon = -180.0 + c * cell
        max_lat = min(min_lat + cell, 90.0)
        max_lon = min(min_lon + cell, 180.0)
        cells.append(
            {
                "cell_id": f"g{r:04d}_{c:04d}",
                "min_lat": round(min_lat, 4),
                "min_lon": round(min_lon, 4),
                "max_lat": round(max_lat, 4),
                "max_lon": round(max_lon, 4),
                "center_lat": round((min_lat + max_lat) / 2, 4),
                "center_lon": round((min_lon + max_lon) / 2, 4),
                "detections": int(row["detections"]),
                "modis": int(row["modis"]),
                "viirs": int(row["viirs"]),
                "mean_frp_mw": row["mean_frp_mw"],
                "max_frp_mw": row["max_frp_mw"],
            }
        )
    return cells

def countries(database: Database) -> tuple[list[dict[str, Any]], int]:
    """Countries with stored detections, plus the total detection count.

    Reads the `observation_country` table built by tools/assign_countries.py.
    Returns (rows, total), where total includes observations left unassigned.
    """
    rows = database.fetch_all(
        """
        SELECT iso_a3, country, COUNT(*) AS detections
        FROM observation_country
        GROUP BY iso_a3, country
        ORDER BY detections DESC, country
        """,
        [],
    )
    total_rows = database.fetch_all("SELECT COUNT(*) AS total FROM observations", [])
    total = int(total_rows[0]["total"]) if total_rows else 0
    return [
        {
            "iso_a3": row["iso_a3"],
            "country": row["country"],
            "detections": int(row["detections"]),
        }
        for row in rows
    ], total
