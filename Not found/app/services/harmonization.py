"""Harmonization service: calibration fits and grid-level harmonization.

Every result is a described transformation of matched pairs or of a run's own
per-cell aggregates. MODIS is never used as ground truth, raw FRP values are
never merged across sensors, and no energy is derived.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pandas as pd

from harmonizer.harmonization import fit, fit_none, harmonize_cells
from harmonizer.harmonization.activity import (
    COUNT_WEIGHT,
    FRP_WEIGHT,
    RESULT_COLUMNS,
    SCALE_QUANTILE,
)
from harmonizer.store import Database
from harmonizer.store import jobs as job_store
from harmonizer.store import sql

from ..errors import ApiError
from ..schemas.harmonization import CalibrateRequest, HarmonizationRunRequest
from ..serialization import maybe_json
from .pairs import build_pairs

METHOD_DESCRIPTIONS: tuple[dict[str, Any], ...] = (
    {
        "method": "none",
        "implemented": True,
        "fits_on_matched_pairs": False,
        "description": "Identity transform. Sensors remain on their own scales.",
        "assumptions": ["No cross-sensor rescaling is applied."],
    },
    {
        "method": "ratio",
        "implemented": True,
        "fits_on_matched_pairs": True,
        "description": "Multiplies VIIRS FRP by median(MODIS / VIIRS) over matched pairs.",
        "assumptions": [
            "One multiplicative factor describes the whole sample.",
            "The median makes the factor robust to the FRP tail but ignores FRP magnitude.",
            "Extrapolates outside the matched FRP range.",
        ],
    },
    {
        "method": "linear-regression",
        "implemented": True,
        "fits_on_matched_pairs": True,
        "description": "Ordinary least squares MODIS = intercept + slope * VIIRS.",
        "assumptions": [
            "A linear relation is adequate across the FRP range.",
            "OLS residuals are not independent: pairs share detections.",
            "Extrapolates outside the matched FRP range.",
        ],
    },
    {
        "method": "quantile-mapping",
        "implemented": True,
        "fits_on_matched_pairs": True,
        "description": "Maps the empirical VIIRS FRP distribution onto the MODIS one.",
        "assumptions": [
            "The matched VIIRS distribution is representative of the mapped data.",
            "Values outside the fitted range are clipped by interpolation.",
        ],
    },
    {
        "method": "random-forest",
        "implemented": False,
        "fits_on_matched_pairs": None,
        "description": (
            "Not implemented. Requires labelled training data and a spatial/temporal "
            "validation strategy; MODIS is not ground truth."
        ),
        "assumptions": [],
    },
)


def _new_run_id() -> str:
    return f"harm_{uuid.uuid4().hex[:16]}"


def methods() -> list[dict[str, Any]]:
    """Describe the supported calibration methods."""
    return [dict(item) for item in METHOD_DESCRIPTIONS]


def _grid(database: Database, grid_id: str) -> dict[str, Any]:
    grid_sql, grid_params = sql.grid_row(grid_id)
    grid = database.fetch_one(grid_sql, grid_params)
    if grid is None:
        raise ApiError("grid_not_found", f"No grid with id '{grid_id}'.", 404)
    return grid


def _calibration_limitations(notes: dict[str, Any]) -> list[str]:
    return [
        "Fitted on matched MODIS/VIIRS pairs: MODIS is not ground truth.",
        "Pairs depend on the matching radius/time window and are not independent samples.",
        f"Matching criterion: {notes.get('criterion', 'not reported')}.",
        "The transform describes this sample; it is not a physical correction.",
        "FRP is instantaneous power (MW); no energy is derived.",
    ]


def calibrate(
    database: Database, method: str, request: CalibrateRequest
) -> dict[str, Any]:
    """Fit a calibration on matched pairs and record it as a run."""
    if method == "random-forest":
        raise NotImplementedError(
            "random-forest is not implemented: it requires labelled training data and "
            "a spatial/temporal validation strategy. MODIS is not ground truth."
        )

    pairs, notes = build_pairs(
        database,
        request.as_filters(),
        radius_m=request.radius_m,
        time_window_h=request.time_window_h,
        max_pairs_per_detection=request.max_pairs_per_detection,
    )
    try:
        fitted = fit(method, pairs["frp_a"].to_numpy(), pairs["frp_b"].to_numpy())
    except ValueError as error:
        raise ApiError("calibration_failed", str(error), 409) from error

    run_id = _new_run_id()
    now = job_store.utcnow()
    database.execute(
        "INSERT INTO harmonization_runs (run_id, method, params, status, calibration, "
        "n_pairs, n_cells, created_at, finished_at) VALUES (?, ?, ?, 'calibrated', ?, ?, 0, ?, ?)",
        [
            run_id,
            method,
            request.model_dump_json(),
            json.dumps(fitted.as_dict(), default=str),
            fitted.n_pairs,
            now,
            now,
        ],
    )

    return {
        "run_id": run_id,
        "method": method,
        "calibration": fitted.as_dict(),
        "matching": notes,
        "limitations": _calibration_limitations(notes),
    }


def _aggregate_frame(
    database: Database, grid: dict[str, Any], request: HarmonizationRunRequest
) -> pd.DataFrame:
    unit = None if request.time_bucket == "none" else request.time_bucket
    query_sql, query_params = sql.aggregate_cells(request.as_filters(), grid, unit)
    frame = database.fetch_frame(query_sql, query_params)
    if frame.empty:
        raise ApiError(
            "no_observations",
            "No observations match the requested filters, so there is nothing to harmonize.",
            409,
        )
    return frame


def run(database: Database, request: HarmonizationRunRequest) -> dict[str, Any]:
    """Fit an optional calibration and write per-cell harmonized results."""
    grid = _grid(database, request.grid_id)
    run_id = _new_run_id()
    now = job_store.utcnow()
    database.execute(
        "INSERT INTO harmonization_runs (run_id, method, params, status, n_pairs, n_cells, "
        "created_at) VALUES (?, ?, ?, 'running', 0, 0, ?)",
        [run_id, request.method, request.model_dump_json(), now],
    )

    try:
        matching_notes: dict[str, Any] | None = None
        if request.method == "none":
            fitted = fit_none()
        else:
            pairs, matching_notes = build_pairs(
                database,
                request.as_filters(),
                radius_m=float(request.radius_m or 0.0),
                time_window_h=request.time_window_h,
                max_pairs_per_detection=request.max_pairs_per_detection,
            )
            try:
                fitted = fit(
                    request.method,
                    pairs["frp_a"].to_numpy(),
                    pairs["frp_b"].to_numpy(),
                )
            except ValueError as error:
                raise ApiError("calibration_failed", str(error), 409) from error

        aggregates = _aggregate_frame(database, grid, request)
        results, result_meta = harmonize_cells(aggregates, fitted)

        stored = results.copy()
        stored.insert(0, "run_id", run_id)
        database.insert_frame(
            "harmonization_results", stored, ("run_id", *RESULT_COLUMNS)
        )

        totals = aggregates.groupby("sensor")["detections"].sum().to_dict()
        calibration = fitted.as_dict()
        database.execute(
            "UPDATE harmonization_runs SET status = 'succeeded', calibration = ?, "
            "n_pairs = ?, n_cells = ?, finished_at = ? WHERE run_id = ?",
            [
                json.dumps(calibration, default=str),
                fitted.n_pairs,
                int(len(results)),
                job_store.utcnow(),
                run_id,
            ],
        )
    except Exception:
        database.execute(
            "UPDATE harmonization_runs SET status = 'failed', finished_at = ? WHERE run_id = ?",
            [job_store.utcnow(), run_id],
        )
        raise

    sample = (
        results.sort_values("harmonized_activity_index", ascending=False)
        .head(10)
        .to_dict("records")
    )
    index_values = results["harmonized_activity_index"].dropna()
    return {
        "run_id": run_id,
        "method": request.method,
        "grid_id": grid["grid_id"],
        "time_bucket": request.time_bucket,
        "n_pairs": fitted.n_pairs,
        "n_cells": int(len(results)),
        "cells_with_both_sensors": int((results["sensors_present"] == 2).sum()),
        "detections": {str(sensor): int(count) for sensor, count in totals.items()},
        "index_stats": {
            "mean": float(index_values.mean()) if len(index_values) else None,
            "median": float(index_values.median()) if len(index_values) else None,
            "max": float(index_values.max()) if len(index_values) else None,
        },
        "calibration": calibration,
        "matching": matching_notes,
        "index_definition": result_meta,
        "sample": sample,
        "notes": [
            "No observation is deleted or merged; only new harmonized rows are written.",
            "Only cells/time buckets with detections are returned; absence is not evidence of no fire.",
        ],
    }


def list_runs(
    database: Database, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """List harmonization runs, newest first."""
    total = int(database.fetch_scalar("SELECT count(*) FROM harmonization_runs") or 0)
    query_sql, query_params = sql.harmonization_run_list(limit, offset)
    rows = database.fetch_all(query_sql, query_params)
    return [get_run_fields(row) for row in rows], total


def get_run_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Decode JSON columns of a stored harmonization run."""
    return {
        **row,
        "params": maybe_json(row.get("params")),
        "calibration": maybe_json(row.get("calibration")),
    }


