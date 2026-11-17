"""Database wiring for the Flask application."""

from __future__ import annotations

from flask import Flask, current_app

from harmonizer.config import resolve_path
from harmonizer.store import Database


def init_database(app: Flask) -> Database:
    """Open the configured DuckDB store and attach it to the app."""
    config = app.config["HARMONIZER"]
    storage = config.get("storage") or {}
    database = Database(
        resolve_path(config, "storage", "duckdb_path"),
        read_only=bool(storage.get("read_only", False)),
    )
    app.extensions["db"] = database
    return database


def get_db() -> Database:
    """Return the request-scoped analytical store."""
    return current_app.extensions["db"]
