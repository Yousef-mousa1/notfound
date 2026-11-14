"""Cross-sensor consistency metrics on matched pairs.

These are **not accuracy metrics**: there is no independent ground truth. MODIS
is not truth and agreement is not proof that either sensor is correct. MAE/RMSE
and bias are reported on ``log10(FRP)`` (heavy-tailed distribution) as well as
raw MW, always with the pair count.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def _clean(modis: np.ndarray, viirs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(modis, dtype="float64")
    b = np.asarray(viirs, dtype="float64")
    mask = np.isfinite(a) & np.isfinite(b)
    return a[mask], b[mask]


def _positive_log(modis: np.ndarray, viirs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b = _clean(modis, viirs)
    mask = (a > 0) & (b > 0)
    return np.log10(a[mask]), np.log10(b[mask])


def mae(observed: np.ndarray, predicted: np.ndarray) -> float:
    """Mean absolute difference."""
    a, b = _clean(observed, predicted)
    return float(np.mean(np.abs(a - b))) if a.size else float("nan")


def rmse(observed: np.ndarray, predicted: np.ndarray) -> float:
    """Root mean squared difference."""
    a, b = _clean(observed, predicted)
    return float(np.sqrt(np.mean((a - b) ** 2))) if a.size else float("nan")


def bias(observed: np.ndarray, predicted: np.ndarray) -> float:
    """Mean signed difference ``observed - predicted``."""
    a, b = _clean(observed, predicted)
    return float(np.mean(a - b)) if a.size else float("nan")


def pearson(observed: np.ndarray, predicted: np.ndarray) -> float | None:
    """Pearson correlation coefficient."""
    a, b = _clean(observed, predicted)
    if a.size < 2 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def spearman(observed: np.ndarray, predicted: np.ndarray) -> float | None:
    """Spearman rank correlation (no SciPy dependency)."""
    a, b = _clean(observed, predicted)
    if a.size < 2:
        return None
    ranked_a = pd.Series(a).rank(method="average").to_numpy()
    ranked_b = pd.Series(b).rank(method="average").to_numpy()
    if np.std(ranked_a) == 0 or np.std(ranked_b) == 0:
        return None
    return float(np.corrcoef(ranked_a, ranked_b)[0, 1])


def ks_statistic(sample_a: np.ndarray, sample_b: np.ndarray) -> float | None:
    """Two-sample Kolmogorov-Smirnov statistic."""
    a, b = _clean(sample_a, sample_b)
    if a.size == 0 or b.size == 0:
        return None
    a = np.sort(a)
    b = np.sort(b)
    grid = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, grid, side="right") / a.size
    cdf_b = np.searchsorted(b, grid, side="right") / b.size
    return float(np.max(np.abs(cdf_a - cdf_b)))


def quantile_table(values: np.ndarray, levels: tuple[float, ...] = QUANTILE_LEVELS) -> dict[str, float | None]:
    """Quantiles as a JSON-friendly mapping."""
    array = np.asarray(values, dtype="float64")
    array = array[np.isfinite(array)]
    if array.size == 0:
        return {f"p{int(level * 100):02d}": None for level in levels}
    return {
        f"p{int(level * 100):02d}": float(np.quantile(array, level)) for level in levels
    }


def summarize(modis: np.ndarray, viirs: np.ndarray) -> dict[str, object]:
    """Full consistency summary on log10 FRP (primary) and raw MW."""
    a, b = _clean(modis, viirs)
    log_a, log_b = _positive_log(modis, viirs)

    def _or_none(value: float | None) -> float | None:
        if value is None:
            return None
        return None if not np.isfinite(value) else float(value)

    return {
        "n_pairs": int(a.size),
        "n_positive_pairs": int(log_a.size),
        "log10_frp": {
            "mae": _or_none(mae(log_a, log_b)),
            "rmse": _or_none(rmse(log_a, log_b)),
            "bias_modis_minus_viirs": _or_none(bias(log_a, log_b)),
            "pearson_r": _or_none(pearson(log_a, log_b)),
            "spearman_rho": _or_none(spearman(log_a, log_b)),
            "ks_statistic": _or_none(ks_statistic(log_a, log_b)),
        },
        "raw_mw": {
            "mae": _or_none(mae(a, b)),
            "rmse": _or_none(rmse(a, b)),
            "bias_modis_minus_viirs": _or_none(bias(a, b)),
            "median_modis_mw": _or_none(float(np.median(a))) if a.size else None,
            "median_viirs_mw": _or_none(float(np.median(b))) if b.size else None,
        },
        "distribution": {
            "modis": quantile_table(a),
            "viirs": quantile_table(b),
        },
        "limitations": [
            "These are cross-sensor consistency metrics, not accuracy metrics: no independent reference data is used.",
            "MODIS is not ground truth; agreement does not prove that either product is correct.",
            "Pairs depend on the matching radius/time window and are not independent samples.",
            "FRP is instantaneous power (MW); no energy is derived.",
        ],
    }
