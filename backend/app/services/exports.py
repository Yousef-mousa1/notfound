"""Export service (Slice E).

Exports are new files plus one stored ``exports`` record. Nothing that was
imported is modified or deleted, and every export carries the filters/run it
came from, a configuration snapshot, the processing steps, the known
limitations and the software versions needed to reproduce it.

There is no ambient "export everything" mode: an export always names its
source, and run-scoped exports are tied to a stored run id.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from harmonizer.config import resolve_path, snapshot_config
from harmonizer.export import (
    safe_file_name,
    software_versions,
    write_csv,
    write_json,
)
from harmonizer.store import Database
from harmonizer.store import sql
from harmonizer.store.jobs import utcnow

from ..errors import ApiError
from ..schemas.exports import (
    CsvExportRequest,
    HarmonizedExportRequest,
    ObservationExportRequest,
    ValidationReportRequest,
)
from ..serialization import TIME_BASIS, jsonable, maybe_json
from . import harmonization as harmonization_service
from . import validation as validation_service
from . import anomalies as anomaly_service

OBSERVATION_LIMITATIONS = [
    "The source files contain detections only: a missing row does not mean no fire. "
    "It may be no observation, an invalid observation or a cloud-obstructed pass (Phase 06).",
    "MODIS (~1 km) and VIIRS 375 m detections are not interchangeable; one MODIS "
    "detection is not one VIIRS detection and resampling creates no information.",
    "Confidence values are exported exactly as stored. The MODIS and VIIRS scales "
    "differ and must not be compared as raw numbers.",
    "FRP is instantaneous radiative power (MW). This export does not sum it and does "
    "not derive energy.",
    "Timestamps are UTC as recorded by the products; the timezone assumption is still "
    "pending official verification (dataset-facts.md §2).",
]

HARMONIZED_LIMITATIONS = [
    "Harmonization is a cross-sensor statistical mapping, not a physical correction, "
    "and MODIS is not ground truth.",
    "The harmonized activity index is unitless and relative to each run's own p95 "
    "scales; a one-sensor cell can reach 1.0.",
    "Only cells/time buckets that contain at least one detection are exported. "
    "Absence is not evidence of no fire (Phase 06).",
    "FRP columns stay in MW per sensor. No FRP is summed across sensors and no "
    "energy is derived.",
    "MODIS and VIIRS counts are different quantities and are exported side by side, "
    "never merged into one detection count.",
    "Uncertainty is the absolute disagreement between MODIS and calibrated VIIRS mean "
    "FRP on cells where both are present; it is not measurement error.",
]

VALIDATION_LIMITATIONS = [
    "These are cross-sensor consistency results, not accuracy: the project has no "
    "independent reference dataset.",
    "MODIS is not ground truth; agreement does not prove that either product is correct.",
    "Pairs depend on the chosen radius and time window and are not independent samples.",
    "FRP is instantaneous power (MW); no energy is derived.",
    "Raw-MW error metrics are dominated by the FRP tail; log10(FRP) metrics are the "
    "robust summary.",
]

ANOMALY_LIMITATIONS = [
    "A flagged row is a statistical outlier in daily per-cell detection counts for one "
    "sensor, not a confirmed fire event.",
    "MODIS and VIIRS are detected as separate series and are never merged.",
    "Detection gaps (clouds, overpass timing, outages) propagate directly into the counts.",
    "Baselines and scales are per (cell, sensor) series; comparing robust z between "
    "cells is not a physical comparison.",
    "Cells are grid cells, not administrative regions.",
]


def _new_export_id() -> str:
    return f"exp_{uuid.uuid4().hex[:16]}"


def _root(config: dict[str, Any]) -> Path:
    """Directory that holds every export (created on demand)."""
    try:
        return resolve_path(config, "paths", "exports")
    except (KeyError, ValueError):
        return resolve_path(config, "paths", "processed") / "exports"


def _max_rows(config: dict[str, Any]) -> int:
    return int((config.get("exports") or {}).get("max_rows") or 500_000)


def _guard_rows(rows: int, config: dict[str, Any]) -> None:
    limit = _max_rows(config)
    if rows > limit:
        raise ApiError(
            "export_too_large",
            f"This export would contain {rows} rows, above the configured limit of {limit}.",
            413,
            {"rows": rows, "max_rows": limit, "config_key": "exports.max_rows"},
        )


def _insert_record(
    database: Database,
    *,
    export_id: str,
    kind: str,
    source: str,
    params: dict[str, Any],
    run_id: str | None,
    row_count: int | None,
    directory: Path,
    metadata: dict[str, Any] | None,
    status: str = "succeeded",
    error: str | None = None,
) -> None:
    now = utcnow()
    database.execute(
        "INSERT INTO exports (export_id, kind, source, status, params, source_run_id, "
        "row_count, directory, metadata, error, created_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            export_id,
            kind,
            source,
            status,
            jsonable_json(params),
            run_id,
            row_count,
            str(directory),
            jsonable_json(metadata) if metadata is not None else None,
            error,
            now,
            now,
        ],
    )


def jsonable_json(payload: Any) -> str:
    """Serialize to JSON with string fallbacks for dates and numpy scalars."""
    return json.dumps(payload, default=str)


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    metadata = maybe_json(row.get("metadata"))
    return {
        **row,
        "params": maybe_json(row.get("params")),
        "metadata": metadata,
        "files": (metadata or {}).get("files") or [],
        "file_available": bool(
            metadata
            and (Path(row["directory"]) / (metadata.get("files") or [{}])[0].get("name", "")).is_file()
        ),
    }


def get_export(database: Database, export_id: str) -> dict[str, Any] | None:
    """Return one export record, or ``None``."""
    query_sql, params = sql.export_row(export_id)
    row = database.fetch_one(query_sql, params)
    return None if row is None else _decode(row)


def history(
    database: Database,
    kind: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Page through export records, newest first."""
    query_sql, params, count_params = sql.export_list(kind, status, limit, offset)
    clauses: list[str] = []
    if kind:
        clauses.append("kind = ?")
    if status:
        clauses.append("status = ?")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = int(
        database.fetch_scalar(f"SELECT count(*) FROM exports {where}", count_params) or 0
    )
    return [_decode(row) for row in database.fetch_all(query_sql, params)], total


