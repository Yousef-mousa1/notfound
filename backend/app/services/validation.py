"""Validation service: cross-sensor consistency on matched pairs.

These endpoints quantify how MODIS and VIIRS disagree on pairs that satisfy the
requested radius/time window; they do not measure accuracy against true fire
occurrence. Held-out reference validation against observed VIIRS for 2013 and
2024 is performed offline in the modeling layer, not here.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import numpy as np
import pandas as pd

from harmonizer.quality import (
    bias,
    ks_statistic,
    mae,
    pearson,
    quantile_table,
    rmse,
    spearman,
    summarize,
)
from harmonizer.store import Database
from harmonizer.store import jobs as job_store
from harmonizer.store import sql

from ..errors import ApiError
from ..schemas.validation import ValidationRunRequest
from ..serialization import maybe_json
from .pairs import build_pairs

PAIR_COLUMNS = (
    "run_id",
    "pair_index",
    "observation_a",
    "observation_b",
    "frp_a",
    "frp_b",
    "distance_m",
    "delta_t_s",
    "lat_a",
    "lon_a",
    "lat_b",
    "lon_b",
)

LIMITATIONS = [
    "These are cross-sensor consistency metrics, not accuracy against true fire occurrence.",
    "Offline year-holdout runs against observed VIIRS (2013, 2024) are held-out reference "
    "validation; they are separate from these pairwise consistency metrics.",
    "MODIS is not ground truth; agreement does not prove that either product is correct.",
    "Pairs depend on the matching radius/time window and are not independent samples.",
    "FRP is instantaneous power (MW); no energy is derived.",
]


def _new_run_id() -> str:
    return f"val_{uuid.uuid4().hex[:16]}"


def run(database: Database, request: ValidationRunRequest) -> dict[str, Any]:
    """Build matched pairs, compute consistency metrics and store the snapshot."""
    run_id = _new_run_id()
    database.execute(
        "INSERT INTO validation_runs (run_id, params, status, n_pairs, created_at) "
        "VALUES (?, ?, 'running', 0, ?)",
        [run_id, request.model_dump_json(), job_store.utcnow()],
    )

    try:
        pairs, notes = build_pairs(
            database,
            request.as_filters(),
            radius_m=request.radius_m,
            time_window_h=request.time_window_h,
            max_pairs_per_detection=request.max_pairs_per_detection,
        )
        summary = summarize(
            pairs["frp_a"].to_numpy(dtype="float64"),
            pairs["frp_b"].to_numpy(dtype="float64"),
        )
        metrics = {
            **summary,
            "matching": notes,
            "limitations": [*summary["limitations"], *LIMITATIONS],
        }

        stored = pairs.reset_index(drop=True).copy()
        stored.insert(0, "pair_index", range(len(stored)))
        stored.insert(0, "run_id", run_id)
        database.insert_frame("validation_pairs", stored, PAIR_COLUMNS)

        database.execute(
            "UPDATE validation_runs SET status = 'succeeded', n_pairs = ?, metrics = ?, "
            "finished_at = ? WHERE run_id = ?",
            [
                int(len(stored)),
                json.dumps(metrics, default=str),
                job_store.utcnow(),
                run_id,
            ],
        )
    except Exception:
        database.execute(
            "UPDATE validation_runs SET status = 'failed', finished_at = ? WHERE run_id = ?",
            [job_store.utcnow(), run_id],
        )
        raise

    return {
        "run_id": run_id,
        "status": "succeeded",
        "n_pairs": int(len(stored)),
        "metrics": metrics,
        "matching": notes,
    }


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "params": maybe_json(row.get("params")),
        "metrics": maybe_json(row.get("metrics")),
    }


def list_runs(
    database: Database, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """List validation runs, newest first."""
    total = int(database.fetch_scalar("SELECT count(*) FROM validation_runs") or 0)
    query_sql, query_params = sql.validation_run_list(limit, offset)
    return [_decode(row) for row in database.fetch_all(query_sql, query_params)], total


def get_run(database: Database, run_id: str) -> dict[str, Any] | None:
    """Return one validation run, or ``None``."""
    query_sql, query_params = sql.validation_run(run_id)
    row = database.fetch_one(query_sql, query_params)
    return None if row is None else _decode(row)


def latest(database: Database) -> dict[str, Any] | None:
    """Return the most recent successful validation run, or ``None``."""
    query_sql, query_params = sql.validation_latest_run()
    row = database.fetch_one(query_sql, query_params)
    return None if row is None else _decode(row)


def _resolve_run(database: Database, run_id: str | None) -> dict[str, Any]:
    if run_id:
        row = get_run(database, run_id)
        if row is None:
            raise ApiError(
                "validation_run_not_found", f"No validation run with id '{run_id}'.", 404
            )
        return row

    query_sql, query_params = sql.validation_latest_run()
    row = database.fetch_one(query_sql, query_params)
    if row is None:
        raise ApiError(
            "no_validation_run",
            "No successful validation run exists yet; call POST /validation/run first.",
            409,
        )
    return _decode(row)


def _pairs_for_metrics(
    database: Database, run_id: str | None
) -> tuple[dict[str, Any], pd.DataFrame]:
    run_row = _resolve_run(database, run_id)
    query_sql, query_params = sql.validation_pairs(run_row["run_id"])
    frame = database.fetch_frame(query_sql, query_params)
    if frame.empty:
        raise ApiError(
            "no_pairs",
            "This validation run stored no pairs, so no metric can be computed.",
            409,
        )
    return run_row, frame


def _meta(run_row: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "run_id": run_row["run_id"],
        "n_pairs": int(len(frame)),
        "matching": (run_row.get("metrics") or {}).get("matching"),
        "limitations": LIMITATIONS,
    }


def _arrays(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return (
        frame["frp_a"].to_numpy(dtype="float64"),
        frame["frp_b"].to_numpy(dtype="float64"),
    )


def _log_arrays(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    a, b = _arrays(frame)
    mask = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0)
    return np.log10(a[mask]), np.log10(b[mask])


def _clean(value: float | None) -> float | None:
    if value is None:
        return None
    return None if not np.isfinite(value) else float(value)


def mae_metric(database: Database, run_id: str | None) -> dict[str, Any]:
    """Mean absolute MODIS-vs-VIIRS difference."""
    run_row, frame = _pairs_for_metrics(database, run_id)
    a, b = _arrays(frame)
    log_a, log_b = _log_arrays(frame)
    return {
        **_meta(run_row, frame),
        "metric": "mae",
        "log10_frp": _clean(mae(log_a, log_b)),
        "log10_frp_unit": "dex (orders of magnitude)",
        "raw_mw": _clean(mae(a, b)),
        "raw_mw_unit": "MW",
        "definition": "mean(|MODIS - VIIRS|) across matched pairs; both directions folded into one absolute value.",
        "note": "Cross-sensor consistency on matched pairs, not accuracy against true fire occurrence.",
    }


def rmse_metric(database: Database, run_id: str | None) -> dict[str, Any]:
    """Root mean squared MODIS-vs-VIIRS difference."""
    run_row, frame = _pairs_for_metrics(database, run_id)
    a, b = _arrays(frame)
    log_a, log_b = _log_arrays(frame)
    return {
        **_meta(run_row, frame),
        "metric": "rmse",
        "log10_frp": _clean(rmse(log_a, log_b)),
        "log10_frp_unit": "dex (orders of magnitude)",
        "raw_mw": _clean(rmse(a, b)),
        "raw_mw_unit": "MW",
        "definition": "sqrt(mean((MODIS - VIIRS)^2)) across matched pairs.",
        "note": "The raw-MW RMSE is dominated by the FRP tail; the log10 value is the robust summary.",
        "limitations": [*LIMITATIONS, "Raw-MW RMSE is heavy-tail sensitive."],
    }


def bias_metric(database: Database, run_id: str | None) -> dict[str, Any]:
    """Signed mean difference (MODIS minus VIIRS)."""
    run_row, frame = _pairs_for_metrics(database, run_id)
    a, b = _arrays(frame)
    log_a, log_b = _log_arrays(frame)
    return {
        **_meta(run_row, frame),
        "metric": "bias",
        "log10_frp": _clean(bias(log_a, log_b)),
        "log10_frp_unit": "dex (orders of magnitude)",
        "raw_mw": _clean(bias(a, b)),
        "raw_mw_unit": "MW",
        "definition": "mean(MODIS - VIIRS). Positive means MODIS reports higher values on these pairs.",
        "note": "A non-zero bias is a sample property, not a correction to apply automatically.",
    }


def correlation_metric(database: Database, run_id: str | None) -> dict[str, Any]:
    """Pearson and Spearman association between the two sensors."""
    run_row, frame = _pairs_for_metrics(database, run_id)
    a, b = _arrays(frame)
    log_a, log_b = _log_arrays(frame)
    return {
        **_meta(run_row, frame),
        "metric": "correlation",
        "log10_frp": {
            "pearson_r": _clean(pearson(log_a, log_b)),
            "spearman_rho": _clean(spearman(log_a, log_b)),
        },
        "raw_mw": {
            "pearson_r": _clean(pearson(a, b)),
            "spearman_rho": _clean(spearman(a, b)),
        },
        "definition": "Correlation of paired FRP values; Spearman is rank-based and robust to the tail.",
        "note": "Correlation describes association, not agreement: a constant offset still gives r near 1.",
    }


def distribution(database: Database, run_id: str | None) -> dict[str, Any]:
    """Quantiles of both sensors on the matched pairs, plus a KS statistic."""
    run_row, frame = _pairs_for_metrics(database, run_id)
    a, b = _arrays(frame)
    log_a, log_b = _log_arrays(frame)
    return {
        **_meta(run_row, frame),
        "modis_mw": quantile_table(a),
        "viirs_mw": quantile_table(b),
        "modis_log10_frp": quantile_table(log_a),
        "viirs_log10_frp": quantile_table(log_b),
        "ks_statistic": {
            "raw_mw": _clean(ks_statistic(a, b)),
            "log10_frp": _clean(ks_statistic(log_a, log_b)),
        },
        "definition": "Empirical quantiles and two-sample Kolmogorov-Smirnov statistic on matched pairs.",
        "note": "Distributional agreement on these pairs says nothing about detections that did not pair.",
    }


TEMPORAL_BINS = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 48.0]
TEMPORAL_LABELS = ["0-15m", "15-30m", "30-60m", "1-2h", "2-4h", "4-8h", "8-48h"]
SPATIAL_BINS = [0.0, 250.0, 500.0, 750.0, 1000.0, 1500.0, 2000.0, 3000.0, 5000.0, 100000.0]
SPATIAL_LABELS = [
    "0-250m",
    "250-500m",
    "500-750m",
    "750-1000m",
    "1-1.5km",
    "1.5-2km",
    "2-3km",
    "3-5km",
    "5-100km",
]


def _group_summary(
    frame: pd.DataFrame, column: str, bins: list[float], labels: list[str]
) -> list[dict[str, Any]]:
    values = pd.to_numeric(frame[column], errors="coerce").abs()
    buckets = pd.cut(values, bins=bins, labels=labels, right=True, include_lowest=True)
    rows: list[dict[str, Any]] = []
    for label in labels:
        mask = buckets == label
        subset = frame[mask]
        if subset.empty:
            continue
        log_a, log_b = _log_arrays(subset)
        a, b = _arrays(subset)
        rows.append(
            {
                "bucket": label,
                "n_pairs": int(len(subset)),
                "log10_mae": _clean(mae(log_a, log_b)),
                "log10_rmse": _clean(rmse(log_a, log_b)),
                "log10_bias": _clean(bias(log_a, log_b)),
                "raw_mae_mw": _clean(mae(a, b)),
                "raw_bias_mw": _clean(bias(a, b)),
            }
        )
    return rows


def temporal(database: Database, run_id: str | None) -> dict[str, Any]:
    """Consistency by absolute overpass-time difference."""
    run_row, frame = _pairs_for_metrics(database, run_id)
    frame = frame.copy()
    frame["dt_hours"] = pd.to_numeric(frame["delta_t_s"], errors="coerce") / 3600.0
    return {
        **_meta(run_row, frame),
        "buckets": _group_summary(frame, "dt_hours", TEMPORAL_BINS, TEMPORAL_LABELS),
        "definition": "Metrics recomputed within absolute time-difference buckets.",
        "note": "Larger time differences mix fire growth and movement into the disagreement.",
    }


def spatial(database: Database, run_id: str | None) -> dict[str, Any]:
    """Consistency by geodesic distance between paired detections."""
    run_row, frame = _pairs_for_metrics(database, run_id)
    return {
        **_meta(run_row, frame),
        "buckets": _group_summary(frame, "distance_m", SPATIAL_BINS, SPATIAL_LABELS),
        "definition": "Metrics recomputed within geodesic-distance buckets (metres).",
        "note": "Larger distances make it less likely that both detections describe the same fire.",
    }
