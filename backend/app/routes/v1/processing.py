"""Processing endpoints: /api/v1/processing."""

from __future__ import annotations

from flask import Blueprint, current_app

from harmonizer.store import jobs as job_store

from ...db import get_db
from ...errors import ApiError
from ...schemas.processing import (
    AggregateRequest,
    CleanRequest,
    FeaturesRequest,
    FilterRequest,
    GridGenerateRequest,
    GridListQuery,
    NormalizeRequest,
    ProcessingJobRequest,
    PROCESSING_SCHEMAS,
    SpatialMatchRequest,
    TemporalMatchRequest,
)
from ...serialization import jsonable
from ...services import processing as service
from ...services import jobs as jobs_service
from ..common import ok, page_meta, parse_body, parse_query

processing_blueprint = Blueprint("processing", __name__)


def _config() -> dict:
    return current_app.config["HARMONIZER"]


def _run_sync(kind: str, model) -> tuple:
    database = get_db()
    job_id = job_store.create_job(database, f"processing.{kind}", model.model_dump())
    job_store.log_job(database, job_id, "info", f"Running processing operation '{kind}'.")
    try:
        result = service.execute(database, _config(), kind, model, job_id=job_id)
    except ApiError as error:
        job_store.log_job(database, job_id, "error", error.message)
        job_store.finish_job(database, job_id, "failed", error=error.message)
        raise
    except Exception as error:  # noqa: BLE001 - surfaced as a structured error
        job_store.log_job(database, job_id, "error", str(error))
        job_store.finish_job(database, job_id, "failed", error=str(error))
        raise

    job_store.log_job(database, job_id, "info", "Processing operation finished.")
    job_store.finish_job(database, job_id, "succeeded", result)
    return ok(jsonable({**result, "job_id": job_id}), {"kind": kind}, 201)


@processing_blueprint.post("/processing/clean")
def clean():
    """Recompute non-destructive QC flags."""
    return _run_sync("clean", parse_body(CleanRequest))


@processing_blueprint.post("/processing/filter")
def filter_observations():
    """Save a filter selection without deleting anything."""
    return _run_sync("filter", parse_body(FilterRequest))


@processing_blueprint.post("/processing/normalize")
def normalize():
    """Check structural normalization and optionally apply a configured mapping."""
    return _run_sync("normalize", parse_body(NormalizeRequest))


@processing_blueprint.post("/processing/spatial-matching")
def spatial_matching():
    """Link MODIS and VIIRS detections by geodesic distance."""
    return _run_sync("spatial-matching", parse_body(SpatialMatchRequest))


@processing_blueprint.post("/processing/temporal-matching")
def temporal_matching():
    """Link MODIS and VIIRS detections by acquisition time."""
    return _run_sync("temporal-matching", parse_body(TemporalMatchRequest))


@processing_blueprint.post("/processing/grid/generate")
def generate_grid():
    """Create a spatial grid for aggregation."""
    return _run_sync("grid", parse_body(GridGenerateRequest))


@processing_blueprint.get("/processing/grid")
def get_grid():
    """Return a grid with its cells, or list stored grids."""
    query = parse_query(GridListQuery)
    if query.grid_id:
        grid = service.get_grid(get_db(), query.grid_id)
        cells = service.grid_cells(get_db(), query.grid_id, query.limit, query.offset)
        return ok(
            jsonable({"grid": grid, "cells": cells}),
            {
                "grid_id": query.grid_id,
                **page_meta(grid["n_rows"] * grid["n_cols"], query.limit, query.offset),
            },
        )

    rows, total = service.list_grids(get_db(), query.limit, query.offset)
    return ok(jsonable(rows), page_meta(total, query.limit, query.offset))


@processing_blueprint.post("/processing/aggregate")
def aggregate():
    """Aggregate detections per grid cell, sensors kept separate."""
    return _run_sync("aggregate", parse_body(AggregateRequest))


@processing_blueprint.post("/processing/features/extract")
def extract_features():
    """Extract per-cell features, sensors kept separate."""
    return _run_sync("features", parse_body(FeaturesRequest))


@processing_blueprint.post("/processing/jobs")
def submit_processing_job():
    """Queue a processing operation and return immediately."""
    body = parse_body(ProcessingJobRequest)
    schema = PROCESSING_SCHEMAS[body.kind]
    try:
        params = schema.model_validate(body.params)
    except Exception as error:  # pydantic ValidationError
        raise ApiError(
            "validation_error", "Invalid job parameters.", 422, str(error)
        ) from error

    runner = current_app.extensions["job_runner"]
    job_id = runner.submit(body.kind, jsonable(params.model_dump()))
    return ok(
        {"job_id": job_id, "kind": body.kind, "status": "queued"},
        {"poll": f"/api/v1/jobs/{job_id}"},
        202,
    )


@processing_blueprint.get("/processing/jobs/<job_id>")
def get_processing_job(job_id: str):
    """Return the job record for a processing job."""
    job = jobs_service.get_job(get_db(), job_id)
    if job is None:
        raise ApiError("job_not_found", f"No job with id '{job_id}'.", 404)
    return ok(jsonable(job))