def get_run(database: Database, run_id: str) -> dict[str, Any] | None:
    """Return one harmonization run, or ``None``."""
    query_sql, query_params = sql.harmonization_run(run_id)
    row = database.fetch_one(query_sql, query_params)
    return None if row is None else get_run_fields(row)


def _require_run(database: Database, run_id: str) -> dict[str, Any]:
    run_row = get_run(database, run_id)
    if run_row is None:
        raise ApiError(
            "harmonization_run_not_found", f"No harmonization run with id '{run_id}'.", 404
        )
    return run_row


def latest_successful(database: Database) -> dict[str, Any] | None:
    """Most recent successful harmonization run."""
    row = database.fetch_one(
        "SELECT * FROM harmonization_runs WHERE status = 'succeeded' "
        "ORDER BY created_at DESC, run_id LIMIT 1"
    )
    return None if row is None else get_run_fields(row)


def _resolve_run(database: Database, run_id: str | None) -> dict[str, Any]:
    if run_id:
        return _require_run(database, run_id)
    latest = latest_successful(database)
    if latest is None:
        raise ApiError(
            "no_harmonization_run",
            "No successful harmonization run exists yet; call POST /harmonization/run first.",
            409,
        )
    return latest


def results(
    database: Database, run_id: str, limit: int, offset: int, order_by_index: bool
) -> tuple[list[dict[str, Any]], int]:
    """Page through a run's per-cell results."""
    _require_run(database, run_id)
    count_sql, count_params = sql.harmonization_result_count(run_id)
    total = int(database.fetch_scalar(count_sql, count_params) or 0)
    query_sql, query_params = sql.harmonization_results(
        run_id, limit, offset, order_by_index
    )
    return database.fetch_all(query_sql, query_params), total