Builder = Callable[
    [Path],
    tuple[list[dict[str, Any]], int, dict[str, Any], list[str], list[str]],
]


def _execute(
    database: Database,
    config: dict[str, Any],
    *,
    kind: str,
    source: str,
    params: dict[str, Any],
    run_id: str | None,
    builder: Builder,
) -> dict[str, Any]:
    """Run a builder, write the metadata sidecar and store the record."""
    export_id = _new_export_id()
    directory = _root(config) / export_id
    try:
        data_files, row_count, inputs, steps, limitations = builder(directory)
        metadata = {
            "export_id": export_id,
            "kind": kind,
            "source": source,
            "created_at": utcnow().isoformat(),
            "time_basis": TIME_BASIS,
            "row_count": row_count,
            "inputs": inputs,
            "data_files": data_files,
            "config_snapshot": snapshot_config(config),
            "steps": steps,
            "limitations": limitations,
            "software": software_versions(),
            "notes": {
                "frp": "FRP is instantaneous power (MW); it is never summed into energy.",
                "coverage": (
                    "Detections only: absence of a row is not absence of fire "
                    "(Phase 06)."
                ),
                "reproducibility": (
                    "This metadata file plus the original inputs and config snapshot "
                    "reproduce the export."
                ),
                "values": (
                    "CSV cells are written as stored; no value is rounded, re-coded or "
                    "prefixed."
                ),
            },
        }
        metadata_file = write_json(metadata, directory / "metadata.json")
        stored = {**metadata, "files": [*data_files, metadata_file]}
        _insert_record(
            database,
            export_id=export_id,
            kind=kind,
            source=source,
            params=params,
            run_id=run_id,
            row_count=row_count,
            directory=directory,
            metadata=stored,
        )
    except ApiError:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except Exception as error:
        shutil.rmtree(directory, ignore_errors=True)
        _insert_record(
            database,
            export_id=export_id,
            kind=kind,
            source=source,
            params=params,
            run_id=run_id,
            row_count=None,
            directory=directory,
            metadata=None,
            status="failed",
            error=str(error),
        )
        raise

    record = get_export(database, export_id)
    assert record is not None
    return record


