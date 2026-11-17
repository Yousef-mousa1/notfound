"""Validation endpoint tests (cross-sensor consistency on matched pairs)."""

from __future__ import annotations

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


def _run_validation(client, **overrides) -> str:
    body = {"radius_m": 2000, "time_window_h": 2}
    body.update(overrides)
    response = client.post("/api/v1/validation/run", json=body)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]["run_id"]


def test_validation_run_reports_pairs_and_limitations(client):
    _import_calibration_pair(client)

    response = client.post(
        "/api/v1/validation/run", json={"radius_m": 2000, "time_window_h": 2}
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["run_id"].startswith("val_")
    assert data["n_pairs"] == 12
    assert data["metrics"]["n_pairs"] == 12
    assert data["metrics"]["n_positive_pairs"] == 12
    assert data["metrics"]["log10_frp"]["mae"] is not None
    assert data["matching"]["criterion"].startswith("geodesic distance")
    assert any("not accuracy" in note for note in data["metrics"]["limitations"])


def test_metric_endpoints_are_consistency_not_accuracy(client):
    _import_calibration_pair(client)
    run_id = _run_validation(client)

    for path in ("mae", "rmse", "bias", "correlation"):
        response = client.get(f"/api/v1/validation/metrics/{path}?run_id={run_id}")
        assert response.status_code == 200, (path, response.get_json())
        body = response.get_json()["data"]
        assert body["n_pairs"] == 12
        assert body["run_id"] == run_id
        assert "not accuracy against true fire occurrence" in body["limitations"][0]
        assert body["metric"] == path

    bias = client.get(f"/api/v1/validation/metrics/bias?run_id={run_id}").get_json()["data"]
    # Synthetic data: MODIS = 5 * VIIRS - 10, so MODIS is higher on every pair.
    assert bias["raw_mw"] > 0
    assert bias["log10_frp"] > 0


def test_distribution_temporal_and_spatial(client):
    _import_calibration_pair(client)
    run_id = _run_validation(client)

    distribution = client.get(f"/api/v1/validation/distribution?run_id={run_id}")
    assert distribution.status_code == 200
    body = distribution.get_json()["data"]
    assert body["modis_mw"]["p50"] is not None
    assert body["ks_statistic"]["raw_mw"] is not None

    temporal = client.get(f"/api/v1/validation/temporal?run_id={run_id}")
    assert temporal.status_code == 200
    buckets = temporal.get_json()["data"]["buckets"]
    assert buckets
    assert sum(item["n_pairs"] for item in buckets) == 12

    spatial = client.get(f"/api/v1/validation/spatial?run_id={run_id}")
    assert spatial.status_code == 200
    buckets = spatial.get_json()["data"]["buckets"]
    assert buckets
    assert sum(item["n_pairs"] for item in buckets) == 12


def test_metrics_default_to_latest_successful_run(client):
    _import_calibration_pair(client)
    run_id = _run_validation(client)

    response = client.get("/api/v1/validation/metrics/mae")
    assert response.status_code == 200
    assert response.get_json()["data"]["run_id"] == run_id

    listing = client.get("/api/v1/validation/results").get_json()
    assert listing["meta"]["total"] == 1
    assert listing["data"][0]["run_id"] == run_id


def test_unknown_run_returns_404(client, imported):
    response = client.get("/api/v1/validation/metrics/mae?run_id=val_missing")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "validation_run_not_found"


def test_no_run_returns_409(client, imported):
    response = client.get("/api/v1/validation/metrics/rmse")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_validation_run"


def test_validation_without_pairs_returns_409(client):
    _import_calibration_pair(client)

    response = client.post(
        "/api/v1/validation/run", json={"radius_m": 1, "time_window_h": 2}
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_pairs"
