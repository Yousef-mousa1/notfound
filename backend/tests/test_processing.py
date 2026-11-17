"""Processing endpoint tests.

The ``synthetic_*_match.csv`` fixtures are synthetic (clearly labelled) and are
used only for matching/flag mechanics: the 25-row real fixtures cover different
dates for MODIS and VIIRS, so they cannot exercise cross-sensor links.
"""

from __future__ import annotations

import time
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _call(client, method: str, path: str, body: dict | None = None):
    if method == "GET":
        return client.get(path)
    return client.post(path, json=body or {})


def _import_pair(client) -> None:
    for sensor, name in (
        ("modis", "synthetic_modis_match.csv"),
        ("viirs", "synthetic_viirs_match.csv"),
    ):
        response = client.post(
            f"/api/v1/ingestion/sources/import/{sensor}",
            json={"path": str(FIXTURES / name)},
        )
        assert response.status_code == 201, response.get_json()


def test_clean_dry_run_reports_flags_without_writing(client, imported):
    response = client.post("/api/v1/processing/clean", json={"dry_run": True})

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["rows"] == 50
    assert data["written"] is False
    assert set(data["flag_counts"]) >= {"invalid_ti4", "night_detection", "low_confidence"}
    assert any("never deleted" in note for note in data["notes"])


def test_clean_writes_flags_and_keeps_row_count(client):
    _import_pair(client)

    dry = client.post("/api/v1/processing/clean", json={"dry_run": True}).get_json()["data"]
    assert dry["flag_counts"]["invalid_ti4"] == 1
    assert dry["flag_counts"]["low_confidence"] == 1
    assert dry["flag_counts"]["night_detection"] == 1

    written = client.post("/api/v1/processing/clean", json={"dry_run": False}).get_json()["data"]
    assert written["written"] is True

    listing = client.get("/api/v1/observations?limit=1000").get_json()
    assert listing["meta"]["total"] == 5
    flagged = [row for row in listing["data"] if row["qc_flags"]]
    assert len(flagged) == 1
    assert "invalid_ti4" in flagged[0]["qc_flags"]