def _harmonization_run(database: Database, run_id: str | None) -> dict[str, Any]:
    if run_id:
        run_row = harmonization_service.get_run(database, run_id)
        if run_row is None:
            raise ApiError(
                "harmonization_run_not_found",
                f"No harmonization run with id '{run_id}'.",
                404,
            )
        return run_row
    latest = harmonization_service.latest_successful(database)
    if latest is None:
        raise ApiError(
            "no_harmonization_run",
            "No successful harmonization run exists yet; call POST /harmonization/run first.",
            409,
        )
    return latest


def _validation_run(database: Database, run_id: str | None) -> dict[str, Any]:
    if run_id:
        run_row = validation_service.get_run(database, run_id)
        if run_row is None:
            raise ApiError(
                "validation_run_not_found",
                f"No validation run with id '{run_id}'.",
                404,
            )
        return run_row
    latest = validation_service.latest(database)
    if latest is None:
        raise ApiError(
            "no_validation_run",
            "No successful validation run exists yet; call POST /validation/run first.",
            409,
        )
    return latest


def _anomaly_run(database: Database, run_id: str | None) -> dict[str, Any]:
    if run_id:
        run_row = anomaly_service.get_run(database, run_id)
        if run_row is None:
            raise ApiError(
                "anomaly_run_not_found", f"No anomaly run with id '{run_id}'.", 404
            )
        return run_row
    latest = anomaly_service.latest_run(database)
    if latest is None:
        raise ApiError(
            "no_anomaly_run",
            "No successful anomaly run exists yet; call POST /anomalies/detect first.",
            409,
        )
    return latest


def _observation_builder(
    database: Database, config: dict[str, Any], request: ObservationExportRequest
) -> Builder:
    """Export the observations matching the requested filters."""

    def build(
        directory: Path,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any], list[str], list[str]]:
        filters = request.as_filters()
        query_sql, params = sql.observations_export(filters, request.include_raw_json)
        frame = database.fetch_frame(query_sql, params)
        _guard_rows(len(frame), config)
        file_name = safe_file_name(request.file_name, "observations")
        files = [write_csv(frame, directory / file_name)]
        inputs = {
            "filters": jsonable(filters),
            "include_raw_json": request.include_raw_json,
            "rows": int(len(frame)),
        }
        steps = [
            "Applied the observation filters with parameterized SQL.",
            "Selected the documented export column set in a fixed order.",
            "Ordered rows by datetime_utc, then observation_id.",
            "Wrote UTF-8 CSV with LF line endings and no value rewriting.",
        ]
        return files, int(len(frame)), inputs, steps, OBSERVATION_LIMITATIONS

    return build


def create_observations(
    database: Database, config: dict[str, Any], request: ObservationExportRequest
) -> dict[str, Any]:
    """Export filtered observations to CSV plus metadata."""
    return _execute(
        database,
        config,
        kind="observations",
        source="observations",
        params=request.model_dump(mode="json"),
        run_id=None,
        builder=_observation_builder(database, config, request),
    )


