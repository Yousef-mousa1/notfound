"""End-to-end demo runner tests.

The runner must build the same state through the public API, reuse a grid on a
second run, and produce byte-identical data files for identical inputs
(reproducibility), without changing the stored observations.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.demo_run import DemoError, run_demo

FIXTURES = Path(__file__).parent / "fixtures"
CALIBRATION_FILES = [
    FIXTURES / "synthetic_modis_calibration.csv",
    FIXTURES / "synthetic_viirs_calibration.csv",
]


def _config(tmp_path: Path, raw_dir: Path) -> Path:
    config = {
        "project": {"name": "test", "team": "test", "event": "test"},
        "paths": {
            "raw": str(raw_dir),
            "interim": str(tmp_path / "interim"),
            "processed": str(tmp_path / "processed"),
            "runs": str(tmp_path / "runs"),
            "uploads": str(tmp_path / "uploads"),
            "exports": str(tmp_path / "exports"),
        },
        "storage": {"duckdb_path": str(tmp_path / "demo.duckdb")},
        "api": {"prefix": "/api/v1", "default_limit": 100, "max_limit": 1000},
        "ingestion": {
            "allowed_extensions": [".csv"],
            "platform_mapping": {"Terra": "Terra", "Aqua": "Aqua", "N": "S-NPP"},
        },
        "exports": {"max_rows": 500000},
    }
    path = tmp_path / "demo.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def _run(config_path: Path, **overrides):
    options = {
        "grid_km": 100,
        "radius_m": 2000,
        "time_window_h": 2,
        "files": CALIBRATION_FILES,
    }
    options.update(overrides)
    return run_demo(config_path, **options)


def test_demo_run_builds_the_full_state(tmp_path):
    config_path = _config(tmp_path, FIXTURES)

    manifest = _run(config_path)

    ids = manifest["ids"]
    assert ids["grid_id"].startswith("grid_")
    assert ids["harmonization_run_id"].startswith("harm_")
    assert ids["validation_run_id"].startswith("val_")
    assert ids["anomaly_run_id"].startswith("anom_")
    assert len(ids["export_ids"]) == 3

    steps = {item["step"]: item for item in manifest["steps"]}
    assert steps["ingest"]["files"][0]["rows_loaded"] == 12
    assert steps["ingest"]["files"][0]["status"] == "imported"
    assert steps["observations"]["detections"] == 24
    assert steps["grid"]["reused"] is False
    assert steps["harmonize"]["n_pairs"] == 12
    assert steps["validate"]["n_pairs"] == 12
    assert steps["anomalies"]["series_total"] >= 1

    export_dir = tmp_path / "exports"
    for export in steps["export"]["exports"]:
        assert export["row_count"] > 0
        assert (export_dir / export["export_id"] / "metadata.json").is_file()

    manifest_file = Path(manifest["manifest_path"])
    assert manifest_file.is_file()
    written = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
    assert written["ids"]["harmonization_run_id"] == ids["harmonization_run_id"]
    assert written["limitations"]


def test_second_run_reuses_grid_and_reproduces_files(tmp_path):
    config_path = _config(tmp_path, FIXTURES)

    first = _run(config_path)
    second = _run(config_path)

    first_steps = {item["step"]: item for item in first["steps"]}
    second_steps = {item["step"]: item for item in second["steps"]}

    assert second_steps["grid"]["reused"] is True
    assert second["ids"]["grid_id"] == first["ids"]["grid_id"]

    # Observations are imported once (idempotent), never duplicated.
    assert second_steps["observations"]["detections"] == 24
    assert second_steps["ingest"]["files"][0]["status"] == "already imported"

    # Identical inputs and config must produce a byte-identical observation CSV.
    first_csv = first_steps["export"]["exports"][0]["files"][0]
    second_csv = second_steps["export"]["exports"][0]["files"][0]
    assert first_csv["name"] == second_csv["name"] == "observations.csv"
    assert first_csv["sha256"] == second_csv["sha256"]

    # The metadata sidecar changes (new ids/timestamps) and must be a distinct file.
    first_meta = next(
        item for item in first_steps["export"]["exports"][0]["files"] if item["name"] == "metadata.json"
    )
    second_meta = next(
        item for item in second_steps["export"]["exports"][0]["files"] if item["name"] == "metadata.json"
    )
    assert first_meta["sha256"] != second_meta["sha256"]


def test_demo_run_fails_clearly_without_input_files(tmp_path):
    empty_raw = tmp_path / "empty_raw"
    empty_raw.mkdir()
    config_path = _config(tmp_path, empty_raw)

    with pytest.raises(DemoError, match="No detection CSV found"):
        _run(config_path, files=None)
