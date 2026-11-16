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
import json
import sys
import time
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.metrics import (
    average_precision_score,
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


def load(paths: list[Path]) -> pd.DataFrame:
    df = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ----------------------------------------------------------------------------- split
def group_ids(df: pd.DataFrame, mode: str, block_days: int, tile_deg: float) -> np.ndarray:
    if mode == "time":
        days = (df["date"] - df["date"].min()).dt.days.to_numpy()
        return (days // block_days).astype(np.int64)
    lat_tile = np.floor((df["cell_lat"].to_numpy(dtype=float) + 90.0) / tile_deg).astype(np.int64)
    lon_tile = np.floor((df["cell_lon"].to_numpy(dtype=float) + 180.0) / tile_deg).astype(np.int64)
    return lat_tile * 10_000 + lon_tile


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
    return {
        "logistic_regression": Pipeline(
            [("prep", linear_preprocessor(features)), ("model", LogisticRegression(max_iter=2000))]
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=seed),
        "lightgbm": lgb.LGBMClassifier(n_estimators=500, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=seed),
        "xgboost": xgb.XGBClassifier(
            n_estimators=500, learning_rate=0.05, max_depth=6, subsample=0.9, colsample_bytree=0.9,
            eval_metric="logloss", random_state=seed,
        ),
    }


def regressors(features: list[str], seed: int) -> dict:
    return {
        "poisson_regression": Pipeline(
            [("prep", linear_preprocessor(features)), ("model", PoissonRegressor(max_iter=500))]
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            loss="poisson", max_iter=300, learning_rate=0.08, random_state=seed
        ),
        "lightgbm": lgb.LGBMRegressor(
            objective="poisson", n_estimators=500, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=seed
        ),
        "xgboost": xgb.XGBRegressor(
            objective="count:poisson", n_estimators=500, learning_rate=0.05, max_depth=6,
            subsample=0.9, colsample_bytree=0.9, random_state=seed,
        ),
    }


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


# --------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", nargs="+", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--split", choices=["time", "space"], default="time")
    parser.add_argument("--block-days", type=int, default=14)
    parser.add_argument("--tile-deg", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--grid", type=float, default=0.05, help="Grid size (degrees) used to build the cell-days.")
    parser.add_argument("--drop", nargs="*", default=[], help="Feature names to leave out.")
    args = parser.parse_args()

    unknown = sorted(set(args.drop) - set(ALL_FEATURES))
    if unknown:
        sys.exit(f"Unknown feature(s) in --drop: {unknown}")
    features = [f for f in ALL_FEATURES if f not in set(args.drop)]

    df = load(args.data)
    needed = set(features) | {"viirs_detections", "viirs_frp_mean", "modis_detections", "modis_frp_mean", "date"}
    if args.split == "space":
        needed |= {"cell_lat", "cell_lon"}
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

    groups = group_ids(df, args.split, args.block_days, args.tile_deg)
    train_idx, val_idx, test_idx = split_indices(groups, args.seed)
    for name, idx in (("validation", val_idx), ("test", test_idx)):
        if len(np.unique(y_presence[idx])) < 2:
            sys.exit(f"The {name} split has a single presence class. Use more data or other split settings.")

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

    proba_test = cls_fitted[best_cls].predict_proba(X.iloc[test_idx])[:, 1]
    presence_test = presence_report(y_presence[test_idx], proba_test, cls_val[best_cls]["threshold"])

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
    count_test = count_report(y_count[test_idx], reg_fitted[best_reg].predict(X.iloc[test_idx]))

    # ---- FRP (only where VIIRS fired)
    def positives(idx: np.ndarray) -> np.ndarray:
        return idx[(y_count[idx] > 0) & np.isfinite(frp_all[idx])]

    frp_train, frp_test_idx = positives(train_idx), positives(test_idx)
    frp_template = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=args.seed)
    frp_model = clone(frp_template).fit(X.iloc[frp_train], np.log1p(frp_all[frp_train]))
    frp_pred = np.expm1(frp_model.predict(X.iloc[frp_test_idx]))
    frp_test = error_report(frp_all[frp_test_idx], frp_pred)

    # ---- trivial baselines (scored on the test set, no tuning)
    ratio_count = y_count[train_idx].sum() / max(modis_detections[train_idx].sum(), 1.0)
    ratio_frp = np.nanmean(frp_all[frp_train]) / max(np.nanmean(modis_frp_mean[frp_train]), 1e-6)
    base_score = modis_detections[test_idx]
    baselines = {
        "presence_prevalence_pr_auc": float(np.mean(y_presence[test_idx])),
        "presence_modis_detections_roc_auc": float(roc_auc_score(y_presence[test_idx], base_score)),
        "presence_modis_detections_pr_auc": float(average_precision_score(y_presence[test_idx], base_score)),
        "count_ratio_times_modis": count_report(y_count[test_idx], ratio_count * modis_detections[test_idx]),
        "frp_ratio_times_modis": error_report(frp_all[frp_test_idx], ratio_frp * modis_frp_mean[frp_test_idx]),
    }
    frp_useful = bool(
        frp_test["r2"] > 0.05 and frp_test["mae"] < baselines["frp_ratio_times_modis"]["mae"]
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
    trainval = np.concatenate([train_idx, val_idx])
    final_presence = clone(cls_fitted[best_cls]).fit(X.iloc[trainval], y_presence[trainval])
    final_count = clone(reg_fitted[best_reg]).fit(X.iloc[trainval], y_count[trainval])
    frp_trainval = positives(trainval)
    final_frp = clone(frp_template).fit(X.iloc[frp_trainval], np.log1p(frp_all[frp_trainval]))
    joblib.dump(final_presence, args.out / "model_presence.joblib")
    joblib.dump(final_count, args.out / "model_count.joblib")
    joblib.dump(final_frp, args.out / "model_frp.joblib")

    meta = {
        "presence_threshold": cls_val[best_cls]["threshold"],
        "precision_ge_0_8_threshold": cls_val[best_cls]["precision_ge_0_8_threshold"],
        "presence_model": best_cls,
        "count_model": best_reg,
        "frp_model": "lightgbm log1p",
        "frp_useful": frp_useful,
        "grid_degrees": args.grid,
        "trained_on": [str(p) for p in args.data],
        "split": args.split,
        "dropped_features": sorted(args.drop),
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
            "block_days": args.block_days,
            "tile_deg": args.tile_deg,
            "seed": args.seed,
            "train_rows": int(len(train_idx)),
            "validation_rows": int(len(val_idx)),
            "test_rows": int(len(test_idx)),
        },
        "classification": cls_val,
        "regression": reg_val,
        "best": {"classification": best_cls, "regression": best_reg},
        "test": {"presence": presence_test, "count": count_test, "frp": frp_test, "baselines": baselines},
        "frp_useful": frp_useful,
    }
    (args.out / "metrics.json").write_text(json.dumps(results, indent=2))

    print("\n=== TEST (winner, validation threshold) ===")
    print(
        f"presence {best_cls}: ROC-AUC={presence_test['roc_auc']:.4f} PR-AUC={presence_test['pr_auc']:.4f} "
        f"F1={presence_test['f1']:.4f}  | baseline PR-AUC (modis_detections)={baselines['presence_modis_detections_pr_auc']:.4f}"
        f" prevalence={baselines['presence_prevalence_pr_auc']:.4f}"
    )
    print(
        f"count    {best_reg}: MAE={count_test['mae']:.3f} R2={count_test['r2']:.3f}"
        f"  | baseline MAE={baselines['count_ratio_times_modis']['mae']:.3f}"
    )
    print(
        f"frp      lightgbm: MAE={frp_test['mae']:.3f} R2={frp_test['r2']:.3f}"
        f"  | baseline MAE={baselines['frp_ratio_times_modis']['mae']:.3f} | useful={frp_useful}"
    )
    print("\nTop features (permutation, validation):")
    print(importance.head(10).to_string())


if __name__ == "__main__":
    main()