def test_filter_saves_selection(client, imported):
    response = client.post(
        "/api/v1/processing/filter",
        json={"sensor": "modis", "min_frp": 10, "name": "modis-high-frp"},
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["selection_id"].startswith("sel_")
    expected = client.get(
        "/api/v1/observations?limit=1&sensor=modis&min_frp=10"
    ).get_json()["meta"]["total"]
    assert data["detections"] == expected
    assert 0 < len(data["preview"]) <= 10


def test_normalize_applies_official_and_heuristic_confidence_mapping(client, app, imported):
    response = client.post("/api/v1/processing/normalize", json={"apply_confidence": True})

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["checks"]["rows"] == 50
    mapping = data["confidence_mapping"]
    assert mapping["applied"] is True
    assert mapping["rows"] == 50
    assert mapping["sensors"]["viirs"]["method"] == "exact"
    assert "FIRMS" in mapping["sensors"]["viirs"]["source"]
    assert mapping["sensors"]["modis"]["method"] == "ranges"
    assert "HEURISTIC" in mapping["sensors"]["modis"]["source"]

    database = app.extensions["db"]
    rows = database.fetch_all(
        "SELECT sensor, confidence_class, count(*) AS n FROM observations "
        "GROUP BY sensor, confidence_class"
    )
    counts = {(row["sensor"], row["confidence_class"]): row["n"] for row in rows}
    assert counts[("viirs", "nominal")] == 25
    assert counts[("modis", "low")] == 2
    assert counts[("modis", "nominal")] == 21
    assert counts[("modis", "high")] == 2


def test_normalize_skips_mapping_when_not_configured(client, app, imported):
    app.config["HARMONIZER"]["confidence"] = {}
    response = client.post("/api/v1/processing/normalize", json={"apply_confidence": True})

    assert response.status_code == 201
    mapping = response.get_json()["data"]["confidence_mapping"]
    assert mapping["applied"] is False
    assert "Phase 03" in mapping["reason"]


def test_grid_generate_and_fetch(client, imported):
    generated = client.post(
        "/api/v1/processing/grid/generate",
        json={"cell_km": 50, "name": "test-grid"},
    )
    assert generated.status_code == 201
    data = generated.get_json()["data"]
    grid_id = data["grid_id"]
    assert data["grid"]["cell_count"] > 0
    assert data["grid"]["area_distortion_pct"] >= 0

    fetched = client.get(f"/api/v1/processing/grid?grid_id={grid_id}").get_json()
    assert fetched["data"]["grid"]["grid_id"] == grid_id
    assert fetched["meta"]["total"] == data["grid"]["cell_count"]
    assert len(fetched["data"]["cells"]) == data["grid"]["cell_count"]

    listing = client.get("/api/v1/processing/grid").get_json()
    assert listing["meta"]["total"] == 1


def test_grid_validation_and_unknown_grid(client, imported):
    bad = client.post("/api/v1/processing/grid/generate", json={"cell_km": 0})
    assert bad.status_code == 422

    unknown = client.post(
        "/api/v1/processing/aggregate", json={"grid_id": "grid_missing"}
    )
    assert unknown.status_code == 404
    assert unknown.get_json()["error"]["code"] == "grid_not_found"


def test_aggregate_keeps_sensors_separate(client, imported):
    grid_id = client.post(
        "/api/v1/processing/grid/generate", json={"cell_km": 100}
    ).get_json()["data"]["grid_id"]

    response = client.post(
        "/api/v1/processing/aggregate", json={"grid_id": grid_id, "time_bucket": "none"}
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["cells_with_detections"] >= 1
    assert data["total_detections"] == 50
    assert {row["sensor"] for row in data["sample"]} == {"modis", "viirs"}

    daily = client.post(
        "/api/v1/processing/aggregate",
        json={"grid_id": grid_id, "time_bucket": "day"},
    ).get_json()["data"]
    assert daily["time_bucket"] == "day"


def test_features_extraction(client, imported):
    grid_id = client.post(
        "/api/v1/processing/grid/generate", json={"cell_km": 100}
    ).get_json()["data"]["grid_id"]

    response = client.post(
        "/api/v1/processing/features/extract", json={"grid_id": grid_id}
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["rows"] >= 2
    assert "distinct_days" in data["features"]
    assert data["total_detections"] == 50


def test_spatial_matching_links_without_deleting(client):
    _import_pair(client)

    response = client.post(
        "/api/v1/processing/spatial-matching",
        json={"radius_m": 2000, "time_window_h": 1},
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["pairs"] == 2
    assert data["truncated"] is False
    assert all(link["distance_m"] <= 2000 for link in data["sample"])

    observations = client.get("/api/v1/observations?limit=1000").get_json()
    assert observations["meta"]["total"] == 5


def test_temporal_matching_uses_time_only(client):
    _import_pair(client)

    response = client.post(
        "/api/v1/processing/temporal-matching", json={"time_window_h": 1}
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["pairs"] == 2
    assert all(abs(link["delta_t_s"]) <= 3600 for link in data["sample"])


def test_matching_requires_radius(client):
    response = client.post("/api/v1/processing/spatial-matching", json={})
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"


def test_async_processing_job(client, imported):
    response = client.post(
        "/api/v1/processing/jobs",
        json={"kind": "clean", "params": {"dry_run": True}},
    )
    assert response.status_code == 202
    job_id = response.get_json()["data"]["job_id"]

    deadline = time.time() + 15
    status = "queued"
    while time.time() < deadline:
        payload = client.get(f"/api/v1/jobs/{job_id}/status").get_json()["data"]
        status = payload["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.1)

    assert status == "succeeded"
    assert client.get(f"/api/v1/processing/jobs/{job_id}").status_code == 200

    logs = client.get(f"/api/v1/jobs/{job_id}/logs").get_json()["data"]
    assert any("finished successfully" in line["message"] for line in logs)


def test_async_job_with_invalid_params_fails(client, imported):
    response = client.post(
        "/api/v1/processing/jobs",
        json={"kind": "aggregate", "params": {"grid_id": "grid_missing"}},
    )
    assert response.status_code == 202
    job_id = response.get_json()["data"]["job_id"]

    deadline = time.time() + 15
    status = "queued"
    while time.time() < deadline:
        payload = client.get(f"/api/v1/jobs/{job_id}/status").get_json()["data"]
        status = payload["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.1)

    assert status == "failed"
    assert "grid" in (payload["error"] or "").lower()


def test_queued_job_can_be_cancelled(app, imported):
    database = app.extensions["db"]
    client = app.test_client()

    job_id = client.post(
        "/api/v1/processing/jobs", json={"kind": "clean", "params": {"dry_run": True}}
    ).get_json()["data"]["job_id"]

    # The worker may already be done; a queued job must be cancellable.
    response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code in {200, 409}
    if response.status_code == 409:
        assert database.fetch_scalar(
            "SELECT status FROM jobs WHERE job_id = ?", [job_id]
        ) in {"succeeded", "failed"}
