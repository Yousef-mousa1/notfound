"""Read-only demo page.

The page is a static template that fetches the public API from the browser. It
contains no scientific logic and no server-side computation: every number on
screen comes from an endpoint that is documented in ``docs/api-endpoints.md``.
"""

from __future__ import annotations

from flask import Blueprint, render_template

ui_blueprint = Blueprint("ui", __name__)


@ui_blueprint.get("/demo")
def demo():
    """Render the single-page demo dashboard."""
    return render_template("demo.html")
