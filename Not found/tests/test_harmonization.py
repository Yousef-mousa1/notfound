"""Harmonization endpoint tests.

The ``synthetic_*_calibration.csv`` fixtures are synthetic (clearly labelled):
12 MODIS/VIIRS rows with an exact linear relation (MODIS = 5 * VIIRS - 10),
used to check calibration mechanics, not to claim anything about real fires.
"""

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


def _grid_id(client, cell_km: int = 100) -> str:
    response = client.post(
        "/api/v1/processing/grid/generate", json={"cell_km": cell_km}
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]["grid_id"]


def test_methods_list_marks_random_forest_unimplemented(client):
    response = client.get("/api/v1/harmonization/methods")

    assert response.status_code == 200
    methods = {item["method"]: item for item in response.get_json()["data"]}
    assert set(methods) == {
        "none",
        "ratio",
        "linear-regression",
        "quantile-mapping",
        "random-forest",
    }
    assert methods["random-forest"]["implemented"] is False
    assert methods["ratio"]["implemented"] is True


def test_ratio_calibration_fits_on_pairs_and_is_persisted(client):
    _import_calibration_pair(client)

    response = client.post(
        "/api/v1/harmonization/calibrate/ratio",
        json={"radius_m": 2000, "time_window_h": 1},
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["run_id"].startswith("harm_")
    assert data["calibration"]["n_pairs"] == 12
    factor = data["calibration"]["spec"]["factor"]
    assert 4.0 <= factor <= 5.0
    assert data["calibration"]["rmse_mw"] is not None
    assert any("not ground truth" in note for note in data["limitations"])

    stored = client.get(f"/api/v1/harmonization/results?run_id={data['run_id']}")
    assert stored.status_code == 200
    assert stored.get_json()["data"]["status"] == "calibrated"


def test_linear_regression_recovers_exact_relation(client):
    _import_calibration_pair(client)

    response = client.post(
        "/api/v1/harmonization/calibrate/linear-regression",
        json={"radius_m": 2000, "time_window_h": 1},
    )

    assert response.status_code == 201
    spec = response.get_json()["data"]["calibration"]["spec"]
    assert abs(spec["slope"] - 5.0) < 0.01
    assert abs(spec["intercept"] + 10.0) < 0.01


def test_quantile_mapping_returns_monotonic_table(client):
    _import_calibration_pair(client)

    response = client.post(
        "/api/v1/harmonization/calibrate/quantile-mapping",
        json={"radius_m": 2000, "time_window_h": 1},
    )

    assert response.status_code == 201
    calibration = response.get_json()["data"]["calibration"]
    assert calibration["n_pairs"] == 12
    source = calibration["spec"]["source_quantiles"]
    target = calibration["spec"]["target_quantiles"]
    assert len(source) == len(target) == calibration["spec"]["points"]
    assert all(b >= a for a, b in zip(source, source[1:], strict=False))
    assert all(b >= a for a, b in zip(target, target[1:], strict=False))


def test_random_forest_returns_501_with_reason(client):
    response = client.post("/api/v1/harmonization/calibrate/random-forest", json={})

    assert response.status_code == 501
    error = response.get_json()["error"]
    assert error["code"] == "not_implemented"
    assert "ground truth" in error["details"]["reason"]


def test_calibration_without_pairs_returns_409(client):
    _import_calibration_pair(client)

    response = client.post(
        "/api/v1/harmonization/calibrate/ratio",
        json={"radius_m": 1, "time_window_h": 1},
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_pairs"


def test_run_writes_bounded_per_cell_results(client):
    _import_calibration_pair(client)
    grid_id = _grid_id(client)

    response = client.post(
        "/api/v1/harmonization/run",
        json={
            "grid_id": grid_id,
            "time_bucket": "none",
            "method": "ratio",
            "radius_m": 2000,
            "time_window_h": 1,
        },
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["run_id"].startswith("harm_")
    assert data["n_pairs"] == 12
    assert data["n_cells"] >= 1
    assert data["calibration"]["method"] == "ratio"
    assert data["index_definition"]["scale_quantile"] == 0.95
    assert 0.0 <= data["index_stats"]["max"] <= 1.0
    for row in data["sample"]:
        assert 0.0 <= row["harmonized_activity_index"] <= 1.0
        assert row["sensors_present"] in {1, 2}

    detail = client.get(f"/api/v1/harmonization/results/{data['run_id']}?limit=1000")
    assert detail.status_code == 200
    payload = detail.get_json()
    assert payload["data"]["run"]["status"] == "succeeded"
    assert len(payload["data"]["results"]) == data["n_cells"]
    assert payload["meta"]["total"] == data["n_cells"]


def test_run_without_calibration_needs_no_radius(client):
    _import_calibration_pair(client)
    grid_id = _grid_id(client)

    response = client.post(
        "/api/v1/harmonization/run",
        json={"grid_id": grid_id, "time_bucket": "day", "method": "none"},
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["method"] == "none"
    assert data["n_pairs"] == 0
    assert data["calibration"]["method"] == "none"
    assert data["n_cells"] >= 1


def test_run_requires_radius_when_calibrating(client):
    _import_calibration_pair(client)
    grid_id = _grid_id(client)

    response = client.post(
        "/api/v1/harmonization/run",
        json={"grid_id": grid_id, "method": "ratio"},
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"


def test_run_unknown_grid_returns_404(client):
    _import_calibration_pair(client)

    response = client.post(
        "/api/v1/harmonization/run",
        json={"grid_id": "grid_missing", "method": "none"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "grid_not_found"


def test_comparison_uncertainty_and_activity_index(client):
    _import_calibration_pair(client)
    grid_id = _grid_id(client)
    run_id = client.post(
        "/api/v1/harmonization/run",
        json={
            "grid_id": grid_id,
            "time_bucket": "none",
            "method": "linear-regression",
            "radius_m": 2000,
            "time_window_h": 1,
        },
    ).get_json()["data"]["run_id"]

    comparison = client.get(f"/api/v1/harmonization/comparison?run_id={run_id}")
    assert comparison.status_code == 200
    summary = comparison.get_json()["data"]["summary"]
    assert summary["rows"] >= 1
    assert summary["cells_with_both_sensors"] + summary["cells_with_one_sensor"] == summary["rows"]

    uncertainty = client.get(f"/api/v1/harmonization/uncertainty?run_id={run_id}")
    assert uncertainty.status_code == 200
    payload = uncertainty.get_json()["data"]
    assert payload["calibration_n_pairs"] == 12
    assert payload["coverage"]

    index = client.get(f"/api/v1/harmonization/activity-index?run_id={run_id}&limit=5")
    assert index.status_code == 200
    body = index.get_json()
    assert "formula" in body["data"]
    assert body["data"]["scales"]["modis_mean_frp_mw"] is not None
    indices = [row["harmonized_activity_index"] for row in body["data"]["results"]]
    assert indices == sorted(indices, reverse=True)


def test_results_list_and_latest_defaults(client):
    _import_calibration_pair(client)
    grid_id = _grid_id(client)
    run_id = client.post(
        "/api/v1/harmonization/run",
        json={"grid_id": grid_id, "time_bucket": "none", "method": "none"},
    ).get_json()["data"]["run_id"]

    listing = client.get("/api/v1/harmonization/results").get_json()
    assert listing["meta"]["total"] == 1
    assert listing["data"][0]["run_id"] == run_id

    index = client.get("/api/v1/harmonization/activity-index")
    assert index.status_code == 200
    assert index.get_json()["data"]["run_id"] == run_id


def test_activity_index_without_runs_returns_409(client, imported):
    response = client.get("/api/v1/harmonization/activity-index")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_harmonization_run"


def test_cells_endpoint_returns_cell_centres_for_the_map(client):
    _import_calibration_pair(client)
    grid_id = _grid_id(client)
    run = client.post(
        "/api/v1/harmonization/run",
        json={
            "grid_id": grid_id,
            "time_bucket": "none",
            "method": "ratio",
            "radius_m": 2000,
            "time_window_h": 1,
        },
    ).get_json()["data"]

    response = client.get("/api/v1/harmonization/cells?limit=1000")
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    data = payload["data"]
    assert data["run_id"] == run["run_id"]
    assert data["grid_id"] == grid_id
    assert data["total"] == run["n_cells"]
    assert data["returned"] == len(data["cells"])
    assert payload["meta"]["total"] == run["n_cells"]
    for cell in data["cells"]:
        assert isinstance(cell["center_lat"], float)
        assert isinstance(cell["center_lon"], float)
        assert cell["sensors_present"] in {1, 2}
        assert cell["day"]

    both = client.get("/api/v1/harmonization/cells?both_only=true&limit=1000")
    assert both.status_code == 200
    both_cells = both.get_json()["data"]["cells"]
    assert all(cell["sensors_present"] == 2 for cell in both_cells)
