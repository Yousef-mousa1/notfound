"""Job endpoints: /api/v1/jobs."""

from __future__ import annotations

from flask import Blueprint

from ...db import get_db
from ...errors import ApiError
from ...schemas.common import JobListQuery, JobLogsQuery
from ...serialization import jsonable, maybe_json
from ...services import jobs as service
from ..common import ok, page_meta, parse_query

jobs_blueprint = Blueprint("jobs", __name__)


def _serialize(job: dict) -> dict:
    return {
        **job,
        "params": maybe_json(job.get("params")),
        "result": maybe_json(job.get("result")),
    }


@jobs_blueprint.get("/jobs")
def list_jobs():
    """List jobs, newest first."""
    query = parse_query(JobListQuery)
    rows, total = service.list_jobs(get_db(), query)
    return ok(
        [jsonable(_serialize(row)) for row in rows],
        page_meta(total, query.limit, query.offset),
    )


@jobs_blueprint.get("/jobs/<job_id>")
def get_job(job_id: str):
    """Job detail."""
    job = service.get_job(get_db(), job_id)
    if job is None:
        raise ApiError("job_not_found", f"No job with id '{job_id}'.", 404)
    return ok(jsonable(_serialize(job)))


@jobs_blueprint.get("/jobs/<job_id>/status")
def get_job_status(job_id: str):
    """Compact job status for polling."""
    job = service.get_job(get_db(), job_id)
    if job is None:
        raise ApiError("job_not_found", f"No job with id '{job_id}'.", 404)
    return ok(
        jsonable(
            {
                "job_id": job["job_id"],
                "kind": job["kind"],
                "status": job["status"],
                "progress": job["progress"],
                "error": job["error"],
                "created_at": job["created_at"],
                "started_at": job["started_at"],
                "finished_at": job["finished_at"],
            }
        )
    )


@jobs_blueprint.get("/jobs/<job_id>/logs")
def get_job_logs(job_id: str):
    """Job log lines, pollable with ``after_seq``."""
    if service.get_job(get_db(), job_id) is None:
        raise ApiError("job_not_found", f"No job with id '{job_id}'.", 404)
    query = parse_query(JobLogsQuery)
    logs = service.get_logs(get_db(), job_id, query)
    return ok(jsonable(logs), {"after_seq": query.after_seq, "returned": len(logs)})


@jobs_blueprint.post("/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    """Cancel a queued or running job."""
    outcome, message = service.cancel(get_db(), job_id)
    if outcome == "not_found":
        raise ApiError("job_not_found", message, 404)
    if outcome == "not_cancellable":
        raise ApiError("job_not_cancellable", message, 409)
    return ok({"job_id": job_id, "status": "cancelled", "message": message})
