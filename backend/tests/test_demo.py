"""Demo page tests.

The page must stay offline-safe (no CDN or external asset) and must only
reference endpoints that actually exist. It renders no data itself: every panel
is fetched from the API in the browser.
"""

from __future__ import annotations

import re

CALL_PATTERN = re.compile(r"api\(\s*\"(/[^\"]+)\"")


def test_demo_page_renders(client):
    response = client.get("/demo")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    html = response.get_data(as_text=True)
    assert "PyroScope" in html
    assert "not</em> accuracy" in html
    assert "one MODIS" not in html  # the page states sensor non-interchangeability instead
    assert "not interchangeable" in html


def test_demo_page_is_offline_safe_and_static(client):
    html = client.get("/demo").get_data(as_text=True)

    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()
    assert "{{" not in html  # no server-side templating of data


def test_demo_page_only_references_existing_endpoints(app, client):
    html = client.get("/demo").get_data(as_text=True)
    referenced = {
        "/api/v1" + path.split("?")[0] for path in CALL_PATTERN.findall(html)
    }
    assert referenced, "the page should reference the API"

    rules = {rule.rule for rule in app.url_map.iter_rules()}
    missing = sorted(path for path in referenced if path not in rules)
    assert not missing, f"demo page references unknown endpoints: {missing}"


def test_root_lists_demo(client):
    payload = client.get("/").get_json()

    assert payload["demo"] == "/demo"
