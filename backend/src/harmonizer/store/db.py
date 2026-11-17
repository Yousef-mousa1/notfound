"""DuckDB analytical store.

Raw CSVs are never modified. They are imported into this store, and each row's
original values are preserved in ``observations.raw_json``. All access goes
through a single connection guarded by a lock: DuckDB allows one writer, and
the Flask development server is multi-threaded.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id   VARCHAR PRIMARY KEY,
        sensor      VARCHAR NOT NULL,
        path        VARCHAR NOT NULL,
        file_name   VARCHAR NOT NULL,
        file_size   BIGINT  NOT NULL,
        file_mtime  DOUBLE  NOT NULL,
        sha256      VARCHAR NOT NULL,
        status      VARCHAR NOT NULL,
        created_at  TIMESTAMP NOT NULL,
        updated_at  TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS imports (
        import_id    VARCHAR PRIMARY KEY,
        source_id    VARCHAR NOT NULL,
        sensor       VARCHAR NOT NULL,
        job_id       VARCHAR,
        status       VARCHAR NOT NULL,
        rows_read    BIGINT,
        rows_loaded  BIGINT,
        duplicates   BIGINT,
        error        VARCHAR,
        started_at   TIMESTAMP,
        finished_at  TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
        observation_id      VARCHAR PRIMARY KEY,
        source_id           VARCHAR NOT NULL,
        source_row          BIGINT  NOT NULL,
        sensor              VARCHAR NOT NULL,
        platform            VARCHAR,
        lat                 DOUBLE  NOT NULL,
        lon                 DOUBLE  NOT NULL,
        datetime_utc        TIMESTAMP,
        frp_mw              DOUBLE,
        confidence_raw      VARCHAR,
        confidence_class    VARCHAR,
        brightness_primary  DOUBLE,
        brightness_secondary DOUBLE,
        daynight            VARCHAR,
        fire_type           INTEGER,
        scan                DOUBLE,
        track               DOUBLE,
        qc_flags            VARCHAR,
        raw_json            VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id      VARCHAR PRIMARY KEY,
        kind        VARCHAR NOT NULL,
        status      VARCHAR NOT NULL,
        params      VARCHAR,
        result      VARCHAR,
        error       VARCHAR,
        progress    DOUBLE,
        created_at  TIMESTAMP NOT NULL,
        started_at  TIMESTAMP,
        finished_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_logs (
        job_id  VARCHAR NOT NULL,
        seq     BIGINT  NOT NULL,
        ts      TIMESTAMP NOT NULL,
        level   VARCHAR NOT NULL,
        message VARCHAR NOT NULL,
        PRIMARY KEY (job_id, seq)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processing_runs (
        run_id      VARCHAR PRIMARY KEY,
        kind        VARCHAR NOT NULL,
        params      VARCHAR,
        status      VARCHAR NOT NULL,
        result      VARCHAR,
        job_id      VARCHAR,
        created_at  TIMESTAMP NOT NULL,
        finished_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS selections (
        selection_id VARCHAR PRIMARY KEY,
        name         VARCHAR,
        filters      VARCHAR NOT NULL,
        detections   BIGINT  NOT NULL,
        created_at   TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grids (
        grid_id              VARCHAR PRIMARY KEY,
        name                 VARCHAR,
        cell_km              DOUBLE  NOT NULL,
        min_lat              DOUBLE  NOT NULL,
        max_lat              DOUBLE  NOT NULL,
        min_lon              DOUBLE  NOT NULL,
        max_lon              DOUBLE  NOT NULL,
        lat_step             DOUBLE  NOT NULL,
        lon_step             DOUBLE  NOT NULL,
        n_rows               INTEGER NOT NULL,
        n_cols               INTEGER NOT NULL,
        mean_lat             DOUBLE  NOT NULL,
        area_distortion_pct  DOUBLE  NOT NULL,
        created_at           TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grid_cells (
        grid_id     VARCHAR NOT NULL,
        cell_id     VARCHAR NOT NULL,
        row_index   INTEGER NOT NULL,
        col_index   INTEGER NOT NULL,
        min_lat     DOUBLE  NOT NULL,
        max_lat     DOUBLE  NOT NULL,
        min_lon     DOUBLE  NOT NULL,
        max_lon     DOUBLE  NOT NULL,
        center_lat  DOUBLE  NOT NULL,
        center_lon  DOUBLE  NOT NULL,
        PRIMARY KEY (grid_id, cell_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_links (
        link_id        VARCHAR PRIMARY KEY,
        run_id         VARCHAR NOT NULL,
        sensor_a       VARCHAR NOT NULL,
        sensor_b       VARCHAR NOT NULL,
        observation_a  VARCHAR NOT NULL,
        observation_b  VARCHAR NOT NULL,
        distance_m     DOUBLE,
        delta_t_s      DOUBLE,
        created_at     TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aggregates (
        run_id          VARCHAR NOT NULL,
        grid_id         VARCHAR NOT NULL,
        cell_id         VARCHAR NOT NULL,
        time_bucket     VARCHAR NOT NULL,
        sensor          VARCHAR NOT NULL,
        detections      BIGINT,
        mean_frp_mw     DOUBLE,
        median_frp_mw   DOUBLE,
        max_frp_mw      DOUBLE,
        min_frp_mw      DOUBLE,
        day_detections  BIGINT,
        night_detections BIGINT,
        PRIMARY KEY (run_id, cell_id, time_bucket, sensor)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS features (
        run_id               VARCHAR NOT NULL,
        grid_id              VARCHAR NOT NULL,
        cell_id              VARCHAR NOT NULL,
        sensor               VARCHAR NOT NULL,
        detections           BIGINT,
        distinct_days        BIGINT,
        mean_frp_mw          DOUBLE,
        median_frp_mw        DOUBLE,
        max_frp_mw           DOUBLE,
        day_fraction         DOUBLE,
        night_fraction       DOUBLE,
        first_detection_utc  TIMESTAMP,
        last_detection_utc   TIMESTAMP,
        PRIMARY KEY (run_id, cell_id, sensor)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS harmonization_runs (
        run_id      VARCHAR PRIMARY KEY,
        method      VARCHAR NOT NULL,
        params      VARCHAR,
        status      VARCHAR NOT NULL,
        calibration VARCHAR,
        n_pairs     BIGINT,
        n_cells     BIGINT,
        created_at  TIMESTAMP NOT NULL,
        finished_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS harmonization_results (
        run_id                      VARCHAR NOT NULL,
        cell_id                     VARCHAR NOT NULL,
        time_bucket                 VARCHAR NOT NULL,
        sensors_present             INTEGER NOT NULL,
        modis_count                 BIGINT,
        viirs_count                 BIGINT,
        modis_mean_frp_mw           DOUBLE,
        viirs_mean_frp_mw           DOUBLE,
        viirs_mean_frp_calibrated_mw DOUBLE,
        modis_index                 DOUBLE,
        viirs_index                 DOUBLE,
        harmonized_activity_index   DOUBLE,
        uncertainty_mw              DOUBLE,
        PRIMARY KEY (run_id, cell_id, time_bucket)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS validation_runs (
        run_id      VARCHAR PRIMARY KEY,
        params      VARCHAR,
        status      VARCHAR NOT NULL,
        n_pairs     BIGINT,
        metrics     VARCHAR,
        created_at  TIMESTAMP NOT NULL,
        finished_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS validation_pairs (
        run_id        VARCHAR NOT NULL,
        pair_index    BIGINT  NOT NULL,
        observation_a VARCHAR NOT NULL,
        observation_b VARCHAR NOT NULL,
        frp_a         DOUBLE,
        frp_b         DOUBLE,
        distance_m    DOUBLE,
        delta_t_s     DOUBLE,
        lat_a         DOUBLE,
        lon_a         DOUBLE,
        lat_b         DOUBLE,
        lon_b         DOUBLE,
        PRIMARY KEY (run_id, pair_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS anomaly_runs (
        run_id            VARCHAR PRIMARY KEY,
        params            VARCHAR,
        status            VARCHAR NOT NULL,
        grid_id           VARCHAR,
        n_cells_total     BIGINT,
        n_cells_evaluated BIGINT,
        n_cell_days       BIGINT,
        n_anomalies       BIGINT,
        created_at        TIMESTAMP NOT NULL,
        finished_at       TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS anomalies (
        run_id          VARCHAR NOT NULL,
        anomaly_id      VARCHAR NOT NULL,
        cell_id         VARCHAR NOT NULL,
        sensor          VARCHAR NOT NULL,
        day             DATE    NOT NULL,
        detections      BIGINT  NOT NULL,
        baseline_median DOUBLE,
        baseline_scale  DOUBLE,
        robust_z        DOUBLE,
        severity        VARCHAR NOT NULL,
        center_lat      DOUBLE,
        center_lon      DOUBLE,
        PRIMARY KEY (run_id, anomaly_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exports (
        export_id     VARCHAR PRIMARY KEY,
        kind          VARCHAR NOT NULL,
        source        VARCHAR NOT NULL,
        status        VARCHAR NOT NULL,
        params        VARCHAR,
        source_run_id VARCHAR,
        row_count     BIGINT,
        directory     VARCHAR NOT NULL,
        metadata      VARCHAR,
        error         VARCHAR,
        created_at    TIMESTAMP NOT NULL,
        finished_at   TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_runs (
        run_id            VARCHAR PRIMARY KEY,
        model_name        VARCHAR NOT NULL,
        method            VARCHAR NOT NULL,
        trained_years     VARCHAR,
        test_year         INTEGER,
        validation_split  VARCHAR,
        metrics           VARCHAR,
        source_path       VARCHAR,
        artifact_path     VARCHAR,
        notes             VARCHAR,
        created_at        TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS estimates (
        run_id             VARCHAR NOT NULL,
        level              VARCHAR NOT NULL,
        entity_id          VARCHAR NOT NULL,
        period             DATE    NOT NULL,
        scale              VARCHAR NOT NULL,
        value              DOUBLE  NOT NULL,
        low                DOUBLE,
        high               DOUBLE,
        centroid_lat       DOUBLE,
        centroid_lon       DOUBLE,
        grid_degrees       DOUBLE,
        is_estimate        BOOLEAN NOT NULL,
        coverage_corrected BOOLEAN NOT NULL,
        scale_factor       DOUBLE,
        baseline           VARCHAR,
        model              VARCHAR,
        PRIMARY KEY (run_id, level, entity_id, period, scale)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_estimates_run_period ON estimates (run_id, period)
    """,
)

