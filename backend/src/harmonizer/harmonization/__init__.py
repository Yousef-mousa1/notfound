"""Sensor harmonization: cross-sensor calibration on matched pairs.

MODIS is never treated as ground truth. Results describe cross-sensor
consistency in this sample and carry their diagnostics.
"""

from __future__ import annotations

from .activity import harmonize_cells
from .calibration import (
    CalibrationFit,
    apply_calibration,
    fit,
    fit_linear,
    fit_none,
    fit_quantile,
    fit_ratio,
)

__all__ = [
    "CalibrationFit",
    "apply_calibration",
    "fit",
    "fit_linear",
    "fit_none",
    "fit_quantile",
    "fit_ratio",
    "harmonize_cells",
]
