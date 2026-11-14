"""Job endpoint tests."""

from __future__ import annotations


def test_jobs_are_created_by_imports(client, imported):
    jobs = client.get("/api/v1/jobs").get_json()

    assert jobs["meta"]["total"] == 2
    assert {row["kind"] for row in jobs["data"]} == {
        "ingestion.import.modis",
        "ingestion.import.viirs",
    }
    assert all(row["status"] == "succeeded" for row in jobs["data"])


def test_job_detail_status_and_logs(client, imported):
    job = client.get("/api/v1/jobs").get_json()["data"][0]
    job_id = job["job_id"]

    detail = client.get(f"/api/v1/jobs/{job_id}").get_json()["data"]
    assert detail["result"]["rows_loaded"] == 25

    status = client.get(f"/api/v1/jobs/{job_id}/status").get_json()["data"]
    assert status["status"] == "succeeded"
    assert status["finished_at"]

    logs = client.get(f"/api/v1/jobs/{job_id}/logs").get_json()["data"]
    assert len(logs) >= 3
    assert logs[0]["seq"] == 1
    assert any("Inserted 25" in line["message"] for line in logs)


def test_logs_can_be_polled_incrementally(client, imported):
    job_id = client.get("/api/v1/jobs").get_json()["data"][0]["job_id"]

    first = client.get(f"/api/v1/jobs/{job_id}/logs?limit=1").get_json()["data"]
    assert len(first) == 1
    rest = client.get(
        f"/api/v1/jobs/{job_id}/logs?after_seq={first[0]['seq']}"
    ).get_json()["data"]
    assert all(line["seq"] > first[0]["seq"] for line in rest)


def test_finished_job_cannot_be_cancelled(client, imported):
    job_id = client.get("/api/v1/jobs").get_json()["data"][0]["job_id"]

    response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "job_not_cancellable"


def test_cancel_unknown_job_returns_404(client):
    response = client.post("/api/v1/jobs/job_missing/cancel")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "job_not_found"


def test_job_filters(client, imported):
    filtered = client.get("/api/v1/jobs?status=failed").get_json()
    assert filtered["meta"]["total"] == 0

    by_kind = client.get("/api/v1/jobs?kind=ingestion.import.modis").get_json()
    assert by_kind["meta"]["total"] == 1
