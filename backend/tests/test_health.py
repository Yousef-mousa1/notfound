"""Smoke test: the app starts and reports liveness."""

from __future__ import annotations


def test_health_returns_200_json(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.is_json
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["service"] == "harmonizer-api"
    assert payload["version"]


def test_index_lists_endpoint_groups(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["api_prefix"] == "/api/v1"
    assert "/api/v1/observations" in payload["groups"]


def test_unknown_route_returns_json_404(client) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"
