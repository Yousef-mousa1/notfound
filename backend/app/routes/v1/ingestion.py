"""Data ingestion endpoints: /api/v1/ingestion."""

from __future__ import annotations

from flask import Blueprint, current_app, request

from ...db import get_db
from ...errors import ApiError
from ...schemas.common import ImportListQuery, PageQuery
from ...schemas.ingestion import ImportRequest, SyncRequest
from ...serialization import jsonable
from ...services import ingestion as service
from ..common import ok, page_meta, parse_body, parse_query

ingestion_blueprint = Blueprint("ingestion", __name__)


def _config() -> dict:
    return current_app.config["HARMONIZER"]


@ingestion_blueprint.post("/ingestion/sources/import/modis")
def import_modis():
    """Import a MODIS detection file from disk."""
    body = parse_body(ImportRequest)
    result = service.import_path(
        get_db(), _config(), "modis", body.path, force=body.force
    )
    status = 200 if result.get("already_imported") else 201
    return ok(jsonable(result), {"sensor": "modis"}, status)


@ingestion_blueprint.post("/ingestion/sources/import/viirs")
def import_viirs():
    """Import a VIIRS detection file from disk."""
    body = parse_body(ImportRequest)
    result = service.import_path(
        get_db(), _config(), "viirs", body.path, force=body.force
    )
    status = 200 if result.get("already_imported") else 201
    return ok(jsonable(result), {"sensor": "viirs"}, status)


@ingestion_blueprint.post("/ingestion/files/upload")
def upload_file():
    """Upload a detection file and register it (import happens on sync)."""
    storage = request.files.get("file")
    if storage is None:
        raise ApiError(
            "missing_file",
            "Attach the file in the 'file' form field (multipart/form-data).",
            400,
        )
    result = service.register_upload(get_db(), _config(), storage)
    status = 200 if result.get("already_registered") else 201
    return ok(jsonable(result), {}, status)


@ingestion_blueprint.get("/ingestion/sources")
def list_sources():
    """List registered data sources."""
    query = parse_query(PageQuery)
    rows, total = service.list_sources(get_db(), query.limit, query.offset)
    return ok(jsonable(rows), page_meta(total, query.limit, query.offset))


@ingestion_blueprint.get("/ingestion/imports")
def list_imports():
    """List import history."""
    query = parse_query(ImportListQuery)
    rows, total = service.list_imports(
        get_db(), query.limit, query.offset, query.status, query.sensor
    )
    return ok(jsonable(rows), page_meta(total, query.limit, query.offset))


@ingestion_blueprint.get("/ingestion/imports/<import_id>")
def get_import(import_id: str):
    """Import detail including its job log."""
    record = service.get_import(get_db(), import_id)
    if record is None:
        raise ApiError("import_not_found", f"No import with id '{import_id}'.", 404)
    return ok(jsonable(record))


@ingestion_blueprint.post("/ingestion/sync")
def sync_sources():
    """Import every registered source that has not been loaded yet."""
    body = parse_body(SyncRequest, required=False)
    result = service.sync(get_db(), _config(), body.sensors)
    return ok(jsonable(result))
