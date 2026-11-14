"""Anomaly detection service: statistical runs and result queries."""

from __future__ import annotations

import json
import uuid
from typing import Any

from harmonizer.anomaly import Thresholds, detect
from harmonizer.anomaly.detect import ANOMALY_COLUMNS
from harmonizer.store import Database
from harmonizer.store import jobs as job_store
from harmonizer.store import sql

from ..errors import ApiError
from ..schemas.anomalies import AnomalyDetectRequest, AnomalyQuery
from ..serialization import maybe_json
from . import processing as processing_service

SEVERITY_DEFINITIONS = {
    "moderate": "robust z at or above the run threshold and below 5",
    "high": "robust z between 5 and 7",
    "extreme": "robust z at or above 7",
}


def _new_run_id() -> str:
    return f"anom_{uuid.uuid4().hex[:16]}"


def run(database: Database, request: AnomalyDetectRequest) -> dict[str, Any]:
    """Detect daily-count anomalies and store the flagged rows."""
    grid = processing_service.get_grid(database, request.grid_id)
    query_sql, query_params = sql.cell_daily_counts(request.as_filters(), grid)
    frame = database.fetch_frame(query_sql, query_params)
    if frame.empty:
        raise ApiError(
            "no_observations",
            "No observations with a timestamp match the requested filters.",
            409,
        )

    thresholds = Thresholds(
        min_days=request.min_days,
        min_detections=request.min_detections,
        threshold=request.threshold,
    )
    flagged, stats = detect(frame, thresholds)

    run_id = _new_run_id()
    database.execute(
        "INSERT INTO anomaly_runs (run_id, params, status, grid_id, n_cells_total, "
        "n_cells_evaluated, n_cell_days, n_anomalies, created_at) "
        "VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?)",
        [
            run_id,
            request.model_dump_json(),
            grid["grid_id"],
            stats.n_cells_total,
            stats.n_cells_evaluated,
            stats.n_cell_days,
            stats.n_anomalies,
            job_store.utcnow(),
        ],
    )

    try:
        if not flagged.empty:
            stored = flagged.copy()
            stored.insert(0, "run_id", run_id)
            stored.insert(1, "anomaly_id", [f"{run_id}-{i:05d}" for i in range(len(stored))])
            database.insert_frame("anomalies", stored, ("run_id", "anomaly_id", *ANOMALY_COLUMNS))
        database.execute(
            "UPDATE anomaly_runs SET status = 'succeeded', "
            "n_cells_total = ?, n_cells_evaluated = ?, n_cell_days = ?, "
            "n_anomalies = ?, finished_at = ? WHERE run_id = ?",
            [
                stats.n_cells_total,
                stats.n_cells_evaluated,
                stats.n_cell_days,
                stats.n_anomalies,
                job_store.utcnow(),
                run_id,
            ],
        )
    except Exception:
        database.execute(
            "UPDATE anomaly_runs SET status = 'failed', finished_at = ? WHERE run_id = ?",
            [job_store.utcnow(), run_id],
        )
        raise

    return {
        "run_id": run_id,
        "grid_id": grid["grid_id"],
        "method": "robust modified z-score on daily per-cell detection counts",
        "thresholds": thresholds.as_dict(),
        "stats": stats.as_dict(),
        "sample": flagged.sort_values("robust_z", ascending=False).head(10).to_dict("records"),
        "notes": [
            "Sensors are evaluated separately; MODIS and VIIRS counts are never merged.",
            "A flagged day is a statistical outlier, not a confirmed fire event.",
            "Cells with short or flat series have no baseline and are reported as skipped.",
            "The source data contains detections only; normal days without detections are not observed here.",
        ],
        "limitations": [
            "Daily counts inherit detection gaps (clouds, overpass timing, sensor outages).",
            "Parameters are request-controlled; no sensitivity analysis is implied by one run.",
            "MODIS and VIIRS have different detection rates, so their baseline scales differ.",
        ],
    }


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "params": maybe_json(row.get("params"))}


def get_run(database: Database, run_id: str) -> dict[str, Any] | None:
    """Return one anomaly run, or ``None``."""
    query_sql, query_params = sql.anomaly_run(run_id)
    row = database.fetch_one(query_sql, query_params)
    return None if row is None else _decode(row)


def latest_run(database: Database) -> dict[str, Any] | None:
    """Return the most recent successful anomaly run, or ``None``."""
    query_sql, query_params = sql.anomaly_latest_run()
    row = database.fetch_one(query_sql, query_params)
    return None if row is None else _decode(row)


