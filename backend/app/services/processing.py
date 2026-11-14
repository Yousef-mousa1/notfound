"""Processing operations: clean, filter, normalize, matching, grid, aggregate.

Every operation is non-destructive: rows are flagged, selected, linked or
aggregated into new tables; ``observations`` rows are never deleted or merged.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pandas as pd
from pydantic import BaseModel

from harmonizer.matching import spatial_links, temporal_links
from harmonizer.spatial import build_grid
from harmonizer.store import Database
from harmonizer.store import jobs as job_store
from harmonizer.store import sql
from harmonizer.validate import flag_count_expressions, flag_list_sql

from ..errors import ApiError
from ..schemas.processing import (
    AggregateRequest,
    CleanRequest,
    FeaturesRequest,
    FilterRequest,
    GridGenerateRequest,
    NormalizeRequest,
    SpatialMatchRequest,
    TemporalMatchRequest,
)

AGGREGATE_COLUMNS = (
    "run_id",
    "grid_id",
    "cell_id",
    "time_bucket",
    "sensor",
    "detections",
    "mean_frp_mw",
    "median_frp_mw",
    "max_frp_mw",
    "min_frp_mw",
    "day_detections",
    "night_detections",
)

FEATURE_COLUMNS = (
    "run_id",
    "grid_id",
    "cell_id",
    "sensor",
    "detections",
    "distinct_days",
    "mean_frp_mw",
    "median_frp_mw",
    "max_frp_mw",
    "day_fraction",
    "night_fraction",
    "first_detection_utc",
    "last_detection_utc",
)


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:16]}"


def execute(
    database: Database,
    config: dict[str, Any],
    kind: str,
    params: BaseModel,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Run one processing operation and record a processing run."""
    operation = OPERATIONS.get(kind)
    if operation is None:
        raise ApiError("unsupported_operation", f"Unknown processing kind '{kind}'.", 400)

    run_id = _new_run_id()
    database.execute(
        "INSERT INTO processing_runs (run_id, kind, params, status, job_id, created_at) "
        "VALUES (?, ?, ?, 'running', ?, ?)",
        [
            run_id,
            kind,
            params.model_dump_json(),
            job_id,
            job_store.utcnow(),
        ],
    )

    try:
        result = operation(database, config, params, run_id)
    except Exception as error:
        database.execute(
            "UPDATE processing_runs SET status = 'failed', result = ?, finished_at = ? "
            "WHERE run_id = ?",
            [json.dumps({"error": str(error)}), job_store.utcnow(), run_id],
        )
        raise

    database.execute(
        "UPDATE processing_runs SET status = 'succeeded', result = ?, finished_at = ? "
        "WHERE run_id = ?",
        [json.dumps(result, default=str), job_store.utcnow(), run_id],
    )
    return {"run_id": run_id, "kind": kind, **result}


def _clean(
    database: Database, config: dict[str, Any], params: CleanRequest, run_id: str
) -> dict[str, Any]:
    filters = params.as_filters()
    count_sql, count_params = sql.flag_counts(filters, flag_count_expressions())
    counts = database.fetch_one(count_sql, count_params) or {}

    if not params.dry_run:
        update_sql, update_params = sql.update_flags(filters, flag_list_sql())
        database.execute(update_sql, update_params)

    return {
        "dry_run": params.dry_run,
        "written": not params.dry_run,
        "rows": int(counts.get("rows") or 0),
        "flag_counts": {
            flag: int(counts.get(flag) or 0)
            for flag in flag_count_expressions()
        },
        "notes": [
            "Flags are additive: rows are never deleted or modified in place beyond qc_flags.",
            "Flag definitions are provisional until Phase 03 verifies the official product documentation.",
        ],
    }


