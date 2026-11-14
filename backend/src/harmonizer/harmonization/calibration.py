"""Cross-sensor calibration fitted on matched pairs.

MODIS is not ground truth. These transforms map VIIRS FRP onto the MODIS FRP
scale as observed in matched pairs; they describe the sample, not a physical
correction. Every fit therefore returns its diagnostics (n, residuals) and the
matching parameters that produced the pairs.

Supported: ``ratio``, ``linear-regression``, ``quantile-mapping``.
``random-forest`` is deliberately not fitted: it needs labelled training data
and a validation strategy (``docs/phases/phase-08-ml.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class CalibrationFit:
    """A fitted transform plus the diagnostics needed to judge it."""

    method: str
    spec: dict[str, Any]
    n_pairs: int
    rmse_mw: float | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "spec": self.spec,
            "n_pairs": self.n_pairs,
            "rmse_mw": self.rmse_mw,
            "diagnostics": self.diagnostics,
            "note": (
                "Fitted on matched MODIS/VIIRS pairs. MODIS is not ground truth; "
                "this is a cross-sensor mapping, not a physical correction."
            ),
        }


def apply_calibration(fit: CalibrationFit, values: np.ndarray | float) -> np.ndarray:
    """Apply a fitted transform to VIIRS FRP values (MW)."""
    array = np.asarray(values, dtype="float64")
    if fit.method == "none":
        return array
    if fit.method == "ratio":
        return array * float(fit.spec["factor"])
    if fit.method == "linear-regression":
        return float(fit.spec["intercept"]) + float(fit.spec["slope"]) * array
    if fit.method == "quantile-mapping":
        source = np.asarray(fit.spec["source_quantiles"], dtype="float64")
        target = np.asarray(fit.spec["target_quantiles"], dtype="float64")
        return np.interp(array, source, target)
    raise ValueError(f"Cannot apply calibration method '{fit.method}'.")


def _usable(modis: np.ndarray, viirs: np.ndarray, positive: bool) -> tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(modis) & np.isfinite(viirs)
    if positive:
        mask &= (modis > 0) & (viirs > 0)
    return modis[mask], viirs[mask]


def _rmse(predicted: np.ndarray, observed: np.ndarray) -> float | None:
    if observed.size == 0:
        return None
    return float(np.sqrt(np.mean((predicted - observed) ** 2)))


def fit_ratio(modis: np.ndarray, viirs: np.ndarray) -> CalibrationFit:
    """VIIRS * factor, with ``factor = median(MODIS / VIIRS)``.

    The median makes the factor robust to the heavy FRP tail.
    """
    m, v = _usable(np.asarray(modis), np.asarray(viirs), positive=True)
    if m.size < 2:
        raise ValueError("Not enough matched pairs with positive FRP for a ratio fit.")

    ratios = m / v
    factor = float(np.median(ratios))
    fit = CalibrationFit(
        method="ratio",
        spec={"factor": factor},
        n_pairs=int(m.size),
        diagnostics={
            "median_ratio": factor,
            "iqr_ratio": _quantile(ratios, 0.75) - _quantile(ratios, 0.25),
            "p10_ratio": _quantile(ratios, 0.10),
            "p90_ratio": _quantile(ratios, 0.90),
        },
    )
    fit.rmse_mw = _rmse(v * factor, m)
    return fit


def fit_linear(modis: np.ndarray, viirs: np.ndarray) -> CalibrationFit:
    """Ordinary least squares ``MODIS = intercept + slope * VIIRS``."""
    m, v = _usable(np.asarray(modis), np.asarray(viirs), positive=False)
    if m.size < 3:
        raise ValueError("Not enough matched pairs for a linear fit.")

    design = np.column_stack([v, np.ones_like(v)])
    solution, *_ = np.linalg.lstsq(design, m, rcond=None)
    slope, intercept = float(solution[0]), float(solution[1])
    predicted = intercept + slope * v
    residuals = m - predicted
    total = float(np.sum((m - float(np.mean(m))) ** 2))
    residual_sum = float(np.sum(residuals**2))
    r2 = None if total == 0 else 1.0 - residual_sum / total

    fit = CalibrationFit(
        method="linear-regression",
        spec={"slope": slope, "intercept": intercept},
        n_pairs=int(m.size),
        diagnostics={
            "r2": r2,
            "residual_std_mw": float(np.std(residuals, ddof=1)) if m.size > 1 else None,
            "viirs_range_mw": [float(v.min()), float(v.max())],
            "modis_range_mw": [float(m.min()), float(m.max())],
        },
    )
    fit.rmse_mw = _rmse(predicted, m)
    return fit


def fit_quantile(modis: np.ndarray, viirs: np.ndarray, points: int = 101) -> CalibrationFit:
    """Empirical quantile mapping of VIIRS FRP onto the MODIS distribution."""
    m, v = _usable(np.asarray(modis), np.asarray(viirs), positive=True)
    if m.size < 10:
        raise ValueError("Not enough matched pairs for quantile mapping (need >= 10).")

    probabilities = np.linspace(0.0, 1.0, points)
    source = np.quantile(v, probabilities)
    target = np.quantile(m, probabilities)
    # Keep the mapping strictly monotonic so interpolation is well defined.
    source = np.maximum.accumulate(source + np.arange(points) * 1e-9)

    fit = CalibrationFit(
        method="quantile-mapping",
        spec={
            "source_quantiles": [float(x) for x in source],
            "target_quantiles": [float(x) for x in target],
            "points": points,
        },
        n_pairs=int(m.size),
        diagnostics={
            "viirs_range_mw": [float(v.min()), float(v.max())],
            "modis_range_mw": [float(m.min()), float(m.max())],
            "clipping": "Values outside the fitted range are clipped by interpolation.",
        },
    )
    fit.rmse_mw = _rmse(np.interp(v, source, target), m)
    return fit


def fit_none() -> CalibrationFit:
    """Identity transform: sensors are compared without rescaling."""
    return CalibrationFit(
        method="none",
        spec={},
        n_pairs=0,
        diagnostics={"reason": "Identity transform; no cross-sensor rescaling applied."},
    )


def fit(method: str, modis: np.ndarray, viirs: np.ndarray) -> CalibrationFit:
    """Dispatch a calibration fit by name."""
    if method == "none":
        return fit_none()
    if method == "ratio":
        return fit_ratio(modis, viirs)
    if method == "linear-regression":
        return fit_linear(modis, viirs)
    if method == "quantile-mapping":
        return fit_quantile(modis, viirs)
    if method == "random-forest":
        raise NotImplementedError(
            "random-forest is not implemented: it requires labelled training data and a "
            "spatial/temporal validation strategy. MODIS is not ground truth."
        )
    raise ValueError(f"Unknown calibration method: {method}")


def _quantile(values: np.ndarray, probability: float) -> float:
    return float(np.quantile(values, probability))
