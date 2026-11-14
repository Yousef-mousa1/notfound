"""Unit tests for matching and grid science helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from harmonizer.matching import haversine_m, spatial_links, temporal_links
from harmonizer.spatial import build_grid


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_haversine_one_degree_of_latitude():
    distance = haversine_m(0.0, 0.0, 1.0, 0.0)

    assert 110_000 < float(distance) < 112_500


def test_haversine_is_zero_for_same_point():
    assert float(haversine_m(10.0, 2.0, 10.0, 2.0)) == pytest.approx(0.0, abs=1e-6)


def test_spatial_links_respect_radius_and_time():
    frame = _frame(
        [
            {"observation_id": "m1", "sensor": "modis", "lat": 10.0, "lon": 2.0,
             "datetime_utc": pd.Timestamp("2012-03-01 10:00"), "frp_mw": 50.0},
            {"observation_id": "m2", "sensor": "modis", "lat": 20.0, "lon": 5.0,
             "datetime_utc": pd.Timestamp("2012-03-01 10:00"), "frp_mw": 60.0},
            {"observation_id": "v1", "sensor": "viirs", "lat": 10.01, "lon": 2.01,
             "datetime_utc": pd.Timestamp("2012-03-01 10:30"), "frp_mw": 5.0},
            {"observation_id": "v2", "sensor": "viirs", "lat": 10.5, "lon": 2.5,
             "datetime_utc": pd.Timestamp("2012-03-01 10:30"), "frp_mw": 6.0},
        ]
    )

    links, notes = spatial_links(frame, radius_m=2000, time_window_h=1, max_pairs_per_detection=10, max_links=100)

    assert notes["pairs"] == 1
    assert links.iloc[0]["observation_a"] == "m1"
    assert links.iloc[0]["observation_b"] == "v1"
    assert float(links.iloc[0]["distance_m"]) <= 2000


def test_spatial_links_cap_pairs_per_detection():
    rows = [
        {"observation_id": "m1", "sensor": "modis", "lat": 10.0, "lon": 2.0,
         "datetime_utc": pd.Timestamp("2012-03-01 10:00"), "frp_mw": 50.0}
    ]
    for index in range(20):
        rows.append(
            {"observation_id": f"v{index}", "sensor": "viirs", "lat": 10.0 + index * 0.0001,
             "lon": 2.0, "datetime_utc": pd.Timestamp("2012-03-01 10:05"), "frp_mw": 5.0}
        )

    links, _ = spatial_links(_frame(rows), radius_m=2000, time_window_h=None, max_pairs_per_detection=5, max_links=100)

    assert len(links) == 5


def test_temporal_links_ignore_distance_but_report_it():
    frame = _frame(
        [
            {"observation_id": "m1", "sensor": "modis", "lat": 10.0, "lon": 2.0,
             "datetime_utc": pd.Timestamp("2012-03-01 10:00"), "frp_mw": 50.0},
            {"observation_id": "v1", "sensor": "viirs", "lat": 30.0, "lon": 20.0,
             "datetime_utc": pd.Timestamp("2012-03-01 10:10"), "frp_mw": 5.0},
        ]
    )

    links, notes = temporal_links(frame, time_window_h=1, max_pairs_per_detection=5, max_links=100)

    assert notes["pairs"] == 1
    assert float(links.iloc[0]["distance_m"]) > 1_000_000
    assert float(links.iloc[0]["delta_t_s"]) == pytest.approx(600.0)


def test_temporal_links_respect_window():
    frame = _frame(
        [
            {"observation_id": "m1", "sensor": "modis", "lat": 10.0, "lon": 2.0,
             "datetime_utc": pd.Timestamp("2012-03-01 10:00"), "frp_mw": 50.0},
            {"observation_id": "v1", "sensor": "viirs", "lat": 10.0, "lon": 2.0,
             "datetime_utc": pd.Timestamp("2012-03-01 14:00"), "frp_mw": 5.0},
        ]
    )

    links, notes = temporal_links(frame, time_window_h=1, max_pairs_per_detection=5, max_links=100)

    assert notes["pairs"] == 0
    assert links.empty


def test_grid_geometry_and_distortion():
    spec, cells = build_grid(6.35, 7.85, 1.0, 2.0, cell_km=100)

    assert spec.n_rows == 2
    assert spec.n_cols == 2
    assert len(cells) == spec.cell_count
    assert spec.area_distortion_pct >= 0
    assert cells["min_lat"].min() == pytest.approx(6.35)
    assert cells["max_lon"].max() == pytest.approx(2.0)


def test_grid_rejects_bad_input():
    with pytest.raises(ValueError):
        build_grid(10, 9, 1, 2, cell_km=10)
    with pytest.raises(ValueError):
        build_grid(9, 10, 1, 2, cell_km=0)

def test_ratio_fit_uses_median_ratio():
    from harmonizer.harmonization import fit_ratio

    modis = [40.0, 45.0, 50.0]
    viirs = [10.0, 11.0, 10.0]
    result = fit_ratio(modis, viirs)

    assert result.n_pairs == 3
    assert result.spec["factor"] == pytest.approx(45.0 / 11.0)
    assert result.rmse_mw is not None


def test_linear_fit_recovers_exact_relation():
    from harmonizer.harmonization import apply_calibration, fit_linear

    modis = [40.0, 45.0, 50.0, 55.0]
    viirs = [10.0, 11.0, 12.0, 13.0]
    result = fit_linear(modis, viirs)

    assert result.spec["slope"] == pytest.approx(5.0)
    assert result.spec["intercept"] == pytest.approx(-10.0)
    assert apply_calibration(result, [14.0])[0] == pytest.approx(60.0)


def test_quantile_mapping_requires_enough_pairs():
    from harmonizer.harmonization import fit_quantile

    with pytest.raises(ValueError):
        fit_quantile([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])


def test_activity_index_is_bounded_and_keeps_sensors_visible():
    from harmonizer.harmonization import fit_none, harmonize_cells

    aggregates = pd.DataFrame(
        [
            {"cell_id": "a", "time_bucket": "all", "sensor": "modis", "detections": 10, "mean_frp_mw": 50.0},
            {"cell_id": "a", "time_bucket": "all", "sensor": "viirs", "detections": 40, "mean_frp_mw": 5.0},
            {"cell_id": "b", "time_bucket": "all", "sensor": "modis", "detections": 2, "mean_frp_mw": 10.0},
        ]
    )

    results, meta = harmonize_cells(aggregates, fit_none())

    assert set(results["cell_id"]) == {"a", "b"}
    assert results["harmonized_activity_index"].between(0.0, 1.0).all()
    cell_a = results[results["cell_id"] == "a"].iloc[0]
    assert cell_a["sensors_present"] == 2
    assert cell_a["uncertainty_mw"] == pytest.approx(45.0)
    cell_b = results[results["cell_id"] == "b"].iloc[0]
    assert cell_b["sensors_present"] == 1
    assert pd.isna(cell_b["uncertainty_mw"])
    assert meta["scale_quantile"] == 0.95
    assert any("absence" in note or "no row" in note for note in meta["limitations"])