def _generic_builder(
    database: Database,
    config: dict[str, Any],
    request: CsvExportRequest,
) -> tuple[Builder, str | None]:
    """Dispatch the generic CSV export to its source table."""
    if request.source == "observations":
        return _observation_builder(
            database,
            config,
            ObservationExportRequest(
                **{
                    **request.model_dump(exclude={"source", "run_id"}),
                    "file_name": request.file_name,
                }
            ),
        ), None

    if request.source == "harmonization-results":
        run_row = _harmonization_run(database, request.run_id)
        run_id = str(run_row["run_id"])

        def build(
            directory: Path,
        ) -> tuple[list[dict[str, Any]], int, dict[str, Any], list[str], list[str]]:
            query_sql, params = sql.harmonization_export(run_id)
            frame = database.fetch_frame(query_sql, params)
            _guard_rows(len(frame), config)
            file_name = safe_file_name(request.file_name, "harmonized_data")
            files = [write_csv(frame, directory / file_name)]
            inputs = {"run_id": run_id, "method": run_row.get("method")}
            steps = [
                "Read the stored per-cell rows of the harmonization run.",
                "Ordered rows by cell_id, then time_bucket.",
                "Wrote UTF-8 CSV with LF line endings and no value rewriting.",
            ]
            return files, int(len(frame)), inputs, steps, HARMONIZED_LIMITATIONS

        return build, run_id

    if request.source == "validation-pairs":
        run_row = _validation_run(database, request.run_id)
        run_id = str(run_row["run_id"])

        def build_pairs(
            directory: Path,
        ) -> tuple[list[dict[str, Any]], int, dict[str, Any], list[str], list[str]]:
            query_sql, params = sql.validation_pairs_export(run_id)
            frame = database.fetch_frame(query_sql, params)
            _guard_rows(len(frame), config)
            file_name = safe_file_name(request.file_name, "validation_pairs")
            files = [write_csv(frame, directory / file_name)]
            inputs = {"run_id": run_id, "n_pairs": int(run_row.get("n_pairs") or 0)}
            steps = [
                "Read the stored matched-pair table of the validation run.",
                "Ordered rows by pair_index.",
                "Wrote UTF-8 CSV with LF line endings and no value rewriting.",
            ]
            return files, int(len(frame)), inputs, steps, VALIDATION_LIMITATIONS

        return build_pairs, run_id

    run_row = _anomaly_run(database, request.run_id)
    run_id = str(run_row["run_id"])

    def build_anomalies(
        directory: Path,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any], list[str], list[str]]:
        query_sql, params = sql.anomalies_export(run_id)
        frame = database.fetch_frame(query_sql, params)
        _guard_rows(len(frame), config)
        file_name = safe_file_name(request.file_name, "anomalies")
        files = [write_csv(frame, directory / file_name)]
        inputs = {"run_id": run_id}
        steps = [
            "Read the flagged anomalies of the stored run.",
            "Ordered rows by robust z (strongest first), day, then anomaly id.",
            "Wrote UTF-8 CSV with LF line endings and no value rewriting.",
        ]
        return files, int(len(frame)), inputs, steps, ANOMALY_LIMITATIONS

    return build_anomalies, run_id


def create_csv(
    database: Database, config: dict[str, Any], request: CsvExportRequest
) -> dict[str, Any]:
    """Generic CSV export of observations or one stored run."""
    builder, run_id = _generic_builder(database, config, request)
    return _execute(
        database,
        config,
        kind="csv",
        source=request.source,
        params=request.model_dump(mode="json"),
        run_id=run_id,
        builder=builder,
    )


def create_harmonized(
    database: Database, config: dict[str, Any], request: HarmonizedExportRequest
) -> dict[str, Any]:
    """Export a harmonization run's per-cell rows plus reproducible metadata."""
    run_row = _harmonization_run(database, request.run_id)
    run_id = str(run_row["run_id"])

    def build(
        directory: Path,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any], list[str], list[str]]:
        query_sql, params = sql.harmonization_export(run_id)
        frame = database.fetch_frame(query_sql, params)
        _guard_rows(len(frame), config)
        file_name = safe_file_name(request.file_name, "harmonized_data")
        files = [write_csv(frame, directory / file_name)]
        inputs = {
            "run_id": run_id,
            "method": run_row.get("method"),
            "status": run_row.get("status"),
            "n_cells": run_row.get("n_cells"),
            "n_pairs_used_for_calibration": run_row.get("n_pairs"),
            "calibration": run_row.get("calibration"),
            "run_params": run_row.get("params"),
        }
        steps = [
            "Read the stored harmonization run record and its per-cell rows.",
            "Exported the rows ordered by cell_id, then time_bucket.",
            "Wrote the metadata sidecar with inputs, config snapshot, steps, limitations "
            "and software versions.",
        ]
        return files, int(len(frame)), inputs, steps, HARMONIZED_LIMITATIONS

    return _execute(
        database,
        config,
        kind="harmonized-data",
        source="harmonization-results",
        params=request.model_dump(mode="json"),
        run_id=run_id,
        builder=build,
    )


