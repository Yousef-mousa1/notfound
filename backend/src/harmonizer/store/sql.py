"""SQL builders for observation queries.

Only whitelisted columns and directions are ever interpolated into SQL.
Every user-provided value is passed as a parameter.
"""

from __future__ import annotations

from typing import Any

SORTABLE_COLUMNS: dict[str, str] = {
    "observation_id": "observation_id",
    "datetime_utc": "datetime_utc",
    "lat": "lat",
    "lon": "lon",
    "frp_mw": "frp_mw",
    "sensor": "sensor",
    "platform": "platform",
    "source_row": "source_row",
}

GRANULARITIES: dict[str, str] = {"day": "day", "month": "month", "year": "year"}

LIST_COLUMNS = (
    "observation_id, source_id, source_row, sensor, platform, lat, lon, "
    "datetime_utc, frp_mw, confidence_raw, confidence_class, brightness_primary, "
    "brightness_secondary, daynight, fire_type, scan, track, qc_flags"
)

DETAIL_COLUMNS = f"{LIST_COLUMNS}, raw_json"


def build_where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Build a WHERE clause from validated filters.

    Supported keys: ``sensor``, ``platform``, ``start``, ``end``, ``min_frp``,
    ``max_frp``, ``daynight``, ``fire_type``, ``confidence_class``,
    ``source_id``, ``bbox`` (min_lon, min_lat, max_lon, max_lat).
    """
    clauses: list[str] = []
    params: list[Any] = []

    simple = {
        "sensor": "=",
        "platform": "=",
        "daynight": "=",
        "fire_type": "=",
        "confidence_class": "=",
        "source_id": "=",
    }
    for key, operator in simple.items():
        value = filters.get(key)
        if value is not None:
            clauses.append(f"{key} {operator} ?")
            params.append(value)

    if filters.get("start") is not None:
        clauses.append("datetime_utc >= ?")
        params.append(filters["start"])
    if filters.get("end") is not None:
        clauses.append("datetime_utc <= ?")
        params.append(filters["end"])
    if filters.get("min_frp") is not None:
        clauses.append("frp_mw >= ?")
        params.append(filters["min_frp"])
    if filters.get("max_frp") is not None:
        clauses.append("frp_mw <= ?")
        params.append(filters["max_frp"])

    bbox = filters.get("bbox")
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        clauses.append("lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?")
        params.extend([min_lon, max_lon, min_lat, max_lat])

    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params


def _order_clause(sort: str, order: str) -> str:
    column = SORTABLE_COLUMNS.get(sort)
    if column is None:
        raise ValueError(f"Unsupported sort column: {sort}")
    direction = order.upper()
    if direction not in {"ASC", "DESC"}:
        raise ValueError(f"Unsupported order: {order}")
    return f"ORDER BY {column} {direction} NULLS LAST, observation_id ASC"


def observations_select(
    filters: dict[str, Any], sort: str, order: str, limit: int, offset: int
) -> tuple[str, list[Any]]:
    """Paginated list query."""
    where, params = build_where(filters)
    sql = (
        f"SELECT {LIST_COLUMNS} FROM observations {where} "
        f"{_order_clause(sort, order)} LIMIT ? OFFSET ?"
    )
    return sql, [*params, limit, offset]


def observations_count(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Total count for the same filters."""
    where, params = build_where(filters)
    return f"SELECT count(*) FROM observations {where}", params


def observation_by_id(observation_id: str) -> tuple[str, list[Any]]:
    """Single observation lookup."""
    return f"SELECT {DETAIL_COLUMNS} FROM observations WHERE observation_id = ?", [
        observation_id
    ]


