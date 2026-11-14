"""Analytics and dashboard endpoint tests (sensor-separated outputs)."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _harmonization_setup(client) -> str:
    for sensor, name in (
        ("modis", "synthetic_modis_calibration.csv"),
        ("viirs", "synthetic_viirs_calibration.csv"),
    ):
        response = client.post(
            f"/api/v1/ingestion/sources/import/{sensor}",
            json={"path": str(FIXTURES / name)},
        )
        assert response.status_code == 201, response.get_json()

    grid_id = client.post(
        "/api/v1/processing/grid/generate", json={"cell_km": 100}
    ).get_json()["data"]["grid_id"]
    response = client.post(
        "/api/v1/harmonization/run",
        json={"grid_id": grid_id, "time_bucket": "day", "method": "none"},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]["run_id"]


def test_analytics_overview(client, imported):
    response = client.get("/api/v1/analytics/overview")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["observations"]["detections"] == 50
    assert {row["sensor"] for row in data["per_sensor"]} == {"modis", "viirs"}
    assert "anomaly_run_id" in data["available_outputs"]
    assert "land-cover" in data["available_outputs"]["land_cover"]


def test_hotspot_and_frp_trends(client, imported):
    monthly = client.get("/api/v1/analytics/hotspot-trends?granularity=month")
    assert monthly.status_code == 200
    body = monthly.get_json()
    assert body["meta"]["granularity"] == "month"
    assert body["data"]["series"]
    assert {row["sensor"] for row in body["data"]["series"]} == {"modis", "viirs"}

    frp = client.get("/api/v1/analytics/frp-trends?granularity=day").get_json()
    assert "median_frp_mw" in frp["data"]["series"][0]
    assert any("energy" in note for note in frp["data"]["notes"])


def test_yearly_makes_no_trend_claim(client, imported):
    response = client.get("/api/v1/analytics/yearly")

    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["trend_claim"] is False
    assert body["meta"]["trend_claim"] is False
    assert body["data"]["granularity"] == "year"


def test_activity_trends_require_a_harmonization_run(client, imported):
    response = client.get("/api/v1/analytics/activity-trends")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_harmonization_run"


def test_activity_trends_follow_explicit_run(client):
    run_id = _harmonization_setup(client)

    response = client.get(f"/api/v1/analytics/activity-trends?run_id={run_id}")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["run_id"] == run_id
    assert data["time_bucket"] == "day"
    assert data["series"]
    assert data["series"][0]["cells"] >= 1


def test_regions_are_data_extent_boxes(client, imported):
    response = client.get("/api/v1/analytics/regions")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body["data"]) == 4
    assert body["meta"]["grid"] == 2
    assert "not administrative" in body["meta"]["region_basis"]


def test_land_cover_returns_501(client, imported):
    response = client.get("/api/v1/analytics/land-cover")

    assert response.status_code == 501
    error = response.get_json()["error"]
    assert error["code"] == "not_implemented"
    assert "land-cover" in error["details"]["reason"]


def test_analytics_sensor_comparison(client, imported):
    response = client.get("/api/v1/analytics/sensor-comparison")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert {row["sensor"] for row in data["sensors"]} == {"modis", "viirs"}
    assert data["agreement"] is None
    assert any("never merged" in note for note in data["notes"])


def test_dashboard_overview_and_optional_panels(client, imported):
    overview = client.get("/api/v1/dashboard/overview").get_json()["data"]
    assert overview["observations"]["detections"] == 50
    assert overview["anomalies"]["available"] is False
    assert overview["harmonization"]["available"] is False
    assert overview["validation"]["available"] is False

    anomalies = client.get("/api/v1/dashboard/anomalies").get_json()["data"]
    assert anomalies["available"] is False

    missing = client.get("/api/v1/dashboard/activity-index")
    assert missing.status_code == 409
    assert missing.get_json()["error"]["code"] == "no_harmonization_run"


def test_dashboard_map_calendar_and_trends(client, imported):
    map_body = client.get("/api/v1/dashboard/map?limit=5").get_json()
    assert map_body["data"]["observations"]
    assert map_body["data"]["anomalies"] == []
    assert map_body["meta"]["limit"] == 5

    calendar = client.get("/api/v1/dashboard/calendar").get_json()["data"]
    assert calendar["series"]
    assert {row["sensor"] for row in calendar["series"]} == {"modis", "viirs"}

    trends = client.get("/api/v1/dashboard/trends").get_json()["data"]
    assert trends["daily"]
    assert trends["monthly"]


def test_dashboard_activity_index_after_run(client):
    run_id = _harmonization_setup(client)

    response = client.get("/api/v1/dashboard/activity-index?limit=5")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["run_id"] == run_id
    assert data["summary"]["rows"] >= 1
    assert len(data["cells"]) <= 5
    assert data["cells"][0]["harmonized_activity_index"] is not None
