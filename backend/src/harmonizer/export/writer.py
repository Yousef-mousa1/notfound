"""File writers for exported datasets, reports and metadata (Phase 09).

Rules enforced here:

- Exports always write **new** files under a dedicated directory; imported
  observations and the raw CSVs are never modified.
- Every written file is described by ``name``, ``format``, ``rows``,
  ``byte_size`` and ``sha256`` so an export can be verified later.
- CSV cells keep their original values. Nothing is rewritten, rounded,
  re-coded or prefixed, because an export must reproduce the stored data.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import harmonizer


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _describe(path: Path, file_format: str, rows: int | None) -> dict[str, Any]:
    """Build the file descriptor stored in export metadata."""
    return {
        "name": path.name,
        "format": file_format,
        "rows": rows,
        "byte_size": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def write_csv(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    """Write a DataFrame as UTF-8 CSV and describe the written file.

    ``lineterminator="\\n"`` is explicit so the same input produces a
    byte-identical file on Windows and Linux (reproducibility check).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    return _describe(path, "csv", int(len(frame)))


def write_json(payload: Any, path: Path) -> dict[str, Any]:
    """Write a JSON document (UTF-8, indented) and describe the written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return _describe(path, "json", None)


def software_versions() -> dict[str, Any]:
    """Versions needed to reproduce an export."""
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "harmonizer": harmonizer.__version__,
        "duckdb": duckdb.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }


def safe_file_name(name: str | None, default: str, extension: str = ".csv") -> str:
    """Return a filesystem-safe file name with the required extension.

    Only ASCII letters, digits, dot, dash and underscore are kept; everything
    else becomes ``_``. The extension is forced so a caller cannot write an
    arbitrary file type.
    """
    stem = (name or default).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    cleaned = "".join(
        character if character.isascii() and (character.isalnum() or character in "._-")
        else "_"
        for character in stem
    ).strip("._-")
    if extension and cleaned.lower().endswith(extension):
        cleaned = cleaned[: -len(extension)]
    cleaned = cleaned or default
    return f"{cleaned}{extension}"