def create_validation_report(
    database: Database, config: dict[str, Any], request: ValidationReportRequest
) -> dict[str, Any]:
    """Export a validation run as a JSON report, optionally with its pairs."""
    run_row = _validation_run(database, request.run_id)
    run_id = str(run_row["run_id"])

    def build(
        directory: Path,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any], list[str], list[str]]:
        files: list[dict[str, Any]] = []
        report = {
            "run": run_row,
            "report_type": "validation_report",
            "time_basis": TIME_BASIS,
            "interpretation": (
                "Cross-sensor consistency on matched pairs; this is not accuracy, "
                "because the project has no independent reference dataset."
            ),
            "limitations": VALIDATION_LIMITATIONS,
            "software": software_versions(),
        }
        files.append(write_json(report, directory / "validation_report.json"))

        pairs_rows = 0
        if request.include_pairs:
            query_sql, params = sql.validation_pairs_export(run_id)
            frame = database.fetch_frame(query_sql, params)
            _guard_rows(len(frame), config)
            files.append(write_csv(frame, directory / "validation_pairs.csv"))
            pairs_rows = int(len(frame))

        inputs = {
            "run_id": run_id,
            "n_pairs": int(run_row.get("n_pairs") or 0),
            "pairs_included": request.include_pairs,
            "run_params": run_row.get("params"),
        }
        steps = [
            "Read the stored validation run including its metrics and limitations.",
            "Wrote the JSON report with the run parameters and metric definitions.",
            "Wrote the matched-pair table when include_pairs is true.",
        ]
        row_count = pairs_rows if request.include_pairs else int(run_row.get("n_pairs") or 0)
        return files, row_count, inputs, steps, VALIDATION_LIMITATIONS

    return _execute(
        database,
        config,
        kind="validation-report",
        source="validation-pairs",
        params=request.model_dump(mode="json"),
        run_id=run_id,
        builder=build,
    )


def resolve_file(
    database: Database, config: dict[str, Any], export_id: str, file_name: str | None
) -> tuple[dict[str, Any], Path]:
    """Resolve a downloadable file and refuse anything outside the export root."""
    record = get_export(database, export_id)
    if record is None:
        raise ApiError(
            "export_not_found", f"No export with id '{export_id}'.", 404
        )
    if record["status"] != "succeeded":
        raise ApiError(
            "export_not_ready",
            "This export failed and has no files.",
            409,
            {"error": record.get("error")},
        )

    files = record["files"]
    if not files:
        raise ApiError("export_file_missing", "This export recorded no files.", 410)

    target = files[0] if file_name is None else next(
        (item for item in files if item["name"] == file_name), None
    )
    if target is None:
        raise ApiError(
            "export_file_not_found",
            f"No file '{file_name}' in export '{export_id}'.",
            404,
            {"files": [item["name"] for item in files]},
        )

    path = (Path(record["directory"]) / target["name"]).resolve()
    root = _root(config).resolve()
    if not path.is_relative_to(root):
        raise ApiError(
            "export_file_outside_root",
            "The resolved file is outside the export directory.",
            400,
        )
    if not path.is_file():
        raise ApiError(
            "export_file_missing",
            "The export file is no longer on disk.",
            410,
            {"file": path.name},
        )
    return record, path
