"""Model-produced estimates service.

This is the hand-off layer between the offline ``modeling/`` package and the
API. It only reads files that the modeling layer wrote; it never derives an
estimate from observations and never writes into ``observations``.

MODIS is not ground truth, so every estimate keeps its scale, its correction
flag and its run id. An imported series is immutable: re-importing the same
run ignores duplicate keys instead of overwriting them.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from harmonizer.config import project_root, resolve_path
from harmonizer.store import Database
from harmonizer.store import jobs as job_store

from ..errors import ApiError
from ..serialization import maybe_json
from ..schemas.estimates import (
    SCALES,
    EstimateQuery,
    EstimatesImportRequest,
    ModelRunCreate,
)

ESTIMATE_COLUMNS: tuple[str, ...] = (
    "run_id",
    "level",
    "entity_id",
    "period",
    "scale",
    "value",
    "low",
    "high",
    "centroid_lat",
    "centroid_lon",
    "grid_degrees",
    "is_estimate",
    "coverage_corrected",
    "scale_factor",
    "baseline",
    "model",
)

REQUIRED_SOURCE_COLUMNS: frozenset[str] = frozenset(
    {"region", "year", "month", "scale", "detections", "is_estimate", "coverage_corrected"}
)

OPTIONAL_SOURCE_COLUMNS: dict[str, str] = {
    "low": "low",
    "high": "high",
    "centroid_lat": "region_lat",
    "centroid_lon": "region_lon",
    "grid_degrees": "region_deg",
    "scale_factor": "scale_factor",
    "baseline": "baseline",
    "model": "model",
}


def _new_run_id() -> str:
    return f"est_{uuid.uuid4().hex[:16]}"


def _deserialize_run(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a run row with its stored JSON columns parsed."""
    if row is None:
        return None
    return {
        **row,
        "trained_years": maybe_json(row.get("trained_years")),
        "metrics": maybe_json(row.get("metrics")),
    }


