"""Export endpoints: /api/v1/exports.

An export is a new file plus a stored record. JSON responses describe the
record and link to the files; ``?download=true`` returns the file itself.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from flask import Blueprint, current_app, send_file, url_for

from ...db import get_db
from ...errors import ApiError
from ...schemas.exports import (
    CsvExportRequest,
    EstimateExportRequest,
    ExportFileQuery,
    ExportHistoryQuery,
    HarmonizedExportRequest,
    ObservationExportRequest,
    ValidationReportRequest,
)
from ...serialization import TIME_BASIS, jsonable
from ...services import exports as service
from ..common import ok, page_meta, parse_body, parse_query

exports_blueprint = Blueprint("exports", __name__)

MIMETYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
}


def _with_links(record: dict) -> dict:
    """Add download links without recomputing anything."""
    files = []
    for item in record.get("files") or []:
        files.append(
            {
                **item,
                "download_url": url_for(
                    "exports.get_export",
                    export_id=record["export_id"],
                    download="true",
                    file=item["name"],
                ),
            }
        )
    payload = {**record, "files": files}
    payload["download_url"] = files[0]["download_url"] if files else None
    return jsonable(payload)


def _meta(note: str) -> dict:
    return {
        "note": note,
        "time_basis": TIME_BASIS,
        "limitations_included": True,
        "download_hint": "Append ?download=true to the download_url to fetch the file.",
    }


def _stateless(config: dict) -> bool:
    """True on read-only hosts that must stream the file in the create response."""
    return bool((config.get("exports") or {}).get("stateless", False))


def _zip_response(record: dict) -> "Response":
    """Stream every export file as one ZIP attachment, built in memory.

    Vercel Functions do not share /tmp between invocations, so a separate
    download request cannot rely on a file written by the create request.
    Packaging in the same request removes that dependency entirely. The
    metadata sidecar (with limitations) is included alongside the data.
    """
    buffer = io.BytesIO()
    root = Path(record["directory"])
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in record.get("files") or []:
            path = (root / item["name"]).resolve()
            if path.is_file():
                archive.write(path, arcname=item["name"])
    buffer.seek(0)
    response = send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{record['export_id']}.zip",
    )
    response.headers["X-Export-Id"] = record["export_id"]
    return response


def _created(record: dict, config: dict, note: str):
    """Return the file directly (stateless) or the JSON record (stateful)."""
    if _stateless(config):
        return _zip_response(record)
    return ok(_with_links(record), _meta(note), 201)


@exports_blueprint.post("/exports/csv")
def export_csv():
    """Create a generic CSV export of observations or one stored run."""
    request = parse_body(CsvExportRequest)
    config = current_app.config["HARMONIZER"]
    record = service.create_csv(get_db(), config, request)
    return _created(
        record, config, "CSV export created; stored data was not modified."
    )


@exports_blueprint.post("/exports/observations")
def export_observations():
    """Export filtered observations to CSV plus a metadata sidecar."""
    request = parse_body(ObservationExportRequest)
    config = current_app.config["HARMONIZER"]
    record = service.create_observations(get_db(), config, request)
    return _created(
        record,
        config,
        "Observation export contains detected hot spots only; absence of a row is "
        "not evidence of no fire.",
    )


@exports_blueprint.post("/exports/harmonized-data")
def export_harmonized():
    """Export a harmonization run's per-cell rows plus metadata."""
    request = parse_body(HarmonizedExportRequest)
    config = current_app.config["HARMONIZER"]
    record = service.create_harmonized(get_db(), config, request)
    return _created(
        record,
        config,
        "Harmonization is a cross-sensor mapping, not a physical correction; "
        "MODIS is not ground truth.",
    )


@exports_blueprint.post("/exports/estimate-series")
def export_estimate_series():
    """Export the model-produced harmonized estimate series plus metadata."""
    request = parse_body(EstimateExportRequest)
    config = current_app.config["HARMONIZER"]
    record = service.create_estimates(get_db(), config, request)
    return _created(
        record,
        config,
        "Model-produced estimates, including backcasts; these are not FIRMS "
        "detections and no row is absent because there was no fire.",
    )


@exports_blueprint.post("/exports/validation-report")
def export_validation_report():
    """Export a validation run as a JSON report, optionally with its pairs."""
    request = parse_body(ValidationReportRequest)
    config = current_app.config["HARMONIZER"]
    record = service.create_validation_report(get_db(), config, request)
    return _created(
        record,
        config,
        "Validation results are cross-sensor consistency, never accuracy.",
    )


@exports_blueprint.get("/exports/history")
def export_history():
    """List export records, newest first."""
    query = parse_query(ExportHistoryQuery)
    records, total = service.history(
        get_db(), query.kind, query.status, query.limit, query.offset,
        current_app.config["HARMONIZER"],
    )
    return ok(
        [_with_links(record) for record in records],
        {
            **page_meta(total, query.limit, query.offset),
            "note": "Only metadata is listed; fetch a file through its download_url.",
        },
    )


@exports_blueprint.get("/exports/<export_id>")
def get_export(export_id: str):
    """Return an export record, or the file itself with ``?download=true``."""
    query = parse_query(ExportFileQuery)
    config = current_app.config["HARMONIZER"]

    if not query.download:
        record = service.get_export(get_db(), export_id, config)
        if record is None:
            raise ApiError(
                "export_not_found", f"No export with id '{export_id}'.", 404
            )
        return ok(_with_links(record), _meta("Export record; append ?download=true."))

    record, path = service.resolve_file(get_db(), config, export_id, query.file)
    descriptor = next(
        (
            item
            for item in record["files"]
            if item["name"] == path.name
        ),
        {},
    )
    response = send_file(
        path,
        mimetype=MIMETYPES.get(path.suffix.lower(), "application/octet-stream"),
        as_attachment=True,
        download_name=path.name,
    )
    if descriptor.get("sha256"):
        response.headers["X-Export-Sha256"] = descriptor["sha256"]
    response.headers["X-Export-Id"] = record["export_id"]
    return response
