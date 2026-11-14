"""Simple background job runner (no Celery/Redis).

A single daemon worker thread consumes queued jobs, marks them running, executes
a processing operation, and writes status, result and logs to DuckDB. Running
jobs are not interrupted; only queued jobs can be cancelled.
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any

from pydantic import ValidationError

from harmonizer.store import Database
from harmonizer.store import jobs as job_store

from .schemas.processing import PROCESSING_SCHEMAS

PROCESSING_PREFIX = "processing."


class JobRunner:
    """One worker thread backed by the shared DuckDB store."""

    def __init__(self, database: Database, config: dict[str, Any]) -> None:
        self._database = database
        self._config = config
        self._queue: queue.Queue[str] = queue.Queue()
        self._stopping = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="harmonizer-jobs", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the worker to stop after the current job and wait for it."""
        self._stopping.set()
        self._queue.put("")
        self._thread.join(timeout)

    def submit(self, kind: str, params: dict[str, Any]) -> str:
        """Queue a processing job and return its id."""
        if self._stopping.is_set():
            raise RuntimeError("Job runner is stopping.")
        job_id = job_store.create_job(
            self._database,
            f"{PROCESSING_PREFIX}{kind}",
            params,
            started=False,
        )
        job_store.log_job(self._database, job_id, "info", "Job queued.")
        self._queue.put(job_id)
        return job_id

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if not job_id or self._stopping.is_set():
                    return
                self._process(job_id)
            except Exception:  # noqa: BLE001 - worker must never die
                try:
                    self._database.execute(
                        "UPDATE jobs SET status = 'failed', error = ?, finished_at = ? "
                        "WHERE job_id = ? AND status != 'succeeded'",
                        [
                            "Worker crashed while handling the job.",
                            job_store.utcnow(),
                            job_id or "",
                        ],
                    )
                except Exception:  # noqa: BLE001 - store may already be closed
                    pass
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        job = job_store.get_job(self._database, job_id)
        if job is None or job["status"] == "cancelled":
            return

        self._database.execute(
            "UPDATE jobs SET status = 'running', started_at = ? WHERE job_id = ?",
            [job_store.utcnow(), job_id],
        )
        job_store.log_job(self._database, job_id, "info", "Job started.")

        kind = str(job["kind"])
        operation = kind[len(PROCESSING_PREFIX) :] if kind.startswith(PROCESSING_PREFIX) else kind
        schema = PROCESSING_SCHEMAS.get(operation)
        raw_params = job.get("params")
        params: dict[str, Any] = (
            json.loads(raw_params) if isinstance(raw_params, str) and raw_params else {}
        )

        try:
            if schema is None:
                raise ValueError(f"Unknown operation '{operation}'.")
            model = schema.model_validate(params)
            from .services import processing as processing_service

            result = processing_service.execute(
                self._database, self._config, operation, model, job_id=job_id
            )
            job_store.finish_job(self._database, job_id, "succeeded", result)
            job_store.log_job(
                self._database, job_id, "info", "Job finished successfully."
            )
        except ValidationError as error:
            message = f"Invalid job parameters: {error.errors(include_url=False)}"
            job_store.log_job(self._database, job_id, "error", message)
            job_store.finish_job(self._database, job_id, "failed", error=message)
        except Exception as error:  # noqa: BLE001 - reported through the job record
            message = str(error)
            job_store.log_job(self._database, job_id, "error", message)
            job_store.finish_job(self._database, job_id, "failed", error=message)