def statistics(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Per-sensor summary statistics (FRP is instantaneous power, never summed)."""
    where, params = build_where(filters)
    sql = f"""
        SELECT
            sensor,
            count(*) AS detections,
            count(DISTINCT CAST(datetime_utc AS DATE)) AS distinct_days,
            min(datetime_utc) AS first_detection_utc,
            max(datetime_utc) AS last_detection_utc,
            min(lat) AS min_lat, max(lat) AS max_lat,
            min(lon) AS min_lon, max(lon) AS max_lon,
            min(frp_mw) AS min_frp_mw,
            max(frp_mw) AS max_frp_mw,
            avg(frp_mw) AS mean_frp_mw,
            quantile_cont(frp_mw, 0.5) AS median_frp_mw
        FROM observations {where}
        GROUP BY sensor
        ORDER BY sensor
    """
    return sql, params


def summary(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Combined summary statistics for the filtered rows (no sensor grouping)."""
    where, params = build_where(filters)
    sql = f"""
        SELECT
            count(*) AS detections,
            count(DISTINCT sensor) AS sensors,
            count(DISTINCT CAST(datetime_utc AS DATE)) AS distinct_days,
            min(datetime_utc) AS first_detection_utc,
            max(datetime_utc) AS last_detection_utc,
            min(lat) AS min_lat, max(lat) AS max_lat,
            min(lon) AS min_lon, max(lon) AS max_lon,
            min(frp_mw) AS min_frp_mw,
            max(frp_mw) AS max_frp_mw,
            avg(frp_mw) AS mean_frp_mw,
            quantile_cont(frp_mw, 0.5) AS median_frp_mw
        FROM observations {where}
    """
    return sql, params


def by_date(filters: dict[str, Any], granularity: str) -> tuple[str, list[Any]]:
    """Detections per sensor per date bucket."""
    unit = GRANULARITIES.get(granularity)
    if unit is None:
        raise ValueError(f"Unsupported granularity: {granularity}")
    where, params = build_where(filters)
    date_clause = "datetime_utc IS NOT NULL"
    combined = f"{where} AND {date_clause}" if where else f"WHERE {date_clause}"
    sql = f"""
        SELECT
            CAST(date_trunc('{unit}', datetime_utc) AS DATE) AS bucket,
            sensor,
            count(*) AS detections,
            avg(frp_mw) AS mean_frp_mw,
            quantile_cont(frp_mw, 0.5) AS median_frp_mw,
            max(frp_mw) AS max_frp_mw,
            min(frp_mw) AS min_frp_mw
        FROM observations {combined}
        GROUP BY bucket, sensor
        ORDER BY bucket, sensor
    """
    return sql, params


def by_sensor(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Detections grouped by sensor and platform."""
    where, params = build_where(filters)
    sql = f"""
        SELECT
            sensor,
            platform,
            count(*) AS detections,
            count(DISTINCT CAST(datetime_utc AS DATE)) AS distinct_days,
            min(datetime_utc) AS first_detection_utc,
            max(datetime_utc) AS last_detection_utc,
            min(frp_mw) AS min_frp_mw,
            max(frp_mw) AS max_frp_mw,
            avg(frp_mw) AS mean_frp_mw
        FROM observations {where}
        GROUP BY sensor, platform
        ORDER BY sensor, platform
    """
    return sql, params


def map_points(filters: dict[str, Any], limit: int) -> tuple[str, list[Any]]:
    """Point payload for a map view (no raw rows)."""
    where, params = build_where(filters)
    sql = f"""
        SELECT observation_id, sensor, platform, lat, lon, datetime_utc, frp_mw, daynight
        FROM observations {where}
        ORDER BY datetime_utc DESC NULLS LAST, observation_id
        LIMIT ?
    """
    return sql, [*params, limit]


def extent(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Bounding box of the filtered observations."""
    where, params = build_where(filters)
    return (
        "SELECT min(lat) AS min_lat, max(lat) AS max_lat, "
        f"min(lon) AS min_lon, max(lon) AS max_lon FROM observations {where}",
        params,
    )


def observations_for_matching(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Minimal columns for link generation."""
    where, params = build_where(filters)
    sql = (
        "SELECT observation_id, sensor, lat, lon, datetime_utc, frp_mw "
        f"FROM observations {where}"
    )
    return sql, params


def flag_counts(filters: dict[str, Any], flag_sums: dict[str, str]) -> tuple[str, list[Any]]:
    """Count rows and each QC flag without changing anything."""
    where, params = build_where(filters)
    sums = ",\n            ".join(
        f"{expression} AS {flag}" for flag, expression in flag_sums.items()
    )
    return (
        f"""
        SELECT
            count(*) AS rows,
            {sums}
        FROM observations {where}
        """,
        params,
    )


def update_flags(filters: dict[str, Any], flag_expression: str) -> tuple[str, list[Any]]:
    """Recompute ``qc_flags`` for the filtered rows (in place, no deletion)."""
    where, params = build_where(filters)
    return f"UPDATE observations SET qc_flags = {flag_expression} {where}", params


def _cell_mapping_cte(filters: dict[str, Any], grid: dict[str, Any]) -> tuple[str, list[Any]]:
    where, params = build_where(filters)
    cte = f"""
        WITH mapped AS (
            SELECT
                o.observation_id, o.sensor, o.frp_mw, o.daynight, o.datetime_utc,
                least(greatest(cast(floor((o.lat - ?) / ?) AS INTEGER), 0), ?) AS row_index,
                least(greatest(cast(floor((o.lon - ?) / ?) AS INTEGER), 0), ?) AS col_index
            FROM observations o
            {where}
        )
    """
    grid_params: list[Any] = [
        grid["min_lat"],
        grid["lat_step"],
        grid["n_rows"] - 1,
        grid["min_lon"],
        grid["lon_step"],
        grid["n_cols"] - 1,
        *params,
    ]
    return cte, grid_params


def aggregate_cells(
    filters: dict[str, Any], grid: dict[str, Any], time_unit: str | None
) -> tuple[str, list[Any]]:
    """Per-cell (and optional day/month) aggregation, sensors kept separate."""
    cte, params = _cell_mapping_cte(filters, grid)
    if time_unit is None:
        bucket = "'all'"
    else:
        if time_unit not in {"day", "month"}:
            raise ValueError(f"Unsupported time bucket: {time_unit}")
        bucket = f"CAST(date_trunc('{time_unit}', m.datetime_utc) AS DATE)"
    sql = cte + f"""
        SELECT
            g.cell_id AS cell_id,
            CAST({bucket} AS VARCHAR) AS time_bucket,
            m.sensor AS sensor,
            count(*) AS detections,
            avg(m.frp_mw) AS mean_frp_mw,
            quantile_cont(m.frp_mw, 0.5) AS median_frp_mw,
            max(m.frp_mw) AS max_frp_mw,
            min(m.frp_mw) AS min_frp_mw,
            sum(CASE WHEN m.daynight = 'D' THEN 1 ELSE 0 END) AS day_detections,
            sum(CASE WHEN m.daynight = 'N' THEN 1 ELSE 0 END) AS night_detections
        FROM mapped m
        JOIN grid_cells g
          ON g.grid_id = ? AND g.row_index = m.row_index AND g.col_index = m.col_index
        GROUP BY g.cell_id, time_bucket, m.sensor
        ORDER BY g.cell_id, m.sensor
    """
    return sql, [*params, grid["grid_id"]]


def feature_cells(filters: dict[str, Any], grid: dict[str, Any]) -> tuple[str, list[Any]]:
    """Per-cell features, sensors kept separate."""
    cte, params = _cell_mapping_cte(filters, grid)
    sql = cte + """
        SELECT
            g.cell_id AS cell_id,
            m.sensor AS sensor,
            count(*) AS detections,
            count(DISTINCT CAST(m.datetime_utc AS DATE)) AS distinct_days,
            avg(m.frp_mw) AS mean_frp_mw,
            quantile_cont(m.frp_mw, 0.5) AS median_frp_mw,
            max(m.frp_mw) AS max_frp_mw,
            avg(CASE WHEN m.daynight = 'D' THEN 1.0 ELSE 0.0 END) AS day_fraction,
            avg(CASE WHEN m.daynight = 'N' THEN 1.0 ELSE 0.0 END) AS night_fraction,
            min(m.datetime_utc) AS first_detection_utc,
            max(m.datetime_utc) AS last_detection_utc
        FROM mapped m
        JOIN grid_cells g
          ON g.grid_id = ? AND g.row_index = m.row_index AND g.col_index = m.col_index
        GROUP BY g.cell_id, m.sensor
        ORDER BY g.cell_id, m.sensor
    """
    return sql, [*params, grid["grid_id"]]


def grid_row(grid_id: str) -> tuple[str, list[Any]]:
    """Look up a stored grid."""
    return "SELECT * FROM grids WHERE grid_id = ?", [grid_id]


def grid_cells_query(grid_id: str, limit: int, offset: int) -> tuple[str, list[Any]]:
    """Page through a grid's cells."""
    return (
        "SELECT * FROM grid_cells WHERE grid_id = ? "
        "ORDER BY row_index, col_index LIMIT ? OFFSET ?",
        [grid_id, limit, offset],
    )


def run_row(run_id: str) -> tuple[str, list[Any]]:
    """Look up a processing run."""
    return "SELECT * FROM processing_runs WHERE run_id = ?", [run_id]


def harmonization_results(
    run_id: str, limit: int, offset: int, order_by_index: bool = True
) -> tuple[str, list[Any]]:
    """Page through a harmonization run's per-cell results."""
    ordering = (
        "harmonized_activity_index DESC NULLS LAST, cell_id, time_bucket"
        if order_by_index
        else "cell_id, time_bucket"
    )
    return (
        "SELECT * FROM harmonization_results WHERE run_id = ? "
        f"ORDER BY {ordering} LIMIT ? OFFSET ?",
        [run_id, limit, offset],
    )


def harmonization_result_count(run_id: str) -> tuple[str, list[Any]]:
    """Number of per-cell result rows for a run."""
    return "SELECT count(*) FROM harmonization_results WHERE run_id = ?", [run_id]


def harmonization_comparison(run_id: str) -> tuple[str, list[Any]]:
    """Before/after comparison aggregated over the run's cells."""
    return (
        """
        SELECT
            count(*) AS rows,
            count(*) FILTER (WHERE sensors_present = 2) AS cells_with_both_sensors,
            count(*) FILTER (WHERE sensors_present = 1) AS cells_with_one_sensor,
            sum(coalesce(modis_count, 0)) AS modis_detections,
            sum(coalesce(viirs_count, 0)) AS viirs_detections,
            avg(modis_mean_frp_mw) AS modis_mean_frp_mw,
            avg(viirs_mean_frp_mw) AS viirs_mean_frp_mw,
            avg(viirs_mean_frp_calibrated_mw) AS viirs_calibrated_mean_frp_mw,
            avg(modis_index) AS modis_index_mean,
            avg(viirs_index) AS viirs_index_mean,
            avg(harmonized_activity_index) AS harmonized_index_mean,
            max(harmonized_activity_index) AS harmonized_index_max
        FROM harmonization_results WHERE run_id = ?
        """,
        [run_id],
    )


def harmonization_coverage(run_id: str) -> tuple[str, list[Any]]:
    """Coverage and uncertainty summary for a run."""
    return (
        """
        SELECT
            sensors_present,
            count(*) AS rows,
            avg(uncertainty_mw) AS mean_uncertainty_mw,
            max(uncertainty_mw) AS max_uncertainty_mw
        FROM harmonization_results
        WHERE run_id = ?
        GROUP BY sensors_present
        ORDER BY sensors_present
        """,
        [run_id],
    )


def harmonization_run(run_id: str) -> tuple[str, list[Any]]:
    """Look up a harmonization run."""
    return "SELECT * FROM harmonization_runs WHERE run_id = ?", [run_id]


def harmonization_run_list(limit: int, offset: int) -> tuple[str, list[Any]]:
    """List harmonization runs, newest first."""
    return (
        "SELECT * FROM harmonization_runs ORDER BY created_at DESC, run_id LIMIT ? OFFSET ?",
        [limit, offset],
    )


def validation_run(run_id: str) -> tuple[str, list[Any]]:
    """Look up a validation run."""
    return "SELECT * FROM validation_runs WHERE run_id = ?", [run_id]


def validation_run_list(limit: int, offset: int) -> tuple[str, list[Any]]:
    """List validation runs, newest first."""
    return (
        "SELECT * FROM validation_runs ORDER BY created_at DESC, run_id LIMIT ? OFFSET ?",
        [limit, offset],
    )


def validation_latest_run() -> tuple[str, list[Any]]:
    """Return the most recent successful validation run."""
    return (
        "SELECT * FROM validation_runs WHERE status = 'succeeded' "
        "ORDER BY created_at DESC, run_id LIMIT 1",
        [],
    )


def validation_pairs(run_id: str) -> tuple[str, list[Any]]:
    """All stored pairs for a validation run."""
    return (
        "SELECT * FROM validation_pairs WHERE run_id = ? ORDER BY pair_index",
        [run_id],
    )


def activity_trend(run_id: str) -> tuple[str, list[Any]]:
    """Harmonized activity index per time bucket for a run."""
    return (
        """
        SELECT
            time_bucket,
            count(*) AS cells,
            count(*) FILTER (WHERE sensors_present = 2) AS cells_with_both_sensors,
            avg(harmonized_activity_index) AS mean_activity_index,
            quantile_cont(harmonized_activity_index, 0.5) AS median_activity_index,
            max(harmonized_activity_index) AS max_activity_index,
            sum(coalesce(modis_count, 0)) AS modis_detections,
            sum(coalesce(viirs_count, 0)) AS viirs_detections
        FROM harmonization_results
        WHERE run_id = ?
        GROUP BY time_bucket
        ORDER BY time_bucket
        """,
        [run_id],
    )


def cell_daily_counts(
    filters: dict[str, Any], grid: dict[str, Any]
) -> tuple[str, list[Any]]:
    """Daily detection counts per grid cell and sensor (sensors kept separate)."""
    cte, params = _cell_mapping_cte(filters, grid)
    sql = cte + """
        SELECT
            g.cell_id AS cell_id,
            m.sensor AS sensor,
            CAST(m.datetime_utc AS DATE) AS day,
            count(*) AS detections,
            g.center_lat AS center_lat,
            g.center_lon AS center_lon
        FROM mapped m
        JOIN grid_cells g
          ON g.grid_id = ? AND g.row_index = m.row_index AND g.col_index = m.col_index
        WHERE m.datetime_utc IS NOT NULL
        GROUP BY g.cell_id, m.sensor, day, g.center_lat, g.center_lon
        ORDER BY g.cell_id, m.sensor, day
    """
    return sql, [*params, grid["grid_id"]]


def _anomaly_where(
    run_id: str, filters: dict[str, Any]
) -> tuple[str, list[Any]]:
    """Shared WHERE clause for anomaly queries."""
    clauses = ["run_id = ?"]
    params: list[Any] = [run_id]
    if filters.get("sensor") is not None:
        clauses.append("sensor = ?")
        params.append(filters["sensor"])
    if filters.get("severity") is not None:
        clauses.append("severity = ?")
        params.append(filters["severity"])
    if filters.get("start") is not None:
        clauses.append("day >= CAST(? AS DATE)")
        params.append(filters["start"])
    if filters.get("end") is not None:
        clauses.append("day <= CAST(? AS DATE)")
        params.append(filters["end"])
    bbox = filters.get("bbox")
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        clauses.append(
            "center_lon BETWEEN ? AND ? AND center_lat BETWEEN ? AND ?"
        )
        params.extend([min_lon, max_lon, min_lat, max_lat])
    return "WHERE " + " AND ".join(clauses), params


def anomalies_list(
    run_id: str, filters: dict[str, Any], limit: int, offset: int
) -> tuple[str, list[Any]]:
    """Page through flagged anomalies, strongest first."""
    where, params = _anomaly_where(run_id, filters)
    return (
        "SELECT * FROM anomalies "
        f"{where} ORDER BY robust_z DESC, day DESC, anomaly_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )


def anomalies_count(run_id: str, filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Total flagged anomalies for the same filters."""
    where, params = _anomaly_where(run_id, filters)
    return f"SELECT count(*) FROM anomalies {where}", params


def anomaly_by_id(anomaly_id: str) -> tuple[str, list[Any]]:
    """Single anomaly lookup."""
    return "SELECT * FROM anomalies WHERE anomaly_id = ?", [anomaly_id]


def anomaly_run(run_id: str) -> tuple[str, list[Any]]:
    """Look up an anomaly run."""
    return "SELECT * FROM anomaly_runs WHERE run_id = ?", [run_id]


def anomaly_latest_run() -> tuple[str, list[Any]]:
    """Most recent successful anomaly run."""
    return (
        "SELECT * FROM anomaly_runs WHERE status = 'succeeded' "
        "ORDER BY created_at DESC, run_id LIMIT 1",
        [],
    )


def anomalies_statistics(
    run_id: str, filters: dict[str, Any]
) -> tuple[str, list[Any]]:
    """Overall anomaly statistics for a run."""
    where, params = _anomaly_where(run_id, filters)
    return (
        f"""
        SELECT
            count(*) AS anomalies,
            count(DISTINCT cell_id) AS cells,
            count(DISTINCT day) AS days,
            min(day) AS first_day,
            max(day) AS last_day,
            avg(robust_z) AS mean_robust_z,
            max(robust_z) AS max_robust_z,
            sum(detections) AS detected_detections
        FROM anomalies {where}
        """,
        params,
    )


def anomalies_by_sensor(
    run_id: str, filters: dict[str, Any]
) -> tuple[str, list[Any]]:
    """Anomaly counts per sensor."""
    where, params = _anomaly_where(run_id, filters)
    return (
        f"""
        SELECT sensor, count(*) AS anomalies, count(DISTINCT cell_id) AS cells,
               max(robust_z) AS max_robust_z
        FROM anomalies {where}
        GROUP BY sensor ORDER BY sensor
        """,
        params,
    )


def anomalies_by_severity(
    run_id: str, filters: dict[str, Any]
) -> tuple[str, list[Any]]:
    """Anomaly counts per severity band."""
    where, params = _anomaly_where(run_id, filters)
    return (
        f"""
        SELECT severity, count(*) AS anomalies, count(DISTINCT cell_id) AS cells,
               max(robust_z) AS max_robust_z
        FROM anomalies {where}
        GROUP BY severity ORDER BY max_robust_z DESC
        """,
        params,
    )


def anomalies_by_region(
    run_id: str, filters: dict[str, Any], limit: int
) -> tuple[str, list[Any]]:
    """Anomaly counts per grid cell and sensor, strongest cells first."""
    where, params = _anomaly_where(run_id, filters)
    return (
        f"""
        SELECT cell_id, sensor, center_lat, center_lon,
               count(*) AS anomalies,
               max(robust_z) AS max_robust_z,
               sum(CASE WHEN severity = 'extreme' THEN 1 ELSE 0 END) AS extreme,
               sum(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high,
               sum(CASE WHEN severity = 'moderate' THEN 1 ELSE 0 END) AS moderate
        FROM anomalies {where}
        GROUP BY cell_id, sensor, center_lat, center_lon
        ORDER BY anomalies DESC, max_robust_z DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def anomalies_by_day(
    run_id: str, filters: dict[str, Any]
) -> tuple[str, list[Any]]:
    """Anomaly counts per day and sensor."""
    where, params = _anomaly_where(run_id, filters)
    return (
        f"""
        SELECT day, sensor, count(*) AS anomalies,
               sum(detections) AS detected_detections, max(robust_z) AS max_robust_z
        FROM anomalies {where}
        GROUP BY day, sensor ORDER BY day, sensor
        """,
        params,
    )


def anomalies_map(
    run_id: str, filters: dict[str, Any], limit: int
) -> tuple[str, list[Any]]:
    """Map point payload for flagged anomalies."""
    where, params = _anomaly_where(run_id, filters)
    return (
        "SELECT anomaly_id, cell_id, sensor, day, detections, robust_z, severity, "
        f"center_lat AS lat, center_lon AS lon FROM anomalies {where} "
        "ORDER BY robust_z DESC LIMIT ?",
        [*params, limit],
    )


#: Columns written by an observation export, in a fixed order.
EXPORT_OBSERVATION_COLUMNS: tuple[str, ...] = (
    "observation_id",
    "source_id",
    "source_row",
    "sensor",
    "platform",
    "lat",
    "lon",
    "datetime_utc",
    "frp_mw",
    "confidence_raw",
    "confidence_class",
    "brightness_primary",
    "brightness_secondary",
    "daynight",
    "fire_type",
    "scan",
    "track",
    "qc_flags",
)


def observations_export(
    filters: dict[str, Any], include_raw_json: bool
) -> tuple[str, list[Any]]:
    """Every observation matching the filters, in deterministic order.

    ``raw_json`` is opt-in because it repeats the whole original row and makes
    the file much larger.
    """
    where, params = build_where(filters)
    columns = ", ".join(EXPORT_OBSERVATION_COLUMNS)
    if include_raw_json:
        columns = f"{columns}, raw_json"
    return (
        f"SELECT {columns} FROM observations {where} "
        "ORDER BY datetime_utc NULLS LAST, observation_id",
        params,
    )


def harmonization_export(run_id: str) -> tuple[str, list[Any]]:
    """Every per-cell row of a harmonization run, in deterministic order."""
    return (
        "SELECT * FROM harmonization_results WHERE run_id = ? "
        "ORDER BY cell_id, time_bucket",
        [run_id],
    )


def validation_pairs_export(run_id: str) -> tuple[str, list[Any]]:
    """Every stored pair of a validation run, in pair order."""
    return (
        "SELECT * FROM validation_pairs WHERE run_id = ? ORDER BY pair_index",
        [run_id],
    )


def anomalies_export(run_id: str) -> tuple[str, list[Any]]:
    """Every flagged anomaly of a run, strongest first."""
    return (
        "SELECT * FROM anomalies WHERE run_id = ? "
        "ORDER BY robust_z DESC, day, anomaly_id",
        [run_id],
    )


def export_row(export_id: str) -> tuple[str, list[Any]]:
    """Look up one export record."""
    return "SELECT * FROM exports WHERE export_id = ?", [export_id]


def export_list(
    kind: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[str, list[Any], list[Any]]:
    """List exports, newest first, plus the matching total count."""
    clauses: list[str] = []
    params: list[Any] = []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return (
        f"SELECT * FROM exports {where} "
        "ORDER BY created_at DESC, export_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
        params,
    )


def harmonized_map_points(
    run_id: str,
    grid_id: str,
    both_only: bool,
    limit: int,
    offset: int = 0,
) -> tuple[str, list[Any]]:
    """Map points for a run's per-cell results, with grid cell centres.

    A harmonized row is a cell-day, not a detection, so the geometry comes from
    the run's grid. Ordering is by the harmonized index so a bounded sample
    keeps the strongest cells instead of an arbitrary slice.
    """
    where = ["r.run_id = ?", "c.grid_id = ?"]
    params: list[Any] = [run_id, grid_id]
    if both_only:
        where.append("r.sensors_present = 2")
    return (
        """
        SELECT
            r.cell_id,
            r.time_bucket AS day,
            r.sensors_present,
            r.modis_count,
            r.viirs_count,
            r.modis_mean_frp_mw,
            r.viirs_mean_frp_mw,
            r.viirs_mean_frp_calibrated_mw,
            r.harmonized_activity_index,
            r.uncertainty_mw,
            c.center_lat,
            c.center_lon
        FROM harmonization_results r
        JOIN grid_cells c ON c.grid_id = ? AND c.cell_id = r.cell_id
        WHERE """ + " AND ".join(where) + """
        ORDER BY r.harmonized_activity_index DESC NULLS LAST, r.cell_id, r.time_bucket
        LIMIT ? OFFSET ?
        """,
        [grid_id, *params, limit, offset],
    )


def harmonized_map_point_count(
    run_id: str, grid_id: str, both_only: bool
) -> tuple[str, list[Any]]:
    """Number of map points matching ``harmonized_map_points`` filters."""
    where = ["r.run_id = ?", "c.grid_id = ?"]
    params: list[Any] = [run_id, grid_id]
    if both_only:
        where.append("r.sensors_present = 2")
    return (
        "SELECT count(*) FROM harmonization_results r "
        "JOIN grid_cells c ON c.grid_id = ? AND c.cell_id = r.cell_id "
        "WHERE " + " AND ".join(where),
        [grid_id, *params],
    )