def _filter(
    database: Database, config: dict[str, Any], params: FilterRequest, run_id: str
) -> dict[str, Any]:
    filters = params.as_filters()
    count_sql, count_params = sql.observations_count(filters)
    detections = int(database.fetch_scalar(count_sql, count_params) or 0)

    selection_id = f"sel_{uuid.uuid4().hex[:16]}"
    database.execute(
        "INSERT INTO selections (selection_id, name, filters, detections, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            selection_id,
            params.name,
            json.dumps({key: value for key, value in filters.items() if value is not None}, default=str),
            detections,
            job_store.utcnow(),
        ],
    )

    preview: list[dict[str, Any]] = []
    if params.preview_limit:
        preview_sql, preview_params = sql.observations_select(
            filters, "datetime_utc", "asc", params.preview_limit, 0
        )
        preview = database.fetch_all(preview_sql, preview_params)

    return {
        "selection_id": selection_id,
        "name": params.name,
        "detections": detections,
        "preview": preview,
        "notes": [
            "A selection is a saved filter, not a copy or a deletion.",
            "Downstream endpoints accept the same filters directly.",
        ],
    }


def _normalize(
    database: Database, config: dict[str, Any], params: NormalizeRequest, run_id: str
) -> dict[str, Any]:
    checks = database.fetch_one(
        """
        SELECT
            count(*) AS rows,
            sum(CASE WHEN datetime_utc IS NULL THEN 1 ELSE 0 END) AS null_datetime,
            sum(CASE WHEN frp_mw IS NULL THEN 1 ELSE 0 END) AS null_frp,
            sum(CASE WHEN lat IS NULL OR lon IS NULL THEN 1 ELSE 0 END) AS null_coordinates,
            sum(CASE WHEN platform IS NULL THEN 1 ELSE 0 END) AS null_platform
        FROM observations
        """
    ) or {}
    platforms = database.fetch_all(
        "SELECT sensor, platform, count(*) AS detections FROM observations "
        "GROUP BY sensor, platform ORDER BY sensor, platform"
    )

    report: dict[str, Any] = {
        "checks": {key: int(value or 0) for key, value in checks.items()},
        "platforms": platforms,
        "actions": [],
        "confidence_mapping": {"applied": False, "reason": "Not requested."},
    }

    if params.apply_confidence:
        mapping = (config.get("confidence") or {})
        usable = {
            sensor: values
            for sensor, values in mapping.items()
            if isinstance(values, dict) and values
        }
        if not usable:
            report["confidence_mapping"] = {
                "applied": False,
                "reason": "No verified confidence mapping is configured (Phase 03).",
            }
        else:
            updated = 0
            for sensor, values in usable.items():
                cases = " ".join("WHEN ? THEN ?" for _ in values)
                flat: list[Any] = [item for pair in values.items() for item in pair]
                database.execute(
                    "UPDATE observations SET confidence_class = "
                    f"CASE confidence_raw {cases} ELSE confidence_class END "
                    "WHERE sensor = ?",
                    [*flat, sensor],
                )
                updated += int(
                    database.fetch_scalar(
                        "SELECT count(*) FROM observations WHERE sensor = ?", [sensor]
                    )
                    or 0
                )
            report["confidence_mapping"] = {"applied": True, "rows": updated}
            report["actions"].append("Applied configured confidence mapping.")

    report["notes"] = [
        "Structural normalization (types, zero-padded times, platform mapping) happens at import.",
        "confidence_class stays NULL until an official mapping is verified and configured.",
    ]
    return report


def _load_grid(database: Database, grid_id: str) -> dict[str, Any]:
    grid_sql, grid_params = sql.grid_row(grid_id)
    grid = database.fetch_one(grid_sql, grid_params)
    if grid is None:
        raise ApiError("grid_not_found", f"No grid with id '{grid_id}'.", 404)
    return grid


