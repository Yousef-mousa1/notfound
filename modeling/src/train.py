"""Train MODIS -> VIIRS models on cell-days, with an evaluation that can be trusted.

Three tasks are learned from the same MODIS features:
  * presence  : does VIIRS see at least one detection in this cell-day?
  * count     : how many VIIRS detections (Poisson model)
  * frp       : mean VIIRS FRP where VIIRS fired

What changed compared with the first version
  1. Train / validation / test split in contiguous blocks.
       --split time  : blocks of --block-days days (neighbouring days stay together)
       --split space : tiles of --tile-deg degrees (a region is never in two sets)
  2. Models, thresholds and the winner are chosen on VALIDATION only. The test set
     is scored once, for the winner, with the threshold found on validation.
  3. Trivial baselines are reported next to the models.
  4. The saved models are refit on train + validation.
  5. Permutation importance on validation shows what the model really relies on.
  6. --drop removes features (for example cell_lat cell_lon) to test generalisation.

Usage:
    python train.py --data data/processed/cellday_a.parquet --out outputs/run_a
    python train.py --data data/processed/cellday_a.parquet --out outputs/run_a_space \
        --split space --drop cell_lat cell_lon
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

try:  # LightGBM/XGBoost need libomp on macOS; degrade instead of failing.
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except Exception as error:  # noqa: BLE001
    lgb = None
    HAS_LIGHTGBM = False
    print(f"[warn] LightGBM unavailable: {type(error).__name__}; skipping it.", file=sys.stderr)

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except Exception as error:  # noqa: BLE001
    xgb = None
    HAS_XGBOOST = False
    print(f"[warn] XGBoost unavailable: {type(error).__name__}; skipping it.", file=sys.stderr)

from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    mean_absolute_error,
    mean_poisson_deviance,
    precision_recall_curve,
    r2_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

ALL_FEATURES = [
    "modis_detections",
    "modis_frp_mean",
    "modis_frp_max",
    "modis_frp_sum",
    "modis_frp_std",
    "modis_bt_primary_mean",
    "modis_bt_primary_max",
    "modis_bt_secondary_mean",
    "modis_bt_secondary_max",
    "modis_scan_mean",
    "modis_track_mean",
    "modis_hour_mean",
    "modis_night_share",
    "modis_platforms",
    "modis_conf_low",
    "modis_conf_nominal",
    "modis_conf_high",
    "modis_neighbour_count",
    "modis_prev1_count",
    "modis_prev2_count",
    "modis_prev3_count",
    "modis_prev3_mean",
    "doy_sin",
    "doy_cos",
    "hour_sin",
    "hour_cos",
    "cell_lat",
    "cell_lon",
]


def load(paths: list[Path], columns: list[str] | None = None) -> pd.DataFrame:
    df = pd.concat(
        [pd.read_parquet(path, columns=columns) for path in paths], ignore_index=True
    )
    df["date"] = pd.to_datetime(df["date"])
    if "year" not in df.columns:
        df["year"] = df["date"].dt.year
    return df


# ----------------------------------------------------------------------------- split
def group_ids(df: pd.DataFrame, mode: str, block_days: int, tile_deg: float) -> np.ndarray:
    if mode == "time":
        days = (df["date"] - df["date"].min()).dt.days.to_numpy()
        return (days // block_days).astype(np.int64)
    if mode == "year":
        return df["date"].dt.year.to_numpy(dtype=np.int64)
    lat_tile = np.floor((df["cell_lat"].to_numpy(dtype=float) + 90.0) / tile_deg).astype(np.int64)
    lon_tile = np.floor((df["cell_lon"].to_numpy(dtype=float) + 180.0) / tile_deg).astype(np.int64)
    # Multiplier from the actual span, so small tiles cannot collide.
    return lat_tile * (int(lon_tile.max()) + 1) + lon_tile


def split_indices(groups: np.ndarray, seed: int, fractions=(0.6, 0.2)) -> tuple[np.ndarray, ...]:
    unique = np.random.default_rng(seed).permutation(np.unique(groups))
    if len(unique) < 5:
        sys.exit(
            f"Only {len(unique)} groups to split. Use a smaller --block-days / --tile-deg or more data."
        )
    n_train = int(round(len(unique) * fractions[0]))
    n_val = int(round(len(unique) * fractions[1]))
    parts = (unique[:n_train], unique[n_train : n_train + n_val], unique[n_train + n_val :])
    indices = tuple(np.flatnonzero(np.isin(groups, part)) for part in parts)
    if any(len(idx) == 0 for idx in indices):
        sys.exit("One of the splits is empty. Adjust --block-days / --tile-deg.")
    return indices


# ------------------------------------------------------------------------- models
def linear_preprocessor(features: list[str]) -> ColumnTransformer:
    skewed = [f for f in features if f.endswith(("_detections", "_count", "_mean", "_max", "_sum", "_std"))]
    rest = [f for f in features if f not in skewed]
    parts = []
    if skewed:
        parts.append(
            (
                "log",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("log", FunctionTransformer(np.log1p)),
                        ("scale", StandardScaler()),
                    ]
                ),
                skewed,
            )
        )
    if rest:
        parts.append(
            ("plain", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), rest)
        )
    return ColumnTransformer(parts)


def classifiers(features: list[str], seed: int) -> dict:
    models = {
        "logistic_regression": Pipeline(
            [("prep", linear_preprocessor(features)), ("model", LogisticRegression(max_iter=2000))]
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=seed),
    }
    if HAS_LIGHTGBM:
        models["lightgbm"] = lgb.LGBMClassifier(
            n_estimators=500, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=seed
        )
    if HAS_XGBOOST:
        models["xgboost"] = xgb.XGBClassifier(
            n_estimators=500, learning_rate=0.05, max_depth=6, subsample=0.9, colsample_bytree=0.9,
            eval_metric="logloss", random_state=seed,
        )
    return models


def regressors(features: list[str], seed: int) -> dict:
    models = {
        "poisson_regression": Pipeline(
            [("prep", linear_preprocessor(features)), ("model", PoissonRegressor(max_iter=500))]
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            loss="poisson", max_iter=300, learning_rate=0.08, random_state=seed
        ),
    }
    if HAS_LIGHTGBM:
        models["lightgbm"] = lgb.LGBMRegressor(
            objective="poisson", n_estimators=500, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=seed
        )
    if HAS_XGBOOST:
        models["xgboost"] = xgb.XGBRegressor(
            objective="count:poisson", n_estimators=500, learning_rate=0.05, max_depth=6,
            subsample=0.9, colsample_bytree=0.9, random_state=seed,
        )
    return models


def frp_regressor(seed: int):
    if HAS_LIGHTGBM:
        return lgb.LGBMRegressor(
            n_estimators=400, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=seed
        )
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.08, random_state=seed)


# ------------------------------------------------------------------------ metrics
def pick_threshold(y_true: np.ndarray, proba: np.ndarray) -> tuple[float, float | None]:
    """Best-F1 threshold and the threshold with the best recall at precision >= 0.8."""
    precision, recall, thresholds = precision_recall_curve(y_true, proba)
    if len(thresholds) == 0:
        return 0.5, None
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    best = int(np.argmax(f1[:-1]))
    high = None
    mask = precision[:-1] >= 0.8
    if mask.any():
        candidates = np.flatnonzero(mask)
        high = float(thresholds[candidates[np.argmax(recall[:-1][mask])]])
    return float(thresholds[best]), high


def presence_report(y_true: np.ndarray, proba: np.ndarray, threshold: float) -> dict:
    predicted = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "roc_auc": float(roc_auc_score(y_true, proba)),
        "pr_auc": float(average_precision_score(y_true, proba)),
        "positive_rate": float(np.mean(y_true)),
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "confusion_matrix": {"labels": ["no_viirs", "viirs"], "matrix": [[int(tn), int(fp)], [int(fn), int(tp)]]},
    }


def error_report(y_true: np.ndarray, pred: np.ndarray) -> dict:
    pred = np.clip(pred, 0, None)
    spearman = pd.Series(y_true).corr(pd.Series(pred), method="spearman")
    return {
        "mae": float(mean_absolute_error(y_true, pred)),
        "rmse": float(np.sqrt(np.mean((y_true - pred) ** 2))),
        "r2": float(r2_score(y_true, pred)),
        "spearman": float(spearman) if spearman == spearman else 0.0,
        "mean_truth": float(np.mean(y_true)),
        "mean_prediction": float(np.mean(pred)),
    }


def count_report(y_true: np.ndarray, pred: np.ndarray) -> dict:
    report = error_report(y_true, pred)
    report["poisson_deviance"] = float(mean_poisson_deviance(y_true, np.clip(pred, 1e-6, None)))
    return report


def region_ids(df: pd.DataFrame, region_deg: float) -> np.ndarray:
    lat = np.floor((df["cell_lat"].to_numpy(dtype=float) + 90.0) / region_deg).astype(np.int64)
    lon = np.floor((df["cell_lon"].to_numpy(dtype=float) + 180.0) / region_deg).astype(np.int64)
    return lat * (int(lon.max()) + 1) + lon


def monthly_report(
    df: pd.DataFrame,
    idx: np.ndarray,
    truth: np.ndarray,
    pred: np.ndarray,
    region_deg: float,
) -> dict:
    """Metrics at the level the calendar actually shows: region x month totals.

    Cell-level R2 is dominated by zero cells; a model can look fine there and
    still be biased by 30% in the monthly totals users see.
    """
    pred = np.clip(np.asarray(pred, dtype=float), 0, None)
    frame = pd.DataFrame(
        {
            "region": region_ids(df, region_deg)[idx],
            "month": df["date"].dt.to_period("M").astype(str).to_numpy()[idx],
            "truth": np.asarray(truth, dtype=float),
            "prediction": pred,
        }
    )
    cells = frame.groupby(["region", "month"], sort=False)[["truth", "prediction"]].sum()
    by_month = frame.groupby("month", sort=True)[["truth", "prediction"]].sum()
    ratio = cells["prediction"] / cells["truth"].clip(lower=1e-9)
    spearman = by_month["truth"].corr(by_month["prediction"], method="spearman")
    return {
        "sum_truth": float(cells["truth"].sum()),
        "sum_prediction": float(cells["prediction"].sum()),
        "sum_ratio": float(cells["prediction"].sum() / max(cells["truth"].sum(), 1e-9)),
        "region_months": int(len(cells)),
        "monthly_mae": float(np.mean(np.abs(cells["prediction"] - cells["truth"]))),
        "monthly_ratio_median": float(ratio.median()),
        "monthly_ratio_p10": float(ratio.quantile(0.10)),
        "monthly_ratio_p90": float(ratio.quantile(0.90)),
        "global_monthly_spearman": float(spearman) if spearman == spearman else 0.0,
        "global_monthly": {
            str(month): {"truth": float(row["truth"]), "prediction": float(row["prediction"])}
            for month, row in by_month.iterrows()
        },
    }


def bootstrap_ci(y_true: np.ndarray, pred: np.ndarray, metric, n: int = 200, seed: int = 0):
    """95% bootstrap interval for a metric, using the already-computed predictions."""
    rng = np.random.default_rng(seed)
    values = []
    size = len(y_true)
    for _ in range(n):
        pick = rng.integers(0, size, size)
        try:
            values.append(float(metric(y_true[pick], pred[pick])))
        except ValueError:
            continue
    if not values:
        return None
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


# --------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", nargs="+", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--split", choices=["time", "space", "year"], default="time")
    parser.add_argument("--block-days", type=int, default=14)
    parser.add_argument("--tile-deg", type=float, default=10.0)
    parser.add_argument("--test-year", type=int, default=None, help="Held-out year for --split year (default: latest).")
    parser.add_argument("--val-year", type=int, default=None, help="Validation year for --split year.")
    parser.add_argument("--region-deg", type=float, default=10.0, help="Region size for the monthly metrics.")
    parser.add_argument(
        "--refit-all",
        action="store_true",
        help="After evaluating on the held-out split, retrain the shipped models on every row.",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--grid", type=float, default=0.05, help="Grid size (degrees) used to build the cell-days.")
    parser.add_argument("--drop", nargs="*", default=[], help="Feature names to leave out.")
    args = parser.parse_args()

    unknown = sorted(set(args.drop) - set(ALL_FEATURES))
    if unknown:
        sys.exit(f"Unknown feature(s) in --drop: {unknown}")
    features = [f for f in ALL_FEATURES if f not in set(args.drop)]

    needed = set(features) | {
        "viirs_detections",
        "viirs_frp_mean",
        "modis_detections",
        "modis_frp_mean",
        "date",
        "cell_lat",
        "cell_lon",
        "year",
    }
    df = load(args.data, sorted(needed - {"year"}))
    missing = sorted(needed - set(df.columns))
    if missing:
        sys.exit(f"Columns missing from the data: {missing}")

    args.out.mkdir(parents=True, exist_ok=True)
    X = df[features]
    y_count = df["viirs_detections"].to_numpy(dtype=float)
    y_presence = (y_count > 0).astype(int)
    frp_all = df["viirs_frp_mean"].to_numpy(dtype=float)
    modis_detections = df["modis_detections"].to_numpy(dtype=float)
    modis_frp_mean = df["modis_frp_mean"].to_numpy(dtype=float)

    if args.split == "year":
        # The product predicts a year the model has never seen, so that is what
        # the headline evaluation must do. Fit on some years, test on one.
        years = np.sort(df["year"].unique())
        test_year = args.test_year if args.test_year is not None else int(years.max())
        if test_year not in set(int(y) for y in years):
            sys.exit(f"--test-year {test_year} is not in the data (years: {years.tolist()})")
        year_values = df["year"].to_numpy()
        test_idx = np.flatnonzero(year_values == test_year)
        val_year = args.val_year
        if val_year is not None:
            val_idx = np.flatnonzero(year_values == val_year)
            train_idx = np.flatnonzero(~np.isin(year_values, [test_year, val_year]))
            if len(train_idx) == 0:
                sys.exit("No training years left. Pass a different --test-year/--val-year.")
            validation_split = "year"
        else:
            # Default: keep every non-test year for training and hold out time
            # blocks of them for validation. With few observed years, spending a
            # whole year on validation costs too much training data.
            train_pool = np.flatnonzero(year_values != test_year)
            days = (df["date"].iloc[train_pool] - df["date"].min()).dt.days.to_numpy()
            blocks = (days // args.block_days).astype(np.int64)
            unique = np.random.default_rng(args.seed).permutation(np.unique(blocks))
            n_train = int(round(len(unique) * 0.8))
            if n_train == 0 or n_train == len(unique):
                sys.exit("Not enough distinct time blocks for a validation split.")
            sub_train = np.flatnonzero(np.isin(blocks, unique[:n_train]))
            sub_val = np.flatnonzero(np.isin(blocks, unique[n_train:]))
            train_idx = train_pool[sub_train]
            val_idx = train_pool[sub_val]
            validation_split = "time_blocks"
        print(
            f"year split: train={sorted(set(int(y) for y in year_values[train_idx]))} "
            f"val={sorted(set(int(y) for y in year_values[val_idx]))} test={[test_year]} "
            f"validation={validation_split}"
        )
    else:
        groups = group_ids(df, args.split, args.block_days, args.tile_deg)
        train_idx, val_idx, test_idx = split_indices(groups, args.seed)
        val_year = None
        validation_split = args.split

    for name, idx in (("validation", val_idx), ("test", test_idx)):
        if len(np.unique(y_presence[idx])) < 2:
            sys.exit(f"The {name} split has a single presence class. Use more data or other split settings.")
        print(
            f"  {name}: {df['date'].iloc[idx].min().date()} .. {df['date'].iloc[idx].max().date()}"
        )

    print(
        f"split={args.split} | rows train={len(train_idx):,} val={len(val_idx):,} test={len(test_idx):,} | "
        f"positive rate train={y_presence[train_idx].mean():.3f} val={y_presence[val_idx].mean():.3f} "
        f"test={y_presence[test_idx].mean():.3f}"
    )

    # ---- presence
    cls_val, cls_fitted = {}, {}
    for name, model in classifiers(features, args.seed).items():
        started = time.time()
        model.fit(X.iloc[train_idx], y_presence[train_idx])
        proba = model.predict_proba(X.iloc[val_idx])[:, 1]
        threshold, high = pick_threshold(y_presence[val_idx], proba)
        report = presence_report(y_presence[val_idx], proba, threshold)
        report["precision_ge_0_8_threshold"] = high
        report["seconds"] = round(time.time() - started, 1)
        cls_val[name], cls_fitted[name] = report, model
        print(f"[presence/val] {name:24s} ROC-AUC={report['roc_auc']:.4f} PR-AUC={report['pr_auc']:.4f} F1={report['f1']:.4f}")
    best_cls = max(cls_val, key=lambda key: cls_val[key]["pr_auc"])

    # Calibrate on validation. PR-AUC only ranks; the app multiplies P by counts,
    # so the probability itself must be meaningful (Brier score / reliability).
    proba_val = cls_fitted[best_cls].predict_proba(X.iloc[val_idx])[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(proba_val, y_presence[val_idx])
    proba_val_cal = calibrator.predict(proba_val)
    cal_threshold, _ = pick_threshold(y_presence[val_idx], proba_val_cal)
    presence_val_calibrated = presence_report(y_presence[val_idx], proba_val_cal, cal_threshold)
    presence_val_calibrated["brier"] = float(brier_score_loss(y_presence[val_idx], proba_val_cal))
    presence_val_calibrated["brier_uncalibrated"] = float(brier_score_loss(y_presence[val_idx], proba_val))

    proba_test = cls_fitted[best_cls].predict_proba(X.iloc[test_idx])[:, 1]
    proba_test_cal = calibrator.predict(proba_test)
    presence_test = presence_report(y_presence[test_idx], proba_test, cls_val[best_cls]["threshold"])
    presence_test_calibrated = presence_report(y_presence[test_idx], proba_test_cal, cal_threshold)
    presence_test_calibrated["brier"] = float(brier_score_loss(y_presence[test_idx], proba_test_cal))
    presence_test_calibrated["brier_uncalibrated"] = float(brier_score_loss(y_presence[test_idx], proba_test))
    presence_test_calibrated["ci95"] = {
        "pr_auc": bootstrap_ci(
            y_presence[test_idx], proba_test_cal, average_precision_score, seed=args.seed
        ),
        "roc_auc": bootstrap_ci(
            y_presence[test_idx], proba_test_cal, roc_auc_score, seed=args.seed
        ),
    }

    # ---- count
    reg_val, reg_fitted = {}, {}
    for name, model in regressors(features, args.seed).items():
        started = time.time()
        model.fit(X.iloc[train_idx], y_count[train_idx])
        report = count_report(y_count[val_idx], model.predict(X.iloc[val_idx]))
        report["seconds"] = round(time.time() - started, 1)
        reg_val[name], reg_fitted[name] = report, model
        print(
            f"[count/val]    {name:24s} deviance={report['poisson_deviance']:.4f} "
            f"MAE={report['mae']:.3f} R2={report['r2']:.3f}"
        )
    best_reg = min(reg_val, key=lambda key: reg_val[key]["poisson_deviance"])
    count_pred_test = np.clip(reg_fitted[best_reg].predict(X.iloc[test_idx]), 0, None)
    count_test = count_report(y_count[test_idx], count_pred_test)
    count_test["ci95"] = {
        "mae": bootstrap_ci(
            y_count[test_idx], count_pred_test, lambda y, p: np.mean(np.abs(y - p)), seed=args.seed
        ),
    }
    monthly_test = monthly_report(df, test_idx, y_count[test_idx], count_pred_test, args.region_deg)

    # ---- FRP (only where VIIRS fired)
    def positives(idx: np.ndarray) -> np.ndarray:
        return idx[(y_count[idx] > 0) & np.isfinite(frp_all[idx])]

    frp_train = positives(train_idx)
    frp_val_idx = positives(val_idx)
    frp_test_idx = positives(test_idx)
    frp_template = frp_regressor(args.seed)
    frp_model = clone(frp_template).fit(X.iloc[frp_train], np.log1p(frp_all[frp_train]))
    frp_val_pred = np.expm1(frp_model.predict(X.iloc[frp_val_idx]))
    frp_val = error_report(frp_all[frp_val_idx], frp_val_pred)
    frp_pred = np.expm1(frp_model.predict(X.iloc[frp_test_idx]))
    frp_test = error_report(frp_all[frp_test_idx], frp_pred)

    # ---- trivial baselines (scored on the test set, no tuning)
    ratio_count = y_count[train_idx].sum() / max(modis_detections[train_idx].sum(), 1.0)
    ratio_frp = np.nanmean(frp_all[frp_train]) / max(np.nanmean(modis_frp_mean[frp_train]), 1e-6)
    base_score = modis_detections[test_idx]
    count_baseline_pred = ratio_count * modis_detections[test_idx]
    frp_baseline_val = error_report(frp_all[frp_val_idx], ratio_frp * modis_frp_mean[frp_val_idx])
    frp_baseline_test = error_report(frp_all[frp_test_idx], ratio_frp * modis_frp_mean[frp_test_idx])
    baselines = {
        "presence_prevalence_pr_auc": float(np.mean(y_presence[test_idx])),
        "presence_modis_detections_roc_auc": float(roc_auc_score(y_presence[test_idx], base_score)),
        "presence_modis_detections_pr_auc": float(average_precision_score(y_presence[test_idx], base_score)),
        "count_ratio_times_modis": count_report(y_count[test_idx], count_baseline_pred),
        "count_ratio_monthly": monthly_report(
            df, test_idx, y_count[test_idx], count_baseline_pred, args.region_deg
        ),
        "frp_ratio_times_modis": frp_baseline_test,
        "frp_ratio_times_modis_validation": frp_baseline_val,
    }
    # Decide on validation, not test: the test set must not influence the product.
    frp_useful = bool(
        frp_val["r2"] > 0.05 and frp_val["mae"] < frp_baseline_val["mae"]
    )

    # ---- what does the winner rely on? (validation, train-only model)
    rng = np.random.default_rng(args.seed)
    sample = rng.choice(val_idx, size=min(20_000, len(val_idx)), replace=False)
    permutation = permutation_importance(
        cls_fitted[best_cls], X.iloc[sample], y_presence[sample],
        scoring="average_precision", n_repeats=3, random_state=args.seed, n_jobs=-1,
    )
    importance = pd.Series(permutation.importances_mean, index=features).sort_values(ascending=False)
    importance.to_csv(args.out / "feature_importance.csv", header=["pr_auc_drop"])

    # ---- refit the winners on train + validation and save
    # Reported metrics stay those of the held-out split above. Real numbers come
    # from the held-out year, so the shipped artifact may use every year; that
    # is the standard "evaluate honestly, then retrain on all data" step.
    trainval = np.concatenate([train_idx, val_idx])
    fit_idx = np.arange(len(df)) if args.refit_all else trainval
    final_presence = clone(cls_fitted[best_cls]).fit(X.iloc[fit_idx], y_presence[fit_idx])
    final_count = clone(reg_fitted[best_reg]).fit(X.iloc[fit_idx], y_count[fit_idx])
    frp_fit = positives(fit_idx)
    final_frp = clone(frp_template).fit(X.iloc[frp_fit], np.log1p(frp_all[frp_fit]))
    joblib.dump(final_presence, args.out / "model_presence.joblib")
    joblib.dump(final_count, args.out / "model_count.joblib")
    joblib.dump(final_frp, args.out / "model_frp.joblib")
    # Calibrator is fitted on the train-only model's validation probabilities.
    joblib.dump(calibrator, args.out / "calibrator_presence.joblib")

    # Pin every serialized artifact so predict.py can refuse a replaced or
    # corrupted file before joblib.load executes its embedded pickle payload.
    artifact_files = {
        "model_presence.joblib": args.out / "model_presence.joblib",
        "model_count.joblib": args.out / "model_count.joblib",
        "model_frp.joblib": args.out / "model_frp.joblib",
        "calibrator_presence.joblib": args.out / "calibrator_presence.joblib",
    }
    artifact_sha256 = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in artifact_files.items()
    }

    meta = {
        "presence_threshold": float(cal_threshold),
        "presence_threshold_uncalibrated": cls_val[best_cls]["threshold"],
        "precision_ge_0_8_threshold": cls_val[best_cls]["precision_ge_0_8_threshold"],
        "calibration": "isotonic",
        "presence_model": best_cls,
        "count_model": best_reg,
        "count_model_is_conditional": False,
        "frp_model": f"log1p ({type(frp_template).__name__})",
        "frp_useful": frp_useful,
        "grid_degrees": args.grid,
        "trained_on": [str(p) for p in args.data],
        "split": args.split,
        "test_year": int(test_year) if args.split == "year" else None,
        "validation_year": int(val_year) if val_year is not None else None,
        "validation_split": validation_split,
        "refit_on_all_rows": bool(args.refit_all),
        "refit_rows": int(len(fit_idx)),
        "dropped_features": sorted(args.drop),
        "artifact_sha256": artifact_sha256,
    }
    (args.out / "model_meta.json").write_text(json.dumps(meta, indent=2))
    (args.out / "feature_schema.json").write_text(
        json.dumps({"features": features, "grid_degrees": args.grid}, indent=2)
    )

    results = {
        "data": [str(p) for p in args.data],
        "rows": int(len(df)),
        "features": features,
        "dropped_features": sorted(args.drop),
        "split": {
            "type": args.split,
            "validation": validation_split,
            "test_year": int(test_year) if args.split == "year" else None,
            "validation_year": int(val_year) if val_year is not None else None,
            "block_days": args.block_days,
            "tile_deg": args.tile_deg,
            "seed": args.seed,
            "train_rows": int(len(train_idx)),
            "validation_rows": int(len(val_idx)),
            "test_rows": int(len(test_idx)),
        },
        "classification": cls_val,
        "classification_calibrated_validation": presence_val_calibrated,
        "regression": reg_val,
        "best": {"classification": best_cls, "regression": best_reg},
        "test": {
            "presence": presence_test,
            "presence_calibrated": presence_test_calibrated,
            "count": count_test,
            "monthly_count": monthly_test,
            "frp": frp_test,
            "frp_validation": frp_val,
            "baselines": baselines,
        },
        "frp_useful": frp_useful,
    }
    (args.out / "metrics.json").write_text(json.dumps(results, indent=2))
    pd.DataFrame(
        {
            "region": region_ids(df, args.region_deg)[test_idx],
            "month": df["date"].dt.to_period("M").astype(str).to_numpy()[test_idx],
            "truth": y_count[test_idx],
            "prediction": count_pred_test,
        }
    ).groupby(["region", "month"], sort=True).sum().reset_index().to_csv(
        args.out / "test_monthly.csv", index=False
    )

    print("\n=== TEST (winner, validation threshold) ===")
    print(
        f"presence {best_cls}: calibrated ROC-AUC={presence_test_calibrated['roc_auc']:.4f} "
        f"PR-AUC={presence_test_calibrated['pr_auc']:.4f} F1={presence_test_calibrated['f1']:.4f} "
        f"Brier={presence_test_calibrated['brier']:.4f}"
    )
    print(
        f"  baseline PR-AUC (modis_detections)={baselines['presence_modis_detections_pr_auc']:.4f}"
        f" prevalence={baselines['presence_prevalence_pr_auc']:.4f}"
    )
    print(
        f"count    {best_reg}: MAE={count_test['mae']:.3f} R2={count_test['r2']:.3f}"
        f"  | baseline MAE={baselines['count_ratio_times_modis']['mae']:.3f}"
    )
    print(
        f"  monthly sum ratio={monthly_test['sum_ratio']:.3f} "
        f"(baseline {baselines['count_ratio_monthly']['sum_ratio']:.3f}) "
        f"monthly MAE={monthly_test['monthly_mae']:.1f} "
        f"Spearman={monthly_test['global_monthly_spearman']:.3f}"
    )
    print(
        f"frp      {type(frp_template).__name__}: MAE={frp_test['mae']:.3f} R2={frp_test['r2']:.3f}"
        f"  | validation MAE={frp_val['mae']:.3f} "
        f"(baseline {frp_baseline_val['mae']:.3f}) | useful={frp_useful}"
    )
    print("\nTop features (permutation, validation):")
    print(importance.head(10).to_string())


if __name__ == "__main__":
    main()