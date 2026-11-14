"""Harmonizer: MODIS/VIIRS active-fire hot spot harmonization (PyroScope).

This package contains all scientific and data-processing logic. It must never
import Flask; the web layer (``app``) only calls into this package.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.2.0"