#: Columns inserted from a unified DataFrame, in storage order.
OBSERVATION_INSERT_COLUMNS: tuple[str, ...] = (
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
    "raw_json",
)


class Database:
    """A small synchronous wrapper around a single DuckDB connection."""

    def __init__(self, path: str | Path, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        self._lock = threading.RLock()
        if read_only:
            # Immutable snapshot on a read-only host (e.g. Vercel Functions).
            self._conn = duckdb.connect(str(self.path), read_only=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(self.path))
            self._create_schema()
        self._conn.execute("SET TimeZone='UTC'")

    def _create_schema(self) -> None:
        with self._lock:
            for statement in SCHEMA_STATEMENTS:
                self._conn.execute(statement)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        """Execute a statement without returning rows."""
        with self._lock:
            self._conn.execute(sql, list(params or []))

    def fetch_all(
        self, sql: str, params: Sequence[Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a query and return rows as dictionaries."""
        with self._lock:
            cursor = self._conn.execute(sql, list(params or []))
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def fetch_one(
        self, sql: str, params: Sequence[Any] | None = None
    ) -> dict[str, Any] | None:
        """Execute a query and return the first row, or ``None``."""
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        """Execute a query and return the first column of the first row."""
        with self._lock:
            rows = self._conn.execute(sql, list(params or [])).fetchall()
            return None if not rows else rows[0][0]

    def fetch_frame(
        self, sql: str, params: Sequence[Any] | None = None
    ) -> pd.DataFrame:
        """Execute a query and return a pandas DataFrame."""
        with self._lock:
            return self._conn.execute(sql, list(params or [])).df()

    def insert_frame(self, table: str, frame: pd.DataFrame, columns: Iterable[str]) -> int:
        """Insert a DataFrame into ``table``.

        Returns:
            Number of rows actually inserted (primary-key conflicts are ignored,
            never overwritten).
        """
        column_list = tuple(columns)
        before = int(self.fetch_scalar(f"SELECT count(*) FROM {table}"))
        with self._lock:
            view_name = "_incoming_frame"
            self._conn.register(view_name, frame[list(column_list)])
            try:
                placeholders = ", ".join(column_list)
                self._conn.execute(
                    f"INSERT OR IGNORE INTO {table} ({placeholders}) "
                    f"SELECT {placeholders} FROM {view_name}"
                )
            finally:
                self._conn.unregister(view_name)
        after = int(self.fetch_scalar(f"SELECT count(*) FROM {table}"))
        return after - before

    def close(self) -> None:
        """Close the connection."""
        with self._lock:
            self._conn.close()
