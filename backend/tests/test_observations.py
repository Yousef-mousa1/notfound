"""Observation endpoint tests."""

from __future__ import annotations


def test_list_is_paginated(client, imported):
    first = client.get("/api/v1/observations?limit=10").get_json()
    assert first["meta"]["total"] == 50
    assert first["meta"]["returned"] == 10
    assert len(first["data"]) == 10

    second = client.get("/api/v1/observations?limit=10&offset=10").get_json()
    assert {row["observation_id"] for row in first["data"]}.isdisjoint(
        {row["observation_id"] for row in second["data"]}
    )


def test_sensor_filter_and_convenience_routes(client, imported):
    modis = client.get("/api/v1/observations/modis?limit=50").get_json()
    assert modis["meta"]["total"] == 25
    assert all(row["sensor"] == "modis" for row in modis["data"])

    viirs = client.get("/api/v1/observations/viirs?limit=50").get_json()
    assert viirs["meta"]["total"] == 25
    assert all(row["sensor"] == "viirs" for row in viirs["data"])


def test_observation_detail_keeps_original_row(client, imported):
    listing = client.get("/api/v1/observations?limit=1").get_json()
    observation_id = listing["data"][0]["observation_id"]

    detail = client.get(f"/api/v1/observations/{observation_id}")
    assert detail.status_code == 200
    data = detail.get_json()["data"]
    assert data["raw_json"]
    assert data["observation_id"] == observation_id


def test_unknown_observation_returns_404(client, imported):
    response = client.get("/api/v1/observations/does-not-exist")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "observation_not_found"


def test_statistics_are_per_sensor(client, imported):
    payload = client.get("/api/v1/observations/statistics").get_json()["data"]

    overall = payload["overall"]
    assert overall["detections"] == 50
    assert overall["sensors"] == 2
    assert overall["median_frp_mw"] is not None
    assert {row["sensor"] for row in payload["per_sensor"]} == {"modis", "viirs"}
    assert "never summed" in payload["notes"]["frp"]


def test_by_date_and_by_sensor(client, imported):
    by_date = client.get("/api/v1/observations/by-date?granularity=day").get_json()
    assert by_date["meta"]["granularity"] == "day"
    assert sum(row["detections"] for row in by_date["data"]) == 50

    by_sensor = client.get("/api/v1/observations/by-sensor").get_json()
    assert sum(row["detections"] for row in by_sensor["data"]) == 50


def test_map_and_regions_cover_all_rows(client, imported):
    points = client.get("/api/v1/observations/map?limit=1000").get_json()
    assert points["meta"]["returned"] == 50

    regions = client.get("/api/v1/observations/by-region").get_json()
    assert regions["meta"]["grid"] == 2
    assert sum(region["detections"] for region in regions["data"]) == 50
    assert {region["region"] for region in regions["data"]} == {
        "R1C1",
        "R1C2",
        "R2C1",
        "R2C2",
    }


def test_bbox_filter(client, imported):
    response = client.get(
        "/api/v1/observations?bbox=0.7,6.2,3.9,12.4&limit=1000"
    ).get_json()
    assert response["meta"]["total"] == 50

    outside = client.get("/api/v1/observations?bbox=0,0,1,1&limit=1000").get_json()
    assert outside["meta"]["total"] == 0


def test_validation_errors_are_structured(client, imported):
    bad_sort = client.get("/api/v1/observations?sort=raw_json")
    assert bad_sort.status_code == 422
    assert bad_sort.get_json()["error"]["code"] == "validation_error"

    bad_bbox = client.get("/api/v1/observations?bbox=1,2,3")
    assert bad_bbox.status_code == 422

    reversed_range = client.get(
        "/api/v1/observations?start=2012-12-31&end=2012-01-01"
    )
    assert reversed_range.status_code == 422


def test_date_boundary_is_inclusive(client, imported):
    response = client.get(
        "/api/v1/observations?start=2012-01-01&end=2012-12-31&limit=1000"
    ).get_json()
    assert response["meta"]["total"] == 50
