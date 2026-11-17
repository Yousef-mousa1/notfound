"""Model-estimate hand-off tests.

The series below is synthetic and explicitly labelled as such: it only checks
the mechanics of importing a file with the shape produced by
``modeling/src/harmonize.py``. It is not a scientific dataset.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

RUN_ID = "est_test001"


def _synthetic_series() -> pd.DataFrame:
    """Small synthetic harmonized series in the long shape used by the pipeline."""
    rows = []
    for year, is_estimate in ((2005, True), (2024, False)):
        for month in (1, 2):
            for region, detections in ((11, 40.0), (12, 60.0)):
                rows.append(
                    {
                        "scale": "viirs_harmonized",
                        "region": region,
                        "region_lat": 20.0,
                        "region_lon": 30.0,
                        "region_deg": 10.0,
                        "year": year,
                        "month": month,
                        "detections": detections * (3.5 if is_estimate else 1.0),
                        "viirs_raw_in_table": None if is_estimate else detections,
                        "low": detections * 0.8,
                        "high": detections * 1.2,
                        "cell_days": 31,
                        "is_estimate": is_estimate,
                        "coverage_corrected": True,
                        "scale_factor": 3.5 if is_estimate else 1.4,
                        "baseline": "pooled",
                        "model": "modis_to_viirs_backcast" if is_estimate else "observed",
                    }
                )
    return pd.DataFrame(rows)


def _write_series(tmp_path: Path, fmt: str = "parquet") -> Path:
    path = tmp_path / f"synthetic_harmonized.{fmt}"
    connection = duckdb.connect()
    try:
        connection.register("synthetic_series", _synthetic_series())
        if fmt == "parquet":
            connection.execute(f"COPY synthetic_series TO '{path}' (FORMAT PARQUET)")
        else:
            connection.execute(f"COPY synthetic_series TO '{path}' (FORMAT CSV, HEADER)")
    finally:
        connection.close()
    return path


def _register(client, run_id: str = RUN_ID):
    return client.post(
        "/api/v1/estimates/runs",
        json={
            "run_id": run_id,
            "model_name": "modis_to_viirs_backcast",
            "method": "cell_day_poisson_isotonic",
            "trained_years": [2013, 2024, 2025],
            "test_year": 2024,
            "validation_split": "time_blocks",
            "metrics": {"test": {"count": {"mae": 2.812}}},
            "notes": "synthetic mechanics test",
        },
    )


def _import(client, path: Path, run_id: str = RUN_ID):
    return client.post(
        "/api/v1/estimates/import",
        json={"run_id": run_id, "path": str(path), "level": "region"},
    )


def test_register_and_import_parquet(client, tmp_path: Path):
    assert _register(client).status_code == 201

    response = _import(client, _write_series(tmp_path))

    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    assert data["run_id"] == RUN_ID
    assert data["rows_read"] == 8
    assert data["rows_added"] == 8
    assert data["duplicates_ignored"] == 0
    assert data["rows_in_run"] == 8
    assert data["n_scales"] == 1
    assert data["n_entities"] == 2
    assert data["period_min"].startswith("2005-01")
    assert data["period_max"].startswith("2024-02")


def test_import_is_idempotent_and_keeps_observations_untouched(client, tmp_path: Path):
    _register(client)
    path = _write_series(tmp_path)
    observations_before = client.get("/api/v1/observations?limit=1").get_json()["meta"]["total"]

    first = _import(client, path)
    second = _import(client, path)

    assert first.status_code == second.status_code == 201
    assert second.get_json()["data"]["rows_added"] == 0
    assert second.get_json()["data"]["duplicates_ignored"] == 8
    assert client.get("/api/v1/observations?limit=1").get_json()["meta"]["total"] == observations_before
    assert client.get(f"/api/v1/estimates/runs/{RUN_ID}").get_json()["data"]["n_estimates"] == 8


def test_estimate_filters_and_monthly_series(client, tmp_path: Path):
    _register(client)
    _import(client, _write_series(tmp_path, fmt="csv"))

    backcasts = client.get(f"/api/v1/estimates?run_id={RUN_ID}&from_period=2005-01-01&to_period=2005-12-31")
    assert backcasts.status_code == 200
    assert backcasts.get_json()["meta"]["total"] == 4
    assert all(row["is_estimate"] for row in backcasts.get_json()["data"])

    raw = client.get(f"/api/v1/estimates?run_id={RUN_ID}&scale=modis_raw")
    assert raw.get_json()["meta"]["total"] == 0

    response = client.get(f"/api/v1/dashboard/estimates-calendar?run_id={RUN_ID}")
    assert response.status_code == 200
    series = response.get_json()["data"]["series"]
    assert len(series) == 4
    first = series[0]
    assert first["period"].startswith("2005-01")
    assert first["estimated_value"] > 0
    assert first["observed_value"] == 0.0
    assert first["n_estimate_rows"] == 2
    assert first["n_observed_rows"] == 0


def test_import_errors(client, tmp_path: Path):
    missing_run = _import(client, _write_series(tmp_path), run_id="est_does_not_exist")
    assert missing_run.status_code == 404

    _register(client)
    missing_file = client.post(
        "/api/v1/estimates/import",
        json={"run_id": RUN_ID, "path": str(tmp_path / "nope.parquet")},
    )
    assert missing_file.status_code == 404

    broken = tmp_path / "broken.parquet"
    duckdb.connect().execute(
        f"COPY (SELECT 1 AS year, 1 AS month) TO '{broken}' (FORMAT PARQUET)"
    )
    invalid = _import(client, broken)
    assert invalid.status_code == 422
    assert "missing_columns" in invalid.get_json()["error"]["details"]


def test_import_rejects_path_outside_allowed_roots(client, tmp_path: Path):
    """Absolute and ``../`` paths outside the allowed roots must be refused."""
    _register(client)

    # A valid-looking file one level ABOVE the configured estimates root
    # (tests point estimates at tmp_path) must still be rejected by containment.
    outside = tmp_path.parent / f"outside_estimates_{RUN_ID}.csv"
    outside.write_text("year,month,scale,region,detections\n2024,1,viirs_harmonized,11,1.0\n")
    try:
        absolute = _import(client, outside)
        assert absolute.status_code == 400
        assert absolute.get_json()["error"]["code"] == "path_outside_allowed_root"

        relative = client.post(
            "/api/v1/estimates/import",
            json={"run_id": RUN_ID, "path": "../outside_estimates_escape.csv"},
        )
        assert relative.status_code == 400
        assert relative.get_json()["error"]["code"] == "path_outside_allowed_root"
    finally:
        outside.unlink(missing_ok=True)
