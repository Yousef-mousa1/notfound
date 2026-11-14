"""Robust anomaly detection on daily per-cell detection counts.

Method (documented and returned with every run):

- A time series is one ``(grid cell, sensor)`` pair of daily detection counts.
- A cell needs at least ``min_days`` days with detections to have a baseline.
- Baseline = median, scale = 1.4826 * MAD (median absolute deviation).
- If MAD is zero (a flat series), the Poisson scale ``sqrt(median)`` is used as
  a documented fallback; if that is also zero the cell is skipped.
- Robust z = (count - median) / scale. A day is flagged when
  ``z >= threshold`` and ``count >= min_detections``.
- Severity bands: moderate ``threshold..5``, high ``5..7``, extreme ``>=7``.

This is a statistical outlier rule, not a fire-danger forecast. Sparse counts
and short series make the baseline unstable; every response reports the
parameters and the number of cells that could not be evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

MAD_TO_SIGMA = 1.4826
SEVERITY_HIGH = 5.0
SEVERITY_EXTREME = 7.0

ANOMALY_COLUMNS = (
    "cell_id",
    "sensor",
    "day",
    "detections",
    "baseline_median",
    "baseline_scale",
    "robust_z",
    "severity",
    "center_lat",
    "center_lon",
)


@dataclass(frozen=True)
class Thresholds:
    """Detection parameters, all echoed in the response."""

    min_days: int = 5
    min_detections: int = 3
    threshold: float = 3.5

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_days": self.min_days,
            "min_detections": self.min_detections,
            "threshold": self.threshold,
            "scale": "1.4826 * MAD, Poisson sqrt(median) fallback when MAD = 0",
            "severity_bands": {
                "moderate": [self.threshold, SEVERITY_HIGH],
                "high": [SEVERITY_HIGH, SEVERITY_EXTREME],
                "extreme": [SEVERITY_EXTREME, None],
            },
        }


@dataclass
class DetectionStats:
    """Counts describing what the rule evaluated and skipped."""

    n_cells_total: int = 0
    n_cells_evaluated: int = 0
    n_cells_skipped_short: int = 0
    n_cells_skipped_flat: int = 0
    n_cell_days: int = 0
    n_anomalies: int = 0
    severity_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "series_total": self.n_cells_total,
            "series_evaluated": self.n_cells_evaluated,
            "series_skipped_short": self.n_cells_skipped_short,
            "series_skipped_no_scale": self.n_cells_skipped_flat,
            "cell_days_evaluated": self.n_cell_days,
            "anomalies": self.n_anomalies,
            "series_basis": "one series per (grid cell, sensor); sensors are never merged",
            "severity_counts": self.severity_counts,
        }


def severity_for(z: float, threshold: float) -> str:
    """Severity band for a robust z-score at or above ``threshold``."""
    if z >= SEVERITY_EXTREME:
        return "extreme"
    if z >= SEVERITY_HIGH:
        return "high"
    return "moderate" if z >= threshold else "normal"


def detect(frame: pd.DataFrame, thresholds: Thresholds) -> tuple[pd.DataFrame, DetectionStats]:
    """Detect anomalies in a per-cell daily count frame.

    Args:
        frame: Columns ``cell_id``, ``sensor``, ``day``, ``detections``,
            ``center_lat``, ``center_lon``.
        thresholds: Validated detection parameters.

    Returns:
        The flagged rows (columns in :data:`ANOMALY_COLUMNS`) and counters.
    """
    stats = DetectionStats(severity_counts={"moderate": 0, "high": 0, "extreme": 0})
    if frame.empty:
        return pd.DataFrame(columns=ANOMALY_COLUMNS), stats

    work = frame.copy()
    work["detections"] = pd.to_numeric(work["detections"], errors="coerce")
    work = work.dropna(subset=["detections"])

    flagged: list[dict[str, Any]] = []
    for (cell_id, sensor), group in work.groupby(["cell_id", "sensor"], sort=False):
        stats.n_cells_total += 1
        if len(group) < thresholds.min_days:
            stats.n_cells_skipped_short += 1
            continue

        values = group["detections"].to_numpy(dtype="float64")
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        scale = MAD_TO_SIGMA * mad
        if scale <= 0:
            scale = float(np.sqrt(median)) if median > 0 else 0.0
        if scale <= 0:
            stats.n_cells_skipped_flat += 1
            continue

        stats.n_cells_evaluated += 1
        stats.n_cell_days += int(len(group))
        z_scores = (values - median) / scale

        for (_, row), z in zip(group.iterrows(), z_scores, strict=True):
            if z < thresholds.threshold or row["detections"] < thresholds.min_detections:
                continue
            severity = severity_for(float(z), thresholds.threshold)
            flagged.append(
                {
                    "cell_id": str(cell_id),
                    "sensor": str(sensor),
                    "day": row["day"],
                    "detections": int(row["detections"]),
                    "baseline_median": median,
                    "baseline_scale": scale,
                    "robust_z": float(z),
                    "severity": severity,
                    "center_lat": float(row["center_lat"]),
                    "center_lon": float(row["center_lon"]),
                }
            )
            stats.n_anomalies += 1
            stats.severity_counts[severity] = stats.severity_counts.get(severity, 0) + 1

    result = pd.DataFrame(flagged, columns=ANOMALY_COLUMNS)
    return result, stats
