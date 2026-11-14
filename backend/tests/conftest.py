"""Shared pytest fixtures.

Tests use small fixtures cut from the real sample files (never invented data)
and a temporary DuckDB database per test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture()
def app(tmp_path: Path):
    config = {
        "project": {"name": "test", "team": "test", "event": "test"},
        "paths": {
            "raw": str(FIXTURES),
            "interim": str(tmp_path / "interim"),
            "processed": str(tmp_path / "processed"),
            "runs": str(tmp_path / "runs"),
            "uploads": str(tmp_path / "uploads"),
            "exports": str(tmp_path / "exports"),
        },
        "storage": {"duckdb_path": str(tmp_path / "test.duckdb")},
        "api": {"prefix": "/api/v1", "default_limit": 100, "max_limit": 1000},
        "ingestion": {
            "allowed_extensions": [".csv"],
            "platform_mapping": {"Terra": "Terra", "Aqua": "Aqua", "N": "S-NPP"},
        },
        "spatial": {"grid_km": None, "storage_crs": "EPSG:4326", "region_grid": 2},
        "exports": {"max_rows": 500000},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    application = create_app(config_path)
    application.config["TESTING"] = True
    yield application

    application.extensions["job_runner"].stop()
    application.extensions["db"].close()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def imported(client):
    """Import the MODIS and VIIRS fixtures and return their payloads."""
    modis = client.post(
        "/api/v1/ingestion/sources/import/modis",
        json={"path": str(FIXTURES / "modis_head.csv")},
    )
    viirs = client.post(
        "/api/v1/ingestion/sources/import/viirs",
        json={"path": str(FIXTURES / "viirs_head.csv")},
    )
    assert modis.status_code == 201, modis.get_json()
    assert viirs.status_code == 201, viirs.get_json()
    return {"modis": modis.get_json()["data"], "viirs": viirs.get_json()["data"]}
