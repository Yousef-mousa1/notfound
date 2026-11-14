"""Per-cell harmonized activity index.

The index is **unitless and relative to the analysed run**. It is built from
per-sensor, per-cell summaries that are normalized by that sensor's own p95
within the run, so a MODIS count is never compared to a VIIRS count directly:

    sensor_index = 0.5 * min(1, count / p95(count))
                 + 0.5 * min(1, mean_frp / p95(mean_frp))

    harmonized_activity_index = mean of the sensor indices present in the cell

Properties and limitations (returned with every endpoint):

- A cell with only one sensor can reach 1.0, the same as a cell with both
  sensors. The ``sensors_present`` column is therefore always reported and
  consumers must not read the index as agreement or confidence.
- ``mean_frp`` for VIIRS may be calibration-transformed before normalization;
  the transform is a cross-sensor mapping fitted on matched pairs, not a
  physical correction.
- No raw FRP value is ever summed across sensors and no energy is derived.
- Cells with no detection are absent from the output: absence of a row is not
  evidence of absence of fire.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .calibration import CalibrationFit, apply_calibration

COUNT_WEIGHT = 0.5
FRP_WEIGHT = 0.5
SCALE_QUANTILE = 0.95

RESULT_COLUMNS = (
    "cell_id",
    "time_bucket",
    "sensors_present",
    "modis_count",
    "viirs_count",
    "modis_mean_frp_mw",
    "viirs_mean_frp_mw",
    "viirs_mean_frp_calibrated_mw",
    "modis_index",
    "viirs_index",
    "harmonized_activity_index",
    "uncertainty_mw",
)


def _scale(values: pd.Series, quantile: float = SCALE_QUANTILE) -> float | None:
    """p95 scale for one sensor, or ``None`` when the sensor is degenerate."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return None
    scale = float(np.quantile(clean.to_numpy(dtype="float64"), quantile))
    return scale if scale > 0 else None


def _normalized(values: pd.Series, scale: float | None) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if scale is None:
        return pd.Series(0.0, index=values.index, dtype="float64")
    return (numeric / scale).clip(lower=0.0, upper=1.0)


def _sensor_index(count: pd.Series, mean_frp: pd.Series, count_scale: float | None, frp_scale: float | None) -> pd.Series:
    count_norm = _normalized(count, count_scale)
    frp_norm = _normalized(mean_frp, frp_scale)
    return (COUNT_WEIGHT * count_norm + FRP_WEIGHT * frp_norm).clip(0.0, 1.0)


def harmonize_cells(
    aggregates: pd.DataFrame, fit: CalibrationFit
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build per-cell, per-time-bucket harmonized rows.

    Args:
        aggregates: Output of the aggregate query with columns ``cell_id``,
            ``time_bucket``, ``sensor``, ``detections`` and ``mean_frp_mw``.
        fit: Calibration applied to VIIRS mean FRP before normalization.

    Returns:
        The result frame (columns in :data:`RESULT_COLUMNS`) and the metadata
        describing the normalization scales and formula.
    """
    frame = aggregates.copy()
    frame["cell_id"] = frame["cell_id"].astype(str)
    frame["time_bucket"] = frame["time_bucket"].astype(str)
    frame["sensor"] = frame["sensor"].astype(str)

    viirs_mask = frame["sensor"] == "viirs"
    calibrated = pd.Series(np.nan, index=frame.index, dtype="float64")
    if viirs_mask.any():
        calibrated.loc[viirs_mask] = apply_calibration(
            fit, frame.loc[viirs_mask, "mean_frp_mw"].to_numpy(dtype="float64")
        )
    frame["mean_frp_calibrated_mw"] = calibrated

    key = ["cell_id", "time_bucket"]
    modis = frame[frame["sensor"] == "modis"].set_index(key)
    viirs = frame[frame["sensor"] == "viirs"].set_index(key)

    index = modis.index.union(viirs.index)
    output = pd.DataFrame(index=index)
    output.index.names = key

    output["modis_count"] = modis["detections"].reindex(index)
    output["viirs_count"] = viirs["detections"].reindex(index)
    output["modis_mean_frp_mw"] = modis["mean_frp_mw"].reindex(index)
    output["viirs_mean_frp_mw"] = viirs["mean_frp_mw"].reindex(index)
    output["viirs_mean_frp_calibrated_mw"] = viirs["mean_frp_calibrated_mw"].reindex(index)

    modis_count_scale = _scale(output["modis_count"])
    modis_frp_scale = _scale(output["modis_mean_frp_mw"])
    viirs_count_scale = _scale(output["viirs_count"])
    viirs_frp_scale = _scale(output["viirs_mean_frp_calibrated_mw"])

    output["modis_index"] = _sensor_index(
        output["modis_count"], output["modis_mean_frp_mw"], modis_count_scale, modis_frp_scale
    ).where(output["modis_count"].notna())
    output["viirs_index"] = _sensor_index(
        output["viirs_count"],
        output["viirs_mean_frp_calibrated_mw"],
        viirs_count_scale,
        viirs_frp_scale,
    ).where(output["viirs_count"].notna())

    indices = output[["modis_index", "viirs_index"]]
    output["sensors_present"] = indices.notna().sum(axis=1).astype(int)
    output["harmonized_activity_index"] = indices.mean(axis=1, skipna=True)

    both = output["modis_count"].notna() & output["viirs_count"].notna()
    output["uncertainty_mw"] = np.where(
        both,
        (output["modis_mean_frp_mw"] - output["viirs_mean_frp_calibrated_mw"]).abs(),
        np.nan,
    )

    output = output.reset_index()
    output = output[list(RESULT_COLUMNS)]

    metadata = {
        "formula": (
            "0.5 * min(1, count / p95(count)) + 0.5 * min(1, mean_frp / p95(mean_frp)), "
            "per sensor; harmonized index = equal-weight mean of present sensor indices"
        ),
        "count_weight": COUNT_WEIGHT,
        "frp_weight": FRP_WEIGHT,
        "scale_quantile": SCALE_QUANTILE,
        "scales": {
            "modis_count": modis_count_scale,
            "modis_mean_frp_mw": modis_frp_scale,
            "viirs_count": viirs_count_scale,
            "viirs_mean_frp_calibrated_mw": viirs_frp_scale,
        },
        "calibration_method": fit.method,
        "uncertainty_definition": (
            "absolute difference between MODIS mean FRP and calibrated VIIRS mean FRP "
            "in cells where both sensors are present; null otherwise"
        ),
        "limitations": [
            "The index is unitless and relative to this run's own p95 scales, not a physical quantity.",
            "A one-sensor cell can reach 1.0; read sensors_present before interpreting the index.",
            "VIIRS mean FRP may be calibration-transformed on matched pairs; MODIS is not ground truth.",
            "Only cells/time buckets with detections are returned; no row does not mean no fire.",
            "FRP normalization starts from the cell mean, so a non-linear calibration is applied to that mean, not to every detection.",
            "No FRP value is summed across sensors and no energy is derived.",
        ],
    }
    return output, metadata
