"""Dataset ingestion: registration, import and sync.

Rules enforced here:
- Raw files are only ever read.
- A file path must resolve inside the project directory.
- The sensor is detected from the file header, never from the file name.
- Re-importing identical content is idempotent (matched by SHA-256).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from harmonizer.config import project_root, resolve_path
from harmonizer.io import fingerprint, load_detections
from harmonizer.io.loaders import detect_file_sensor
from harmonizer.store import Database
from harmonizer.store.db import OBSERVATION_INSERT_COLUMNS
from harmonizer.store.jobs import (
    create_job,
    finish_job,
    log_job,
    utcnow,
)

from ..errors import ApiError

ALLOWED_EXTENSIONS = {".csv"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _resolve_input(config: dict[str, Any], raw_path: str) -> Path:
    """Resolve a user-supplied path and refuse anything outside allowed roots.

    Allowed roots are the project directory plus the configured raw and upload
    directories (tests point these at temporary directories).
    """
    candidate = Path(raw_path)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (project_root() / candidate).resolve()
    )

    roots = {project_root().resolve()}
    for keys in (("paths", "raw"), ("paths", "uploads")):
        try:
            roots.add(resolve_path(config, *keys).resolve())
        except (KeyError, ValueError):
            continue

    if not any(resolved.is_relative_to(root) for root in roots):
        raise ApiError(
            "path_outside_project",
            "The path must resolve inside the project, raw or upload directory.",
            400,
            {"path": str(resolved)},
        )
    if not resolved.is_file():
        raise ApiError("file_not_found", f"No such file: {resolved}", 404)
    if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ApiError(
            "unsupported_file_type",
            f"Only {sorted(ALLOWED_EXTENSIONS)} files can be imported.",
            400,
        )
    return resolved


def _source_row(database: Database, source_id: str) -> dict[str, Any] | None:
    return database.fetch_one("SELECT * FROM sources WHERE source_id = ?", [source_id])


def _insert_source(
    database: Database,
    sensor: str,
    path: Path,
    file_size: int,
    file_mtime: float,
    sha256: str,
    status: str,
) -> dict[str, Any]:
    source_id = _new_id("src")
    now = utcnow()
    database.execute(
        "INSERT INTO sources (source_id, sensor, path, file_name, file_size, file_mtime, "
        "sha256, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            source_id,
            sensor,
            str(path),
            path.name,
            file_size,
            file_mtime,
            sha256,
            status,
            now,
            now,
        ],
    )
    return _source_row(database, source_id) or {}


def _import_row(database: Database, import_id: str) -> dict[str, Any] | None:
    return database.fetch_one("SELECT * FROM imports WHERE import_id = ?", [import_id])


def import_path(
    database: Database,
    config: dict[str, Any],
    sensor: str,
    raw_path: str,
    force: bool = False,
) -> dict[str, Any]:
    """Import one detection file and return the resulting import record."""
    resolved = _resolve_input(config, raw_path)

    detected = detect_file_sensor(resolved)
    if detected != sensor:
        raise ApiError(
            "sensor_mismatch",
            f"The endpoint expects '{sensor}' data but the file header looks like '{detected}'.",
            400,
            {"expected": sensor, "detected": detected, "path": str(resolved)},
        )

    file_info = fingerprint(resolved)
    existing = database.fetch_one(
        "SELECT * FROM sources WHERE sha256 = ? ORDER BY created_at LIMIT 1",
        [file_info.sha256],
    )

    if existing and existing["status"] == "imported" and not force:
        previous = database.fetch_one(
            "SELECT * FROM imports WHERE source_id = ? ORDER BY started_at DESC LIMIT 1",
            [existing["source_id"]],
        )
        return {
            "already_imported": True,
            "source": existing,
            "import": previous,
            "message": "This exact file content was imported before. Use force=true to re-run.",
        }

    if existing:
        source = existing
    else:
        source = _insert_source(
            database,
            sensor,
            resolved,
            file_info.size,
            file_info.mtime,
            file_info.sha256,
            "registered",
        )
    source_id = str(source["source_id"])

    job_id = create_job(
        database,
        f"ingestion.import.{sensor}",
        {"path": str(resolved), "sensor": sensor, "source_id": source_id},
    )
    import_id = _new_id("imp")
    started_at = utcnow()
    database.execute(
        "INSERT INTO imports (import_id, source_id, sensor, job_id, status, started_at) "
        "VALUES (?, ?, ?, ?, 'running', ?)",
        [import_id, source_id, sensor, job_id, started_at],
    )
    log_job(database, job_id, "info", f"Reading {resolved.name} ({file_info.size} bytes).")

    platform_mapping = (config.get("ingestion") or {}).get("platform_mapping") or {}

    try:
        loaded = load_detections(resolved, sensor, source_id, platform_mapping)
        log_job(database, job_id, "info", f"Validated {loaded.rows_read} rows.")
        if loaded.invalid_datetime:
            log_job(
                database,
                job_id,
                "warning",
                f"{loaded.invalid_datetime} rows have no parseable datetime (kept, not dropped).",
            )
        if loaded.duplicate_rows:
            log_job(
                database,
                job_id,
                "warning",
                f"{loaded.duplicate_rows} exact duplicate rows detected (kept, not deleted).",
            )

        inserted = database.insert_frame(
            "observations", loaded.frame, OBSERVATION_INSERT_COLUMNS
        )
        finished_at = utcnow()

        database.execute(
            "UPDATE sources SET status = 'imported', updated_at = ? WHERE source_id = ?",
            [finished_at, source_id],
        )
        database.execute(
            "UPDATE imports SET status = 'succeeded', rows_read = ?, rows_loaded = ?, "
            "duplicates = ?, finished_at = ? WHERE import_id = ?",
            [loaded.rows_read, inserted, loaded.duplicate_rows, finished_at, import_id],
        )
        result = {
            "import_id": import_id,
            "source_id": source_id,
            "job_id": job_id,
            "sensor": sensor,
            "rows_read": loaded.rows_read,
            "rows_loaded": inserted,
            "duplicate_rows": loaded.duplicate_rows,
            "invalid_datetime": loaded.invalid_datetime,
            "invalid_numeric": loaded.invalid_numeric,
        }
        log_job(database, job_id, "info", f"Inserted {inserted} new observations.")
        finish_job(database, job_id, "succeeded", result)
        return {"already_imported": False, "source": _source_row(database, source_id), **result}

    except ApiError:
        _mark_failed(database, import_id, source_id, job_id, "Validation error")
        raise
    except Exception as error:  # noqa: BLE001 - surfaced as a structured API error
        message = f"Import failed: {error}"
        _mark_failed(database, import_id, source_id, job_id, message)
        raise ApiError("import_failed", message, 500) from error


def _mark_failed(
    database: Database, import_id: str, source_id: str, job_id: str, message: str
) -> None:
    now = utcnow()
    database.execute(
        "UPDATE imports SET status = 'failed', error = ?, finished_at = ? WHERE import_id = ?",
        [message, now, import_id],
    )
    database.execute(
        "UPDATE sources SET status = 'failed', updated_at = ? WHERE source_id = ?",
        [now, source_id],
    )
    log_job(database, job_id, "error", message)
    finish_job(database, job_id, "failed", error=message)


def register_upload(
    database: Database, config: dict[str, Any], file_storage
) -> dict[str, Any]:
    """Save an uploaded file and register it as a source (no import yet)."""
    filename = (file_storage.filename or "").strip()
    if not filename:
        raise ApiError("missing_file", "Upload a file in the 'file' form field.", 400)

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ApiError(
            "unsupported_file_type",
            f"Only {sorted(ALLOWED_EXTENSIONS)} files can be uploaded.",
            400,
        )

    upload_dir = resolve_path(config, "paths", "uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name.replace(" ", "_")
    target = upload_dir / f"{uuid.uuid4().hex[:12]}_{safe_name}"
    file_storage.save(target)

    try:
        sensor = detect_file_sensor(target)
        if sensor is None:
            raise ApiError(
                "unsupported_schema",
                "The file header matches neither MODIS nor VIIRS active-fire columns.",
                400,
            )
        file_info = fingerprint(target)
        existing = database.fetch_one(
            "SELECT * FROM sources WHERE sha256 = ? ORDER BY created_at LIMIT 1",
            [file_info.sha256],
        )
        if existing:
            target.unlink(missing_ok=True)
            return {
                "source": existing,
                "already_registered": True,
                "message": "Identical file content is already registered.",
            }

        source = _insert_source(
            database,
            sensor,
            target,
            file_info.size,
            file_info.mtime,
            file_info.sha256,
            "uploaded",
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return {
        "source": source,
        "already_registered": False,
        "next": "POST /api/v1/ingestion/sync to import registered sources.",
    }


def sync(
    database: Database, config: dict[str, Any], sensors: list[str] | None
) -> dict[str, Any]:
    """Import every registered source that is not loaded yet."""
    clauses = ["status IN ('registered', 'uploaded', 'failed')"]
    params: list[Any] = []
    if sensors:
        placeholders = ", ".join("?" for _ in sensors)
        clauses.append(f"sensor IN ({placeholders})")
        params.extend(sensors)

    pending = database.fetch_all(
        f"SELECT * FROM sources WHERE {' AND '.join(clauses)} ORDER BY created_at",
        params,
    )

    results: list[dict[str, Any]] = []
    for source in pending:
        try:
            outcome = import_path(
                database, config, str(source["sensor"]), str(source["path"])
            )
            results.append(
                {
                    "source_id": source["source_id"],
                    "sensor": source["sensor"],
                    "status": "succeeded",
                    "rows_loaded": outcome.get("rows_loaded", 0),
                }
            )
        except ApiError as error:
            results.append(
                {
                    "source_id": source["source_id"],
                    "sensor": source["sensor"],
                    "status": "failed",
                    "error": {"code": error.code, "message": error.message},
                }
            )

    succeeded = sum(1 for item in results if item["status"] == "succeeded")
    return {
        "sources_checked": len(pending),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


def list_sources(
    database: Database, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """List registered sources with their observation counts."""
    total = int(database.fetch_scalar("SELECT count(*) FROM sources") or 0)
    rows = database.fetch_all(
        """
        SELECT s.*, coalesce(o.observation_count, 0) AS observation_count
        FROM sources s
        LEFT JOIN (
            SELECT source_id, count(*) AS observation_count
            FROM observations GROUP BY source_id
        ) o ON o.source_id = s.source_id
        ORDER BY s.created_at DESC, s.source_id
        LIMIT ? OFFSET ?
        """,
        [limit, offset],
    )
    return rows, total


def list_imports(
    database: Database, limit: int, offset: int, status: str | None, sensor: str | None
) -> tuple[list[dict[str, Any]], int]:
    """List import history, newest first."""
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("i.status = ?")
        params.append(status)
    if sensor:
        clauses.append("i.sensor = ?")
        params.append(sensor)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    total = int(
        database.fetch_scalar(f"SELECT count(*) FROM imports i {where}", params) or 0
    )
    rows = database.fetch_all(
        f"""
        SELECT i.*, s.file_name, s.path, s.file_size
        FROM imports i
        LEFT JOIN sources s ON s.source_id = i.source_id
        {where}
        ORDER BY i.started_at DESC NULLS LAST, i.import_id
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    )
    return rows, total


def get_import(database: Database, import_id: str) -> dict[str, Any] | None:
    """Return an import with its source and job logs."""
    record = database.fetch_one(
        """
        SELECT i.*, s.file_name, s.path, s.file_size, s.sha256
        FROM imports i
        LEFT JOIN sources s ON s.source_id = i.source_id
        WHERE i.import_id = ?
        """,
        [import_id],
    )
    if record is None:
        return None

    logs: list[dict[str, Any]] = []
    if record.get("job_id"):
        logs = database.fetch_all(
            "SELECT seq, ts, level, message FROM job_logs WHERE job_id = ? ORDER BY seq",
            [record["job_id"]],
        )
    return {**record, "logs": logs}
