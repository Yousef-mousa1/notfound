"""Map point-inspection endpoint tests.

Fixtures are the real observations imported by the shared ``client`` fixture;
this module only checks that the endpoint reports them honestly alongside the
stored estimate block, and that invalid input is rejected.
"""

from __future__ import annotations


def test_inspect_point_returns_detections_and_estimate(client):
    response = client.get("/api/v1/dashboard/inspect?lat=9.5&lon=2.5&radius_km=50")
    assert response.status_code == 200, response.get_json()
    data = response.get_json()["data"]

    assert data["point"]["radius_km"] == 50.0
    assert "detections" in data and "estimate" in data
    detections = data["detections"]
    assert detections["count"] >= 0
    assert isinstance(detections["sample"], list)
    assert detections["sensors"] == {} or all(
        isinstance(v, int) for v in detections["sensors"].values()
    )
    assert "no record is NOT proof of no fire" in " ".join(data["notes"])


def test_inspect_point_estimate_shape_when_loaded(client):
    # Benin sample spans roughly lat 6-12, lon 0.7-3.9.
    data = client.get(
        "/api/v1/dashboard/inspect?lat=9.0&lon=2.0&radius_km=10"
    ).get_json()["data"]
    estimate = data["estimate"]
    assert estimate is None or "entity_id" in estimate
    if estimate and estimate.get("available"):
        assert "scales" in estimate


def test_inspect_point_validates_input(client):
    assert client.get("/api/v1/dashboard/inspect?lat=91&lon=0").status_code == 422
    assert client.get("/api/v1/dashboard/inspect?lat=0&lon=181").status_code == 422
    assert client.get("/api/v1/dashboard/inspect?lat=0&lon=0&radius_km=0").status_code == 422