def _generate_grid(
    database: Database, config: dict[str, Any], params: GridGenerateRequest, run_id: str
) -> dict[str, Any]:
    bounds = params.bbox_tuple
    if bounds is None:
        extent_sql, extent_params = sql.extent({})
        extent = database.fetch_one(extent_sql, extent_params) or {}
        if extent.get("min_lat") is None:
            raise ApiError("empty_dataset", "Cannot derive grid bounds from an empty dataset.", 409)
        min_lon, min_lat, max_lon, max_lat = (
            float(extent["min_lon"]),
            float(extent["min_lat"]),
            float(extent["max_lon"]),
            float(extent["max_lat"]),
        )
    else:
        min_lon, min_lat, max_lon, max_lat = bounds

    try:
        spec, cells = build_grid(min_lat, max_lat, min_lon, max_lon, params.cell_km)
    except ValueError as error:
        raise ApiError("invalid_grid", str(error), 422) from error

    grid_id = f"grid_{uuid.uuid4().hex[:16]}"
    database.execute(
        "INSERT INTO grids (grid_id, name, cell_km, min_lat, max_lat, min_lon, max_lon, "
        "lat_step, lon_step, n_rows, n_cols, mean_lat, area_distortion_pct, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            grid_id,
            params.name or f"{params.cell_km:g}km-grid",
            spec.cell_km,
            spec.min_lat,
            spec.max_lat,
            spec.min_lon,
            spec.max_lon,
            spec.lat_step,
            spec.lon_step,
            spec.n_rows,
            spec.n_cols,
            spec.mean_lat,
            spec.area_distortion_pct,
            job_store.utcnow(),
        ],
    )
    cells = cells.copy()
    cells.insert(0, "grid_id", grid_id)
    database.insert_frame(
        "grid_cells",
        cells,
        (
            "grid_id",
            "cell_id",
            "row_index",
            "col_index",
            "min_lat",
            "max_lat",
            "min_lon",
            "max_lon",
            "center_lat",
            "center_lon",
        ),
    )

    return {
        "grid_id": grid_id,
        "grid": spec.as_dict(),
        "notes": [
            "Cells are sized in km on an equirectangular approximation; area distortion across the extent is reported.",
            "Distances between detections are still computed geodesically, never from the grid.",
        ],
    }


def _spatial_matching(
    database: Database, config: dict[str, Any], params: SpatialMatchRequest, run_id: str
) -> dict[str, Any]:
    frame_sql, frame_params = sql.observations_for_matching(params.as_filters())
    frame = database.fetch_frame(frame_sql, frame_params)

    links, notes = spatial_links(
        frame,
        radius_m=params.radius_m,
        time_window_h=params.time_window_h,
        max_pairs_per_detection=params.max_pairs_per_detection,
        max_links=params.max_links,
    )
    inserted = _store_links(database, run_id, links)
    return {
        "pairs": inserted,
        "truncated": notes["truncated"],
        "criteria": notes["criterion"],
        "sample": links.head(20).to_dict("records"),
        "notes": [
            "Link table only: no detection is removed, merged or labelled duplicate.",
            "Thresholds came from the request; a sensitivity analysis is required before any conclusion (Phase 07).",
            f"At most {params.max_pairs_per_detection} links per MODIS detection are kept.",
        ],
    }


def _temporal_matching(
    database: Database, config: dict[str, Any], params: TemporalMatchRequest, run_id: str
) -> dict[str, Any]:
    frame_sql, frame_params = sql.observations_for_matching(params.as_filters())
    frame = database.fetch_frame(frame_sql, frame_params)

    links, notes = temporal_links(
        frame,
        time_window_h=params.time_window_h,
        max_pairs_per_detection=params.max_pairs_per_detection,
        max_links=params.max_links,
    )
    inserted = _store_links(database, run_id, links)
    return {
        "pairs": inserted,
        "truncated": notes["truncated"],
        "criteria": notes["criterion"],
        "sample": links.head(20).to_dict("records"),
        "notes": [
            "Time-only links: spatial distance is reported but is not a criterion.",
            "No detection is removed or merged.",
        ],
    }


def _store_links(database: Database, run_id: str, links: pd.DataFrame) -> int:
    if links.empty:
        return 0
    stored = links.copy()
    stored.insert(0, "link_id", [f"{run_id}#{index}" for index in range(len(stored))])
    stored.insert(1, "run_id", run_id)
    stored["sensor_a"] = "modis"
    stored["sensor_b"] = "viirs"
    stored["created_at"] = job_store.utcnow()
    columns = (
        "link_id",
        "run_id",
        "sensor_a",
        "sensor_b",
        "observation_a",
        "observation_b",
        "distance_m",
        "delta_t_s",
        "created_at",
    )
    return database.insert_frame("match_links", stored, columns)


