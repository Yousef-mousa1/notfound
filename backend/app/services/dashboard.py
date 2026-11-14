"""Dashboard service: compact payloads reusing already-computed outputs.

Nothing new is computed here beyond aggregation of stored results. Panels that
depend on an optional run report ``available: false`` instead of inventing data.
"""

from __future__ import annotations

from typing import Any

from harmonizer.store import Database
from harmonizer.store import sql

from ..errors import ApiError
from ..schemas.analytics import AnalyticsQuery
from ..schemas.anomalies import AnomalyQuery
from . import analytics, anomalies, harmonization, observations, validation


def overview(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Main summary panel."""
    stats = observations.statistics(database, query)
    anomaly_run = anomalies.latest_run(database)
    harmonization_run = harmonization.latest_successful(database)
    validation_run = validation.latest(database)

    return {
        "observations": stats["overall"],
        "per_sensor": stats["per_sensor"],
        "anomalies": _run_brief(anomaly_run, "n_anomalies"),
        "harmonization": _run_brief(harmonization_run, "n_cells"),
        "validation": (
            {
                "available": True,
                "run_id": validation_run["run_id"],
                "n_pairs": validation_run.get("n_pairs"),
            }
            if validation_run
            else {"available": False}
        ),
        "notes": [
            "Detections only: absence of a row does not mean no fire.",
            "Sensors are never merged into one count.",
        ],
    }


def _run_brief(run_row: dict[str, Any] | None, count_key: str) -> dict[str, Any]:
    if run_row is None:
        return {"available": False}
    return {
        "available": True,
        "run_id": run_row["run_id"],
        "count": run_row.get(count_key),
        "created_at": run_row.get("created_at"),
    }


def map_payload(database: Database, query: AnalyticsQuery, limit: int) -> dict[str, Any]:
    """Map points for observations and, when available, anomalies."""
    points = observations.map_points(database, query, limit)
    anomaly_run = anomalies.latest_run(database)
    anomaly_points: list[dict[str, Any]] = []
    if anomaly_run:
        anomaly_query = AnomalyQuery(run_id=anomaly_run["run_id"], limit=limit)
        anomaly_points = anomalies.map_points(database, anomaly_query)

    return {
        "observations": points,
        "anomalies": anomaly_points,
        "anomaly_run_id": anomaly_run["run_id"] if anomaly_run else None,
        "notes": [
            "Observation points are a bounded sample, not the full dataset.",
            "Anomaly points are flagged cell-days, not individual detections.",
        ],
    }


def calendar(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Daily detection counts per sensor for a calendar view."""
    scoped = query.model_copy(update={"granularity": "day"})
    return {
        "series": observations.by_date(database, scoped),
        "notes": ["One row per date and sensor; missing dates mean no detections in the source."],
    }


def anomaly_panel(database: Database) -> dict[str, Any]:
    """Anomaly panel based on the latest successful run."""
    run_row = anomalies.latest_run(database)
    if run_row is None:
        return {
            "available": False,
            "reason": "No successful anomaly run exists; call POST /anomalies/detect.",
        }

    scoped = AnomalyQuery(run_id=run_row["run_id"])
    top_cells, _ = anomalies.by_region(database, scoped)
    return {
        "available": True,
        "statistics": anomalies.statistics(database, scoped),
        "by_date": anomalies.by_date(database, scoped),
        "severity": anomalies.severity(database, scoped),
        "top_cells": top_cells,
    }


def trends(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Daily and monthly trend payloads."""
    daily_query = query.model_copy(update={"granularity": "day"})
    monthly_query = query.model_copy(update={"granularity": "month"})
    return {
        "daily": observations.by_date(database, daily_query),
        "monthly": observations.by_date(database, monthly_query),
        "notes": [
            "FRP columns are instantaneous power (MW); no energy is derived.",
            "Counts are per sensor and never merged.",
        ],
    }


def sensor_comparison(database: Database, query: AnalyticsQuery) -> dict[str, Any]:
    """Side-by-side sensor panel."""
    return analytics.sensor_comparison(database, query)


def activity_index(
    database: Database, query: AnalyticsQuery, limit: int
) -> dict[str, Any]:
    """Top harmonized cells from the latest successful run."""
    run_row = harmonization.latest_successful(database)
    if run_row is None:
        raise ApiError(
            "no_harmonization_run",
            "No successful harmonization run exists; call POST /harmonization/run first.",
            409,
        )

    results_sql, results_params = sql.harmonization_results(
        run_row["run_id"], limit, 0, True
    )
    summary_sql, summary_params = sql.harmonization_comparison(run_row["run_id"])
    return {
        "run_id": run_row["run_id"],
        "method": run_row["method"],
        "summary": database.fetch_one(summary_sql, summary_params) or {},
        "cells": database.fetch_all(results_sql, results_params),
        "notes": [
            "Unitless index relative to the run's own p95 scales.",
            "One-sensor cells can reach 1.0; check sensors_present.",
            "No FRP is summed across sensors and no energy is derived.",
        ],
    }