def register_run(database: Database, request: ModelRunCreate) -> dict[str, Any]:
    """Store the provenance of a modeling run before its series is imported."""
    run_id = request.run_id or _new_run_id()
    existing = get_run(database, run_id)
    if existing is not None:
        raise ApiError(
            "model_run_exists",
            f"Model run '{run_id}' is already registered.",
            409,
            {"run_id": run_id},
        )

    database.execute(
        """
        INSERT INTO model_runs (
            run_id, model_name, method, trained_years, test_year,
            validation_split, metrics, source_path, artifact_path, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id,
            request.model_name,
            request.method,
            json.dumps(request.trained_years) if request.trained_years is not None else None,
            request.test_year,
            request.validation_split,
            json.dumps(request.metrics) if request.metrics is not None else None,
            None,
            request.artifact_path,
            request.notes,
            job_store.utcnow(),
        ],
    )
    row = get_run(database, run_id)
    assert row is not None
    return row


def _resolve_source(config: dict[str, Any], path: str) -> Path:
    """Resolve an estimate source path and refuse anything outside allowed roots.

    Allowed roots are the project directory plus the configured raw, upload and
    estimate directories. This mirrors ``ingestion._resolve_input``: without a
    ``resolve()`` + containment check, an absolute or ``../`` path could read any
    ``.csv``/``.parquet`` on the server through ``/estimates/import``. Tests point
    the configured roots at temporary directories.
    """
    candidate = Path(path).expanduser()
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (project_root() / candidate).resolve()
    )

    roots = {project_root().resolve()}
    for keys in (("paths", "raw"), ("paths", "uploads"), ("paths", "estimates")):
        try:
            roots.add(resolve_path(config, *keys).resolve())
        except (KeyError, ValueError):
            continue

    if not any(resolved.is_relative_to(root) for root in roots):
        raise ApiError(
            "path_outside_allowed_root",
            "Estimate source must resolve inside the project, raw, upload or estimates directory.",
            400,
        )
    if not resolved.is_file():
        raise ApiError(
            "estimate_source_not_found",
            "Estimate source file does not exist.",
            404,
        )
    if resolved.suffix.lower() not in {".parquet", ".csv"}:
        raise ApiError(
            "unsupported_estimate_source",
            "Only .parquet and .csv files produced by src/harmonize.py can be imported.",
            415,
        )
    return resolved


def import_series(
    database: Database, config: dict[str, Any], request: EstimatesImportRequest
) -> dict[str, Any]:
    """Load one harmonized series into ``estimates`` without touching observations."""
    run_row = get_run(database, request.run_id)
    if run_row is None:
        raise ApiError(
            "model_run_not_found",
            f"No model run with id '{request.run_id}'. Register it first.",
            404,
        )

    path = _resolve_source(config, request.path)
    reader = "read_parquet(?)" if path.suffix.lower() == ".parquet" else "read_csv_auto(?)"

    described = database.fetch_all(f"DESCRIBE SELECT * FROM {reader}", [str(path)])
    available = {str(row["column_name"]) for row in described}
    missing = sorted(REQUIRED_SOURCE_COLUMNS - available)
    if missing:
        raise ApiError(
            "estimate_source_invalid",
            "Estimate source is missing required columns.",
            422,
            {"missing_columns": missing},
        )

    def source_or_null(target: str) -> str:
        column = OPTIONAL_SOURCE_COLUMNS[target]
        if column in available:
            return f'CAST("{column}" AS DOUBLE)' if target in {
                "low", "high", "centroid_lat", "centroid_lon", "grid_degrees", "scale_factor"
            } else f'CAST("{column}" AS VARCHAR)'
        return "NULL"

    select_columns = ", ".join(
        [
            "? AS run_id",
            "? AS level",
            "CAST(region AS VARCHAR) AS entity_id",
            "make_date(CAST(year AS INTEGER), CAST(month AS INTEGER), 1) AS period",
            "CAST(scale AS VARCHAR) AS scale",
            "CAST(detections AS DOUBLE) AS value",
            f"{source_or_null('low')} AS low",
            f"{source_or_null('high')} AS high",
            f"{source_or_null('centroid_lat')} AS centroid_lat",
            f"{source_or_null('centroid_lon')} AS centroid_lon",
            f"{source_or_null('grid_degrees')} AS grid_degrees",
            "CAST(is_estimate AS BOOLEAN) AS is_estimate",
            "CAST(coverage_corrected AS BOOLEAN) AS coverage_corrected",
            f"{source_or_null('scale_factor')} AS scale_factor",
            f"{source_or_null('baseline')} AS baseline",
            f"{source_or_null('model')} AS model",
        ]
    )
    target_columns = ", ".join(ESTIMATE_COLUMNS)

    source_scales = {
        str(row["scale"])
        for row in database.fetch_all(f"SELECT DISTINCT CAST(scale AS VARCHAR) AS scale FROM {reader}", [str(path)])
    }
    bad_scales = sorted(source_scales - set(SCALES))
    if bad_scales:
        raise ApiError(
            "estimate_unknown_scale",
            "Estimate source contains an unknown scale value.",
            422,
            {"scales": bad_scales, "allowed": list(SCALES)},
        )

    before = int(
        database.fetch_scalar("SELECT count(*) FROM estimates WHERE run_id = ?", [request.run_id])
        or 0
    )
    database.execute(
        f"INSERT OR IGNORE INTO estimates ({target_columns}) "
        f"SELECT {select_columns} FROM {reader}",
        [request.run_id, request.level, str(path)],
    )
    after = int(
        database.fetch_scalar("SELECT count(*) FROM estimates WHERE run_id = ?", [request.run_id])
        or 0
    )
    database.execute(
        "UPDATE model_runs SET source_path = ? WHERE run_id = ?",
        [str(path), request.run_id],
    )

    summary = database.fetch_one(
        """
        SELECT count(*) AS rows_imported,
               min(period) AS period_min,
               max(period) AS period_max,
               count(DISTINCT scale) AS n_scales,
               count(DISTINCT entity_id) AS n_entities
        FROM estimates WHERE run_id = ?
        """,
        [request.run_id],
    ) or {}
    rows_read = int(database.fetch_scalar(f"SELECT count(*) FROM {reader}", [str(path)]) or 0)
    rows_added = after - before
    return {
        **summary,
        "run_id": request.run_id,
        "level": request.level,
        "rows_read": rows_read,
        "rows_added": rows_added,
        "duplicates_ignored": rows_read - rows_added,
        "rows_in_run": int(summary.get("rows_imported", 0)),
        "source": str(path),
    }


def latest_run(database: Database) -> dict[str, Any] | None:
    """Return the most recently registered model run, or ``None``."""
    return _deserialize_run(
        database.fetch_one(
            """
            SELECT r.*, COALESCE(e.n_estimates, 0) AS n_estimates
            FROM model_runs r
            LEFT JOIN (
                SELECT run_id, count(*) AS n_estimates FROM estimates GROUP BY run_id
            ) e ON e.run_id = r.run_id
            ORDER BY r.created_at DESC, r.run_id DESC
            LIMIT 1
            """
        )
    )


def list_runs(database: Database, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    """List registered model runs, newest first."""
    total = int(database.fetch_scalar("SELECT count(*) FROM model_runs") or 0)
    rows = database.fetch_all(
        """
        SELECT r.*, COALESCE(e.n_estimates, 0) AS n_estimates
        FROM model_runs r
        LEFT JOIN (
            SELECT run_id, count(*) AS n_estimates FROM estimates GROUP BY run_id
        ) e ON e.run_id = r.run_id
        ORDER BY r.created_at DESC, r.run_id DESC
        LIMIT ? OFFSET ?
        """,
        [limit, offset],
    )
    return [_deserialize_run(row) for row in rows], total


def block_at(database: Database, lat: float, lon: float) -> dict[str, Any] | None:
    """Latest-run estimate rows for the 1-degree region containing a point.

    The region id is derived with the same formula the modeling layer uses
    (``region_index`` in ``modeling/src/harmonize.py``, region_deg=1). It is used
    only to look up stored estimate rows; nothing is recomputed here. Returns
    the latest observed and backcast periods for both scales, or ``None`` when
    no estimates have been imported.
    """
    latest = latest_run(database)
    if latest is None:
        return None
    run_id = latest["run_id"]
    n_lon = 360
    lat_i = int((lat + 90.0) // 1.0)
    lon_i = int((lon + 180.0) // 1.0)
    lat_i = max(0, min(n_lon // 2 - 1, lat_i))
    lon_i = max(0, min(n_lon - 1, lon_i))
    entity_id = str(lat_i * n_lon + lon_i)

    rows = database.fetch_all(
        """
        SELECT scale, period, value, low, high, is_estimate, baseline, model
        FROM estimates
        WHERE run_id = ? AND level = 'region' AND entity_id = ?
        ORDER BY scale, period DESC
        """,
        [run_id, entity_id],
    )
    if not rows:
        return {
            "run_id": run_id,
            "entity_id": entity_id,
            "grid_degrees": 1.0,
            "available": False,
            "reason": "No stored estimate rows for this block.",
        }

    by_scale: dict[str, Any] = {}
    for scale in SCALES:
        scale_rows = [r for r in rows if r["scale"] == scale]
        if not scale_rows:
            continue
        newest = scale_rows[0]
        observed = next((r for r in scale_rows if not r["is_estimate"]), None)
        by_scale[scale] = {
            "latest_period": newest["period"],
            "latest_value": newest["value"],
            "latest_is_estimate": newest["is_estimate"],
            "low": newest["low"],
            "high": newest["high"],
            "latest_observed_period": observed["period"] if observed else None,
            "latest_observed_value": observed["value"] if observed else None,
            "baseline": newest["baseline"],
        }
    return {
        "run_id": run_id,
        "entity_id": entity_id,
        "grid_degrees": 1.0,
        "available": True,
        "scales": by_scale,
    }


def get_run(database: Database, run_id: str) -> dict[str, Any] | None:
    """Return one model run with its estimate count."""
    return _deserialize_run(
        database.fetch_one(
            """
            SELECT r.*, COALESCE(e.n_estimates, 0) AS n_estimates
            FROM model_runs r
            LEFT JOIN (
                SELECT run_id, count(*) AS n_estimates FROM estimates GROUP BY run_id
            ) e ON e.run_id = r.run_id
            WHERE r.run_id = ?
            """,
            [run_id],
        )
    )


def _resolve_run(database: Database, run_id: str | None) -> dict[str, Any]:
    row = latest_run(database) if run_id is None else get_run(database, run_id)
    if row is None:
        raise ApiError(
            "model_run_not_found",
            "No model estimates are available. Register and import a run first.",
            404,
        )
    return row


def list_estimates(
    database: Database, query: EstimateQuery
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Return a page of stored estimates and the run they came from."""
    run = _resolve_run(database, query.run_id)
    clauses = ["run_id = ?"]
    params: list[Any] = [run["run_id"]]

    for key, column in (
        ("level", "level"),
        ("entity_id", "entity_id"),
        ("scale", "scale"),
        ("is_estimate", "is_estimate"),
    ):
        value = getattr(query, key)
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    if query.from_period is not None:
        clauses.append("period >= ?")
        params.append(query.from_period)
    if query.to_period is not None:
        clauses.append("period <= ?")
        params.append(query.to_period)

    where = " AND ".join(clauses)
    total = int(
        database.fetch_scalar(f"SELECT count(*) FROM estimates WHERE {where}", params) or 0
    )
    rows = database.fetch_all(
        f"SELECT * FROM estimates WHERE {where} "
        "ORDER BY period, entity_id, scale LIMIT ? OFFSET ?",
        [*params, query.limit, query.offset],
    )
    return rows, total, run


def calendar_series(database: Database, run_id: str | None = None) -> dict[str, Any]:
    """Monthly series for a dashboard, summed over all entities.

    Observed and estimated rows are returned as separate columns rather than
    merged: a backcast is never presented as a measurement.
    """
    run = _resolve_run(database, run_id)
    rows = database.fetch_all(
        """
        SELECT
            period,
            scale,
            sum(value) AS value,
            sum(CASE WHEN is_estimate THEN value ELSE 0 END) AS estimated_value,
            sum(CASE WHEN NOT is_estimate THEN value ELSE 0 END) AS observed_value,
            sum(low) AS low,
            sum(high) AS high,
            count(*) FILTER (WHERE is_estimate) AS n_estimate_rows,
            count(*) FILTER (WHERE NOT is_estimate) AS n_observed_rows
        FROM estimates
        WHERE run_id = ?
        GROUP BY period, scale
        ORDER BY period, scale
        """,
        [run["run_id"]],
    )
    return {
        "run_id": run["run_id"],
        "model_name": run["model_name"],
        "series": rows,
        "notes": [
            "Values are model-produced estimates, not FIRMS detections.",
            "viirs_harmonized includes a coverage correction; modis_raw is uncorrected.",
            "low/high are a heuristic band, not a fitted confidence interval.",
            "Observed and estimated contributions are kept in separate columns.",
            "MODIS is not ground truth; no trend claim is made from three observed years.",
            "Held-out reference validation against observed VIIRS exists for 2013 and 2024; "
            "2025 contributed to fitting and is not an independent holdout.",
            "VIIRS did not exist before 20 January 2012: the 2005, 2006 and 2012 backcasts "
            "cannot be directly checked against VIIRS by design.",
        ],
    }
