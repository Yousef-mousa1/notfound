"""Minimal file registry helpers (hashing and metadata).

Registration itself lives in the store; these functions are pure and testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileFingerprint:
    """Stable identity of a file, used to avoid duplicate imports."""

    path: Path
    size: int
    mtime: float
    sha256: str


def fingerprint(path: str | Path, chunk_size: int = 1024 * 1024) -> FileFingerprint:
    """Compute size, modification time and SHA-256 of a file.

    Reads in chunks so large CSVs do not need to fit in memory.
    """
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)

    stat = file_path.stat()
    return FileFingerprint(
        path=file_path,
        size=stat.st_size,
        mtime=stat.st_mtime,
        sha256=digest.hexdigest(),
    )
