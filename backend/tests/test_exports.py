"""Export endpoint tests (Slice E).

Exports must never modify stored data, must stay asymmetric (no invented
values) and must carry reproducible metadata. The synthetic calibration
fixtures are only used to create a stored run to export.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _import_calibration_pair(client) -> None:
    for sensor, name in (
        ("modis", "synthetic_modis_calibration.csv"),
        ("viirs", "synthetic_viirs_calibration.csv"),
    ):
        response = client.post(
            f"/api/v1/ingestion/sources/import/{sensor}",
            json={"path": str(FIXTURES / name)},
        )
        assert response.status_code == 201, response.get_json()


def _harmonization_run(client) -> str:
    _import_calibration_pair(client)
    grid_id = client.post(
        "/api/v1/processing/grid/generate", json={"cell_km": 100}
    ).get_json()["data"]["grid_id"]
    response = client.post(
        "/api/v1/harmonization/run",
        json={"grid_id": grid_id, "time_bucket": "day", "method": "none"},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]["run_id"]


def _validation_run(client) -> str:
    _import_calibration_pair(client)
    response = client.post(
        "/api/v1/validation/run", json={"radius_m": 2000, "time_window_h": 2}
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]["run_id"]


def _csv_rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"))))


def test_observation_export_writes_csv_and_metadata(client, imported):
    response = client.post(
        "/api/v1/exports/observations", json={"sensor": "modis"}
    )

    assert response.status_code == 201, response.get_json()
    record = response.get_json()["data"]
    assert record["export_id"].startswith("exp_")
    assert record["kind"] == "observations"
    assert record["status"] == "succeeded"
    assert record["row_count"] == 25
    names = [item["name"] for item in record["files"]]
    assert names == ["observations.csv", "metadata.json"]
    assert record["download_url"].endswith("download=true&file=observations.csv")
    assert "/api/v1/exports/" in record["download_url"]
    assert all("download_url" in item for item in record["files"])

    download = client.get(record["download_url"])
    assert download.status_code == 200
    assert download.headers["Content-Type"].startswith("text/csv")
    assert download.headers["X-Export-Sha256"] == record["files"][0]["sha256"]
    assert "attachment" in download.headers["Content-Disposition"]

    rows = _csv_rows(download.data)
    assert len(rows) == 25
    assert {row["sensor"] for row in rows} == {"modis"}
    assert "raw_json" not in rows[0]
    assert rows[0]["frp_mw"] != ""


def test_observation_export_keeps_stored_values(client, imported):
    stored = client.get(
        "/api/v1/observations?sensor=modis&limit=1000"
    ).get_json()["data"]
    response = client.post(
        "/api/v1/exports/observations", json={"sensor": "modis"}
    )
    rows = _csv_rows(client.get(response.get_json()["data"]["download_url"]).data)

    exported = {row["observation_id"]: row["frp_mw"] for row in rows}
    for observation in stored:
        assert exported[observation["observation_id"]] == str(observation["frp_mw"])


def test_metadata_sidecar_is_reproducible(client, imported):
    record = client.post(
        "/api/v1/exports/observations", json={"sensor": "viirs"}
    ).get_json()["data"]

    metadata_file = next(
        item for item in record["files"] if item["name"] == "metadata.json"
    )
    response = client.get(metadata_file["download_url"])
    assert response.status_code == 200

    metadata = json.loads(response.data.decode("utf-8"))
    assert metadata["export_id"] == record["export_id"]
    assert metadata["inputs"]["rows"] == 25
    assert metadata["inputs"]["filters"]["sensor"] == "viirs"
    assert metadata["config_snapshot"]["api"]["prefix"] == "/api/v1"
    assert metadata["software"]["harmonizer"]
    assert metadata["steps"]
    assert any("detections only" in note for note in metadata["limitations"])
    assert "time_basis" in metadata


def test_repeated_export_reproduces_the_same_data_file(client, imported):
    first = client.post(
        "/api/v1/exports/observations", json={"sensor": "modis"}
    ).get_json()["data"]
    second = client.post(
        "/api/v1/exports/observations", json={"sensor": "modis"}
    ).get_json()["data"]

    assert first["export_id"] != second["export_id"]
    assert first["files"][0]["name"] == second["files"][0]["name"] == "observations.csv"
    assert first["files"][0]["sha256"] == second["files"][0]["sha256"]
    assert first["files"][0]["byte_size"] == second["files"][0]["byte_size"]


def test_generic_csv_rejects_incomplete_requests(client, imported):
    missing_run = client.post(
        "/api/v1/exports/csv", json={"source": "harmonization-results"}
    )
    assert missing_run.status_code == 409
    assert missing_run.get_json()["error"]["code"] == "no_harmonization_run"

    filters = client.post(
        "/api/v1/exports/csv",
        json={"source": "anomalies", "run_id": "ano_x", "sensor": "modis"},
    )
    assert filters.status_code == 422

    raw = client.post(
        "/api/v1/exports/csv",
        json={"source": "validation-pairs", "run_id": "val_x", "include_raw_json": True},
    )
    assert raw.status_code == 422


def test_generic_csv_defaults_to_latest_run(client):
    run_id = _harmonization_run(client)

    response = client.post(
        "/api/v1/exports/csv", json={"source": "harmonization-results"}
    )

    assert response.status_code == 201, response.get_json()
    record = response.get_json()["data"]
    assert record["kind"] == "csv"
    assert record["source_run_id"] == run_id
    assert record["metadata"]["inputs"]["run_id"] == run_id
    assert record["row_count"] > 0


def test_harmonized_export_uses_latest_run(client):
    run_id = _harmonization_run(client)

    response = client.post("/api/v1/exports/harmonized-data", json={})

    assert response.status_code == 201, response.get_json()
    record = response.get_json()["data"]
    assert record["kind"] == "harmonized-data"
    assert record["source_run_id"] == run_id
    assert record["metadata"]["inputs"]["run_id"] == run_id
    assert record["row_count"] > 0

    rows = _csv_rows(client.get(record["download_url"]).data)
    assert len(rows) == record["row_count"]
    assert "harmonized_activity_index" in rows[0]
    assert "sensors_present" in rows[0]
    assert any("not a physical correction" in note for note in record["metadata"]["limitations"])


def test_harmonized_export_without_run_returns_409(client, imported):
    response = client.post("/api/v1/exports/harmonized-data", json={})

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_harmonization_run"


def test_validation_report_exports_metrics_and_pairs(client):
    run_id = _validation_run(client)

    response = client.post(
        "/api/v1/exports/validation-report", json={"run_id": run_id}
    )

    assert response.status_code == 201, response.get_json()
    record = response.get_json()["data"]
    assert record["kind"] == "validation-report"
    assert [item["name"] for item in record["files"]] == [
        "validation_report.json",
        "validation_pairs.csv",
        "metadata.json",
    ]
    assert record["row_count"] == 12

    report = json.loads(
        client.get(record["download_url"]).data.decode("utf-8")
    )
    assert report["run"]["run_id"] == run_id
    assert report["run"]["metrics"]["n_pairs"] == 12
    assert "not accuracy" in report["interpretation"]

    pairs = _csv_rows(client.get(record["files"][1]["download_url"]).data)
    assert len(pairs) == 12
    assert "distance_m" in pairs[0]


def test_history_lists_and_filters_exports(client, imported):
    first = client.post(
        "/api/v1/exports/observations", json={"sensor": "modis"}
    ).get_json()["data"]
    second = client.post(
        "/api/v1/exports/csv", json={"source": "observations"}
    ).get_json()["data"]

    listing = client.get("/api/v1/exports/history").get_json()
    assert listing["meta"]["total"] == 2
    assert {row["export_id"] for row in listing["data"]} == {
        first["export_id"],
        second["export_id"],
    }
    assert all(row["download_url"] for row in listing["data"])

    filtered = client.get("/api/v1/exports/history?kind=csv").get_json()
    assert filtered["meta"]["total"] == 1
    assert filtered["data"][0]["kind"] == "csv"


def test_export_record_and_file_errors(client, imported):
    missing = client.get("/api/v1/exports/exp_missing")
    assert missing.status_code == 404
    assert missing.get_json()["error"]["code"] == "export_not_found"

    record = client.post(
        "/api/v1/exports/observations", json={"sensor": "modis"}
    ).get_json()["data"]

    wrong_file = client.get(
        f"/api/v1/exports/{record['export_id']}?download=true&file=nope.csv"
    )
    assert wrong_file.status_code == 404
    assert wrong_file.get_json()["error"]["code"] == "export_file_not_found"

    record_only = client.get(f"/api/v1/exports/{record['export_id']}").get_json()["data"]
    assert record_only["files"][0]["sha256"] == record["files"][0]["sha256"]


def test_export_row_limit_is_enforced(client, imported, app):
    app.config["HARMONIZER"]["exports"]["max_rows"] = 10

    response = client.post("/api/v1/exports/observations", json={})

    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "export_too_large"
    history = client.get("/api/v1/exports/history").get_json()
    assert history["meta"]["total"] == 0


def _estimate_run(client, tmp_path: Path) -> str:
    from test_estimates import RUN_ID, _import, _register, _write_series

    assert _register(client, RUN_ID).status_code == 201
    assert _import(client, _write_series(tmp_path), RUN_ID).status_code == 201
    return RUN_ID


def test_estimate_series_export(client, tmp_path: Path):
    run_id = _estimate_run(client, tmp_path)

    response = client.post("/api/v1/exports/estimate-series", json={})

    assert response.status_code == 201, response.get_json()
    record = response.get_json()["data"]
    assert record["kind"] == "estimate-series"
    assert record["source"] == "estimates"
    assert record["source_run_id"] == run_id
    assert record["row_count"] == 8
    assert [item["name"] for item in record["files"]] == [
        "harmonized_estimates.csv",
        "metadata.json",
    ]

    rows = _csv_rows(client.get(record["download_url"]).data)
    assert len(rows) == 8
    for column in ("scale", "value", "is_estimate", "coverage_corrected", "baseline", "model"):
        assert column in rows[0]
    # Observed and backcast rows stay separate, never merged.
    assert {row["is_estimate"] for row in rows} == {"True", "False"}

    metadata_file = next(
        item for item in record["files"] if item["name"] == "metadata.json"
    )
    metadata = json.loads(client.get(metadata_file["download_url"]).data.decode("utf-8"))
    assert metadata["inputs"]["run_id"] == run_id
    assert any("not FIRMS detections" in note for note in metadata["limitations"])


def test_estimate_series_scale_filter(client, tmp_path: Path):
    run_id = _estimate_run(client, tmp_path)

    response = client.post(
        "/api/v1/exports/estimate-series",
        json={"run_id": run_id, "scale": "viirs_harmonized"},
    )

    assert response.status_code == 201, response.get_json()
    record = response.get_json()["data"]
    rows = _csv_rows(client.get(record["download_url"]).data)
    assert len(rows) == 8
    assert {row["scale"] for row in rows} == {"viirs_harmonized"}


def test_estimate_series_rejects_bad_scale(client, tmp_path: Path):
    _estimate_run(client, tmp_path)
    response = client.post(
        "/api/v1/exports/estimate-series", json={"scale": "raw"}
    )
    assert response.status_code == 422


def test_estimate_series_without_run_returns_409(client):
    response = client.post("/api/v1/exports/estimate-series", json={})
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_model_run"
