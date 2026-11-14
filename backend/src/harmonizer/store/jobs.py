"""Job records and logs.

Phase 00 decision: a simple in-process runner with status stored on disk.
No Celery/Redis. Ingestion runs synchronously inside a job record; long-running
processing jobs (Slice B) will reuse the same records.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import Database

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
CANCELLABLE_STATUSES = frozenset({"queued", "running"})


def utcnow() -> datetime:
    """Return the current UTC time as a naive timestamp.

    Naive storage is deliberate: the time basis (UTC) is an assumption pending
    verification, and DuckDB TIMESTAMP has no zone.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_job(
    db: Database,
    kind: str,
    params: dict[str, Any] | None = None,
    started: bool = True,
) -> str:
    """Create a job record and return its id."""
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    now = utcnow()
    db.execute(
        "INSERT INTO jobs (job_id, kind, status, params, progress, created_at, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            job_id,
            kind,
            "running" if started else "queued",
            json.dumps(params or {}, default=str),
            0.0,
            now,
            now if started else None,
        ],
    )
    return job_id


def log_job(db: Database, job_id: str, level: str, message: str) -> None:
    """Append a log line to a job.

    The sequence number is computed inside the insert so that two threads
    logging to the same job cannot both read the same ``max(seq)`` (the API
    thread can cancel a job while the runner thread is logging a step).
    """
    db.execute(
        "INSERT INTO job_logs (job_id, seq, ts, level, message) "
        "SELECT ?, coalesce(max(seq), 0) + 1, ?, ?, ? "
        "FROM job_logs WHERE job_id = ?",
        [job_id, utcnow(), level.upper(), message, job_id],
    )


def finish_job(
    db: Database,
    job_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Mark a job as finished with a result or an error."""
    db.execute(
        "UPDATE jobs SET status = ?, result = ?, error = ?, progress = ?, finished_at = ? "
        "WHERE job_id = ?",
        [
            status,
            json.dumps(result, default=str) if result is not None else None,
            error,
            1.0 if status == "succeeded" else None,
            utcnow(),
            job_id,
        ],
    )


def get_job(db: Database, job_id: str) -> dict[str, Any] | None:
    """Return a job record, or ``None`` if it does not exist."""
    return db.fetch_one("SELECT * FROM jobs WHERE job_id = ?", [job_id])


def list_jobs(
    db: Database,
    status: str | None,
    kind: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """List jobs, newest first, with a total count."""
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    total = int(db.fetch_scalar(f"SELECT count(*) FROM jobs {where}", params) or 0)
    rows = db.fetch_all(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC, job_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return rows, total


def job_logs(
    db: Database, job_id: str, after_seq: int, limit: int
) -> list[dict[str, Any]]:
    """Return job log lines ordered by sequence."""
    return db.fetch_all(
        "SELECT seq, ts, level, message FROM job_logs "
        "WHERE job_id = ? AND seq > ? ORDER BY seq LIMIT ?",
        [job_id, after_seq, limit],
    )


def cancel_job(db: Database, job_id: str) -> tuple[str, str]:
    """Attempt to cancel a job.

    Returns:
        ``(outcome, message)`` where outcome is ``"cancelled"``,
        ``"not_found"`` or ``"not_cancellable"``.
    """
    job = get_job(db, job_id)
    if job is None:
        return "not_found", "Job does not exist."
    if job["status"] not in CANCELLABLE_STATUSES:
        return (
            "not_cancellable",
            f"Job is already '{job['status']}' and cannot be cancelled.",
        )

    db.execute(
        "UPDATE jobs SET status = 'cancelled', finished_at = ?, error = ? WHERE job_id = ?",
        [utcnow(), "Cancelled by user.", job_id],
    )
    log_job(db, job_id, "warning", "Job cancelled by user.")
    return "cancelled", "Job cancelled."
