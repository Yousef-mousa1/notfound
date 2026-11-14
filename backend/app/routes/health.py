"""Liveness endpoint."""

from __future__ import annotations

from flask import Blueprint, jsonify

from harmonizer import __version__

health_blueprint = Blueprint("health", __name__)


@health_blueprint.get("/health")
def health():  # noqa: ANN202 - Flask view signature
    """Report that the service is up."""
    return jsonify({"status": "ok", "service": "harmonizer-api", "version": __version__})
