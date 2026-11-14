"""CORS headers: the browser frontend calls the API from another origin."""
from __future__ import annotations


def test_cors_headers_for_allowed_origin(client):
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]


def test_cors_preflight_is_accepted(client):
    response = client.options(
        "/api/v1/dashboard/overview",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"


def test_cors_headers_absent_for_unknown_origin(client):
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "Access-Control-Allow-Origin" not in response.headers
