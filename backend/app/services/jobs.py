"""Job inspection and cancellation."""

from __future__ import annotations

from typing import Any

from harmonizer.store import Database
from harmonizer.store import jobs as job_store

from ..schemas.common import JobListQuery, JobLogsQuery


def list_jobs(
    database: Database, query: JobListQuery
) -> tuple[list[dict[str, Any]], int]:
    """List jobs, newest first."""
    return job_store.list_jobs(database, query.status, query.kind, query.limit, query.offset)


def get_job(database: Database, job_id: str) -> dict[str, Any] | None:
    """Return one job, or ``None``."""
    return job_store.get_job(database, job_id)


def get_logs(database: Database, job_id: str, query: JobLogsQuery) -> list[dict[str, Any]]:
    """Return log lines after ``after_seq``."""
    return job_store.job_logs(database, job_id, query.after_seq, query.limit)


def cancel(database: Database, job_id: str) -> tuple[str, str]:
    """Cancel a queued or running job."""
    return job_store.cancel_job(database, job_id)