def _resolve_run(database: Database, run_id: str | None) -> dict[str, Any]:
    if run_id:
        row = get_run(database, run_id)
        if row is None:
            raise ApiError(
                "anomaly_run_not_found", f"No anomaly run with id '{run_id}'.", 404
            )
        return row

    latest = latest_run(database)
    if latest is None:
        raise ApiError(
            "no_anomaly_run",
            "No successful anomaly run exists yet; call POST /anomalies/detect first.",
            409,
        )
    return latest


def _filters(query: AnomalyQuery) -> dict[str, Any]:
    filters = query.as_filters()
    filters["severity"] = query.severity
    return filters


def list_anomalies(
    database: Database, query: AnomalyQuery
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Page through flagged anomalies."""
    run_row = _resolve_run(database, query.run_id)
    filters = _filters(query)
    count_sql, count_params = sql.anomalies_count(run_row["run_id"], filters)
    total = int(database.fetch_scalar(count_sql, count_params) or 0)
    query_sql, query_params = sql.anomalies_list(
        run_row["run_id"], filters, query.limit, query.offset
    )
    return database.fetch_all(query_sql, query_params), total, run_row


def get_anomaly(database: Database, anomaly_id: str) -> dict[str, Any] | None:
    """Return one anomaly, including its run parameters."""
    query_sql, query_params = sql.anomaly_by_id(anomaly_id)
    row = database.fetch_one(query_sql, query_params)
    if row is None:
        return None
    run_row = get_run(database, row["run_id"])
    return {**row, "run": run_row}


def statistics(database: Database, query: AnomalyQuery) -> dict[str, Any]:
    """Overall, per-sensor and per-severity anomaly statistics."""
    run_row = _resolve_run(database, query.run_id)
    filters = _filters(query)
    summary_sql, summary_params = sql.anomalies_statistics(run_row["run_id"], filters)
    sensor_sql, sensor_params = sql.anomalies_by_sensor(run_row["run_id"], filters)
    severity_sql, severity_params = sql.anomalies_by_severity(run_row["run_id"], filters)

    return {
        "run_id": run_row["run_id"],
        "thresholds": (run_row.get("params") or {}),
        "overall": database.fetch_one(summary_sql, summary_params) or {},
        "per_sensor": database.fetch_all(sensor_sql, sensor_params),
        "per_severity": database.fetch_all(severity_sql, severity_params),
        "evaluation": {
            "series_total": run_row.get("n_cells_total"),
            "series_evaluated": run_row.get("n_cells_evaluated"),
            "cell_days_evaluated": run_row.get("n_cell_days"),
            "anomalies": run_row.get("n_anomalies"),
            "series_basis": "one series per (grid cell, sensor)",
        },
        "severity_definitions": SEVERITY_DEFINITIONS,
        "limitations": [
            "Statistical outliers, not confirmed fire events.",
            "Daily counts inherit observation gaps.",
        ],
    }


def by_region(
    database: Database, query: AnomalyQuery
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Anomaly counts per grid cell and sensor."""
    run_row = _resolve_run(database, query.run_id)
    query_sql, query_params = sql.anomalies_by_region(
        run_row["run_id"], _filters(query), query.limit
    )
    return database.fetch_all(query_sql, query_params), run_row


def by_date(database: Database, query: AnomalyQuery) -> list[dict[str, Any]]:
    """Anomaly counts per day and sensor."""
    run_row = _resolve_run(database, query.run_id)
    query_sql, query_params = sql.anomalies_by_day(run_row["run_id"], _filters(query))
    return database.fetch_all(query_sql, query_params)


def map_points(database: Database, query: AnomalyQuery) -> list[dict[str, Any]]:
    """Map payload for flagged anomalies."""
    run_row = _resolve_run(database, query.run_id)
    query_sql, query_params = sql.anomalies_map(
        run_row["run_id"], _filters(query), query.limit
    )
    return database.fetch_all(query_sql, query_params)


def severity(database: Database, query: AnomalyQuery) -> dict[str, Any]:
    """Severity counts and definitions for a run."""
    run_row = _resolve_run(database, query.run_id)
    query_sql, query_params = sql.anomalies_by_severity(
        run_row["run_id"], _filters(query)
    )
    return {
        "run_id": run_row["run_id"],
        "bands": database.fetch_all(query_sql, query_params),
        "definitions": SEVERITY_DEFINITIONS,
        "parameters": (run_row.get("params") or {}),
    }
