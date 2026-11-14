"""Ingestion endpoint tests."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

MODIS = str(FIXTURES / "modis_head.csv")
VIIRS = str(FIXTURES / "viirs_head.csv")


def test_import_modis_counts_all_rows(client):
    response = client.post("/api/v1/ingestion/sources/import/modis", json={"path": MODIS})

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["rows_read"] == 25
    assert data["rows_loaded"] == 25
    assert data["sensor"] == "modis"
    assert data["invalid_datetime"] == 0


def test_import_viirs_counts_all_rows(client):
    response = client.post("/api/v1/ingestion/sources/import/viirs", json={"path": VIIRS})

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["rows_read"] == 25
    assert data["rows_loaded"] == 25
    assert data["sensor"] == "viirs"


def test_identical_file_is_idempotent(client):
    first = client.post("/api/v1/ingestion/sources/import/modis", json={"path": MODIS})
    second = client.post("/api/v1/ingestion/sources/import/modis", json={"path": MODIS})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["data"]["already_imported"] is True

    listing = client.get("/api/v1/observations?limit=1").get_json()
    assert listing["meta"]["total"] == 25


def test_wrong_sensor_endpoint_is_rejected(client):
    response = client.post("/api/v1/ingestion/sources/import/modis", json={"path": VIIRS})

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert error["code"] == "sensor_mismatch"
    assert error["details"]["detected"] == "viirs"


def test_missing_file_returns_404(client):
    response = client.post(
        "/api/v1/ingestion/sources/import/modis",
        json={"path": "tests/fixtures/does-not-exist.csv"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "file_not_found"


def test_path_outside_project_is_rejected(client):
    response = client.post(
        "/api/v1/ingestion/sources/import/modis", json={"path": "C:/Windows/win.ini"}
    )

    assert response.status_code in {400, 404}
    assert response.get_json()["error"]["code"] in {
        "path_outside_project",
        "file_not_found",
        "unsupported_file_type",
    }


def test_invalid_body_is_rejected(client):
    response = client.post("/api/v1/ingestion/sources/import/modis", json={})

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"


def test_sources_and_imports_listing(client, imported):
    sources = client.get("/api/v1/ingestion/sources").get_json()
    assert sources["meta"]["total"] == 2
    counts = {row["sensor"]: row["observation_count"] for row in sources["data"]}
    assert counts == {"modis": 25, "viirs": 25}

    imports = client.get("/api/v1/ingestion/imports").get_json()
    assert imports["meta"]["total"] == 2
    assert all(row["status"] == "succeeded" for row in imports["data"])

    detail = client.get(f"/api/v1/ingestion/imports/{imports['data'][0]['import_id']}")
    assert detail.status_code == 200
    assert detail.get_json()["data"]["logs"]


def test_upload_registers_and_sync_imports(client):
    with open(FIXTURES / "modis_head.csv", "rb") as handle:
        response = client.post(
            "/api/v1/ingestion/files/upload",
            data={"file": (handle, "modis_upload.csv")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 201
    source = response.get_json()["data"]["source"]
    assert source["sensor"] == "modis"
    assert source["status"] == "uploaded"

    synced = client.post("/api/v1/ingestion/sync", json={})
    assert synced.status_code == 200
    body = synced.get_json()["data"]
    assert body["sources_checked"] == 1
    assert body["succeeded"] == 1

    observations = client.get("/api/v1/observations?limit=1").get_json()
    assert observations["meta"]["total"] == 25

    # Sync again: nothing left to import.
    again = client.post("/api/v1/ingestion/sync", json={}).get_json()["data"]
    assert again["sources_checked"] == 0


def test_upload_rejects_unknown_schema(client, tmp_path: Path):
    bad = tmp_path / "not_fire.csv"
    bad.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

    with bad.open("rb") as handle:
        response = client.post(
            "/api/v1/ingestion/files/upload",
            data={"file": (handle, "not_fire.csv")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unsupported_schema"