def comparison(database: Database, run_id: str | None) -> dict[str, Any]:
    """Compare sensor behaviour and the harmonized index within a run."""
    run_row = _resolve_run(database, run_id)
    query_sql, query_params = sql.harmonization_comparison(run_row["run_id"])
    row = database.fetch_one(query_sql, query_params) or {}
    if not row.get("rows"):
        raise ApiError(
            "no_results",
            "This run has no per-cell results (it may be a calibration-only run).",
            409,
        )
    return {
        "run_id": run_row["run_id"],
        "method": run_row["method"],
        "time_bucket": (run_row.get("params") or {}).get("time_bucket"),
        "summary": row,
        "notes": [
            "MODIS and VIIRS counts are reported side by side; they are never summed as one detection count.",
            "Mean FRP values are instantaneous power (MW), not energy.",
            "The harmonized index is unitless and relative to this run's own p95 scales.",
        ],
    }


def uncertainty(database: Database, run_id: str | None) -> dict[str, Any]:
    """Coverage and per-cell FRP disagreement for a run."""
    run_row = _resolve_run(database, run_id)
    query_sql, query_params = sql.harmonization_coverage(run_row["run_id"])
    rows = database.fetch_all(query_sql, query_params)
    if not rows:
        raise ApiError(
            "no_results",
            "This run has no per-cell results (it may be a calibration-only run).",
            409,
        )
    calibration = run_row.get("calibration") or {}
    return {
        "run_id": run_row["run_id"],
        "method": run_row["method"],
        "coverage": rows,
        "calibration_rmse_mw": calibration.get("rmse_mw"),
        "calibration_n_pairs": calibration.get("n_pairs"),
        "definition": (
            "Per cell: absolute difference between MODIS mean FRP and calibrated VIIRS "
            "mean FRP when both are present, else null. The coverage table shows how many "
            "cells fall into each sensors_present group."
        ),
        "limitations": [
            "This is cross-sensor disagreement, not measurement error: neither sensor is truth.",
            "Cells with one sensor carry no cross-sensor uncertainty and are reported separately.",
            "Group means are unweighted across cells and time buckets.",
        ],
    }


