"""Vercel entrypoint for the read-only PyroScope demo API.

Vercel Functions have no nginx layer, so this module exposes the Flask app
directly. The bundled DuckDB snapshot is opened read-only (config/vercel.yaml)
and contains precomputed results only; no mutation endpoints are reachable
from the public demo.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Vercel may install the package into site-packages rather than keeping it at
# backend/src/. Put our own directories first so `app` and `harmonizer` resolve
# from the bundle, and project_root() points at backend/ (where the DB lives).
_ROOT = Path(__file__).resolve().parent
for _candidate in (str(_ROOT), str(_ROOT / "src")):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from app import create_app  # noqa: E402

CONFIG_PATH = _ROOT / "config" / "vercel.yaml"
application = create_app(str(CONFIG_PATH))
app = application