def _aggregate(
    database: Database, config: dict[str, Any], params: AggregateRequest, run_id: str
) -> dict[str, Any]:
    grid = _load_grid(database, params.grid_id)
    unit = None if params.time_bucket == "none" else params.time_bucket
    query_sql, query_params = sql.aggregate_cells(params.as_filters(), grid, unit)
    frame = database.fetch_frame(query_sql, query_params)

    if not frame.empty:
        frame = frame.copy()
        frame.insert(0, "run_id", run_id)
        frame.insert(1, "grid_id", grid["grid_id"])
        database.insert_frame("aggregates", frame, AGGREGATE_COLUMNS)

    cells = int(frame["cell_id"].nunique()) if not frame.empty else 0
    return {
        "grid_id": grid["grid_id"],
        "time_bucket": params.time_bucket,
        "rows": int(len(frame)),
        "cells_with_detections": cells,
        "total_detections": int(frame["detections"].sum()) if not frame.empty else 0,
        "sample": frame.head(10).to_dict("records"),
        "notes": [
            "Sensors are aggregated separately; they are never merged into one count.",
            "Mean/median/max FRP are instantaneous power values, never summed into energy.",
        ],
    }


def _features(
    database: Database, config: dict[str, Any], params: FeaturesRequest, run_id: str
) -> dict[str, Any]:
    grid = _load_grid(database, params.grid_id)
    query_sql, query_params = sql.feature_cells(params.as_filters(), grid)
    frame = database.fetch_frame(query_sql, query_params)

    if not frame.empty:
        frame = frame.copy()
        frame.insert(0, "run_id", run_id)
        frame.insert(1, "grid_id", grid["grid_id"])
        database.insert_frame("features", frame, FEATURE_COLUMNS)

    return {
        "grid_id": grid["grid_id"],
        "rows": int(len(frame)),
        "cells_with_detections": int(frame["cell_id"].nunique()) if not frame.empty else 0,
        "total_detections": int(frame["detections"].sum()) if not frame.empty else 0,
        "sample": frame.head(10).to_dict("records"),
        "features": [
            "detections",
            "distinct_days",
            "mean_frp_mw",
            "median_frp_mw",
            "max_frp_mw",
            "day_fraction",
            "night_fraction",
            "first_detection_utc",
            "last_detection_utc",
        ],
        "notes": [
            "Features are computed per sensor and per cell; no cross-sensor feature is fabricated.",
        ],
    }


OPERATIONS = {
    "clean": _clean,
    "filter": _filter,
    "normalize": _normalize,
    "grid": _generate_grid,
    "spatial-matching": _spatial_matching,
    "temporal-matching": _temporal_matching,
    "aggregate": _aggregate,
    "features": _features,
}


def get_grid(database: Database, grid_id: str) -> dict[str, Any]:
    """Return a stored grid."""
    return _load_grid(database, grid_id)


def list_grids(database: Database, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    """List stored grids, newest first."""
    total = int(database.fetch_scalar("SELECT count(*) FROM grids") or 0)
    rows = database.fetch_all(
        "SELECT * FROM grids ORDER BY created_at DESC, grid_id LIMIT ? OFFSET ?",
        [limit, offset],
    )
    return rows, total


def grid_cells(
    database: Database, grid_id: str, limit: int, offset: int
) -> list[dict[str, Any]]:
    """Page through a grid's cells."""
    query_sql, query_params = sql.grid_cells_query(grid_id, limit, offset)
    return database.fetch_all(query_sql, query_params)


def get_run(database: Database, run_id: str) -> dict[str, Any] | None:
    """Return a processing run with its parsed parameters and result."""
    query_sql, query_params = sql.run_row(run_id)
    row = database.fetch_one(query_sql, query_params)
    if row is None:
        return None
    return {
        **row,
        "params": _maybe_json(row.get("params")),
        "result": _maybe_json(row.get("result")),
    }


def _maybe_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value
