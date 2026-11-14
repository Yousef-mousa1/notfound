"""Anomaly endpoint tests.

``synthetic_modis_anomaly.csv`` is synthetic (clearly labelled): one grid cell
with six daily counts [1, 1, 1, 1, 1, 10], so the last day is an obvious
statistical outlier. It tests mechanics, not real fire behaviour.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _import_anomaly_fixture(client) -> None:
    response = client.post(
        "/api/v1/ingestion/sources/import/modis",
        json={"path": str(FIXTURES / "synthetic_modis_anomaly.csv")},
    )
    assert response.status_code == 201, response.get_json()


def _grid(client, cell_km: int = 25) -> str:
    response = client.post(
        "/api/v1/processing/grid/generate", json={"cell_km": cell_km}
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]["grid_id"]


def _detect(client, grid_id: str, **overrides):
    body = {"grid_id": grid_id}
    body.update(overrides)
    return client.post("/api/v1/anomalies/detect", json=body)


def test_detect_flags_spike_with_poisson_fallback(client):
    _import_anomaly_fixture(client)
    grid_id = _grid(client)

    response = _detect(client, grid_id)

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["stats"]["series_evaluated"] == 1
    assert data["stats"]["cell_days_evaluated"] == 6
    assert data["stats"]["anomalies"] == 1
    assert data["stats"]["severity_counts"]["extreme"] == 1
    row = data["sample"][0]
    assert row["detections"] == 10
    assert row["baseline_median"] == 1.0
    assert row["baseline_scale"] == 1.0
    assert row["robust_z"] == 9.0
    assert row["severity"] == "extreme"
    assert data["thresholds"]["min_days"] == 5


def test_anomaly_list_filters_and_detail(client):
    _import_anomaly_fixture(client)
    grid_id = _grid(client)
    run_id = _detect(client, grid_id).get_json()["data"]["run_id"]

    listing = client.get(f"/api/v1/anomalies?run_id={run_id}")
    assert listing.status_code == 200
    body = listing.get_json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["cell_id"]
    anomaly_id = body["data"][0]["anomaly_id"]

    extreme = client.get(f"/api/v1/anomalies?run_id={run_id}&severity=extreme")
    assert extreme.get_json()["meta"]["total"] == 1
    moderate = client.get(f"/api/v1/anomalies?run_id={run_id}&severity=moderate")
    assert moderate.get_json()["meta"]["total"] == 0

    detail = client.get(f"/api/v1/anomalies/{anomaly_id}")
    assert detail.status_code == 200
    assert detail.get_json()["data"]["run"]["run_id"] == run_id

    missing = client.get("/api/v1/anomalies/anom_missing")
    assert missing.status_code == 404


def test_anomaly_aggregate_endpoints(client):
    _import_anomaly_fixture(client)
    grid_id = _grid(client)
    run_id = _detect(client, grid_id).get_json()["data"]["run_id"]

    stats = client.get(f"/api/v1/anomalies/statistics?run_id={run_id}").get_json()["data"]
    assert stats["overall"]["anomalies"] == 1
    assert stats["per_sensor"][0]["sensor"] == "modis"
    assert stats["evaluation"]["series_evaluated"] == 1

    severity = client.get(f"/api/v1/anomalies/severity?run_id={run_id}").get_json()["data"]
    assert severity["bands"][0]["severity"] == "extreme"
    assert "extreme" in severity["definitions"]

    regions = client.get(f"/api/v1/anomalies/by-region?run_id={run_id}").get_json()
    assert regions["data"][0]["anomalies"] == 1
    assert regions["meta"]["run_id"] == run_id

    dates = client.get(f"/api/v1/anomalies/by-date?run_id={run_id}").get_json()["data"]
    assert len(dates) == 1
    assert dates[0]["day"].startswith("2012-03-06")

    points = client.get(f"/api/v1/anomalies/map?run_id={run_id}").get_json()["data"]
    assert len(points) == 1
    # Points are grid-cell centres, not raw detection coordinates.
    assert 10.0 <= points[0]["lat"] <= 10.01
    assert 2.0 <= points[0]["lon"] <= 2.01


def test_high_threshold_yields_no_anomalies(client):
    _import_anomaly_fixture(client)
    grid_id = _grid(client)

    data = _detect(client, grid_id, threshold=12).get_json()["data"]

    assert data["stats"]["series_evaluated"] == 1
    assert data["stats"]["anomalies"] == 0


def test_anomalies_require_a_run(client, imported):
    response = client.get("/api/v1/anomalies")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_anomaly_run"


def test_detect_unknown_grid_returns_404(client, imported):
    response = _detect(client, "grid_missing")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "grid_not_found"


def test_short_series_is_skipped(client):
    _import_anomaly_fixture(client)
    grid_id = _grid(client)

    data = _detect(client, grid_id, min_days=7).get_json()["data"]

    assert data["stats"]["series_evaluated"] == 0
    assert data["stats"]["series_skipped_short"] == 1
    assert data["stats"]["anomalies"] == 0