def activity_index(
    database: Database, run_id: str | None, limit: int, offset: int
) -> dict[str, Any]:
    """Rank cells by the harmonized index and restate its formula."""
    run_row = _resolve_run(database, run_id)
    query_sql, query_params = sql.harmonization_results(
        run_row["run_id"], limit, offset, True
    )
    rows = database.fetch_all(query_sql, query_params)
    count_sql, count_params = sql.harmonization_result_count(run_row["run_id"])
    total = int(database.fetch_scalar(count_sql, count_params) or 0)
    if total == 0:
        raise ApiError(
            "no_results",
            "This run has no per-cell results (it may be a calibration-only run).",
            409,
        )

    scales = database.fetch_one(
        """
        SELECT
            quantile_cont(modis_count, ?) AS modis_count,
            quantile_cont(modis_mean_frp_mw, ?) AS modis_mean_frp_mw,
            quantile_cont(viirs_count, ?) AS viirs_count,
            quantile_cont(viirs_mean_frp_calibrated_mw, ?) AS viirs_mean_frp_calibrated_mw
        FROM harmonization_results WHERE run_id = ?
        """,
        [SCALE_QUANTILE, SCALE_QUANTILE, SCALE_QUANTILE, SCALE_QUANTILE, run_row["run_id"]],
    ) or {}

    calibration = run_row.get("calibration") or {}
    return {
        "run_id": run_row["run_id"],
        "method": run_row["method"],
        "formula": (
            "sensor_index = 0.5 * min(1, count / p95(count)) "
            "+ 0.5 * min(1, mean_frp / p95(mean_frp)); "
            "harmonized_activity_index = equal-weight mean of the sensor indices present"
        ),
        "weights": {"count": COUNT_WEIGHT, "frp": FRP_WEIGHT},
        "scale_quantile": SCALE_QUANTILE,
        "scales": {
            "modis_count": scales.get("modis_count"),
            "modis_mean_frp_mw": scales.get("modis_mean_frp_mw"),
            "viirs_count": scales.get("viirs_count"),
            "viirs_mean_frp_calibrated_mw": scales.get("viirs_mean_frp_calibrated_mw"),
            "note": "p95 scales are computed over the whole run, not over this page.",
        },
        "calibration_method": calibration.get("method", run_row["method"]),
        "results": rows,
        "total": total,
        "limitations": [
            "Unitless and relative to this run's p95 scales; not a physical quantity.",
            "One-sensor cells can reach 1.0; check sensors_present.",
            "FRP normalization starts from the cell mean, so a non-linear calibration is applied to that mean, not to every detection.",
            "No FRP is summed across sensors and no energy is derived.",
        ],
    }


def map_cells(
    database: Database,
    run_id: str | None,
    both_only: bool,
    limit: int,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a run's cell-day results as map points, with grid cell centres.

    Each point is a 25 km cell-day, not a detection: the coordinates are the
    grid cell centre and several points can share the same cell on different
    days.
    """
    run_row = _resolve_run(database, run_id)
    params = run_row.get("params") or {}
    grid_id = params.get("grid_id")
    if not grid_id:
        raise ApiError(
            "no_grid",
            "This harmonization run is not attached to a grid, so it has no map geometry.",
            409,
        )

    query_sql, query_params = sql.harmonized_map_points(
        run_row["run_id"], grid_id, both_only, limit, offset
    )
    rows = database.fetch_all(query_sql, query_params)
    count_sql, count_params = sql.harmonized_map_point_count(
        run_row["run_id"], grid_id, both_only
    )
    total = int(database.fetch_scalar(count_sql, count_params) or 0)

    return {
        "run_id": run_row["run_id"],
        "grid_id": grid_id,
        "both_sensors_only": both_only,
        "total": total,
        "returned": len(rows),
        "cells": rows,
        "notes": [
            "Each point is a grid cell-day (cell centre), not a detection.",
            "sensors_present = 2 means MODIS and VIIRS both reported in that cell-day; "
            "1 means only one sensor did.",
            "The harmonized index is unitless and relative to this run's own p95 scales.",
            "Points are ordered by the harmonized index, so a bounded sample keeps the strongest cells.",
        ],
    }
