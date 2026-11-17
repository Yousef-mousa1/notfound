"""Vercel entrypoint for the read-only PyroScope demo API.

Vercel Functions have no nginx layer, so this module exposes the Flask app
directly. The bundled DuckDB snapshot is opened read-only (config/vercel.yaml)
and contains precomputed results only; no mutation endpoints are reachable
from the public demo.
"""

from __future__ import annotations

from pathlib import Path

from app import create_app

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "vercel.yaml"
application = create_app(str(CONFIG_PATH))
app = application
