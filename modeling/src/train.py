"""Train MODIS -> VIIRS models on 0.05-degree cell-days.

Two tasks are learned from the same MODIS features:
  * presence  : does VIIRS see at least one detection in this cell-day?
  * intensity : how many VIIRS detections (and mean FRP) when it does.

The split is grouped by date (80/20 of days) so a cell from the same day cannot
appear in both train and test, which would inflate every score.

Usage:
    python train.py --data data/processed/cellday_2015.parquet data/processed/cellday_2025.parquet \
        --out outputs/run_2015_2025
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_curve,
    r2_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, MinMaxScaler, StandardScaler

import lightgbm as lgb
import xgboost as xgb

FEATURES = [
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

# Columns that are strongly right-skewed (counts and FRP); log1p stabilises them
# for models that assume roughly symmetric inputs.
SKEWED = [f for f in FEATURES if f.endswith(("_detections", "_count", "_mean", "_max", "_sum", "_std"))]


def load(paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_parquet(path) for path in paths]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def make_preprocessor(kind: str) -> ColumnTransformer:
    """Return a preprocessing transformer for the chosen variant."""
    if kind == "none":
        return ColumnTransformer([("keep", "passthrough", FEATURES)])
    if kind == "standard":
        return ColumnTransformer(
            [("scale", Pipeline([("impute", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), FEATURES)]
        )
    if kind == "minmax":
        return ColumnTransformer(
            [("scale", Pipeline([("impute", SimpleImputer(strategy="median")), ("scaler", MinMaxScaler())]), FEATURES)]
        )
    if kind == "log1p_standard":
        skewed = [f for f in SKEWED if f in FEATURES]
        rest = [f for f in FEATURES if f not in skewed]
        return ColumnTransformer(
            [
                ("log", Pipeline([("impute", SimpleImputer(strategy="median")), ("log", FunctionTransformer(np.log1p)), ("scale", StandardScaler())]), skewed),
                ("plain", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), rest),
            ]
        )
    raise ValueError(kind)


def classifier_zoo(prep_kind: str) -> dict[str, Pipeline]:
    return {
        "logistic_regression": Pipeline(
            [("prep", make_preprocessor("standard" if prep_kind == "none" else prep_kind)), ("model", LogisticRegression(max_iter=2000))]
        ),
        "random_forest": Pipeline(
            [
                ("prep", make_preprocessor(prep_kind)),
                ("model", RandomForestClassifier(n_estimators=300, min_samples_leaf=5, n_jobs=-1, random_state=0)),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            [
                ("prep", make_preprocessor(prep_kind)),
                ("model", HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0)),
            ]
        ),
        "lightgbm": Pipeline(
            [
                ("prep", make_preprocessor(prep_kind)),
                ("model", lgb.LGBMClassifier(n_estimators=500, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=0)),
            ]
        ),
        "xgboost": Pipeline(
            [
                ("prep", make_preprocessor(prep_kind)),
                ("model", xgb.XGBClassifier(n_estimators=500, learning_rate=0.05, max_depth=6, subsample=0.9, colsample_bytree=0.9, eval_metric="logloss", random_state=0)),
            ]
        ),
    }


def regressor_zoo(prep_kind: str) -> dict[str, Pipeline]:
    return {
        "poisson_regression": Pipeline(
            [("prep", make_preprocessor("standard" if prep_kind == "none" else prep_kind)), ("model", PoissonRegressor(max_iter=500))]
        ),
        "random_forest": Pipeline(
            [
                ("prep", make_preprocessor(prep_kind)),
                ("model", RandomForestRegressor(n_estimators=300, min_samples_leaf=3, n_jobs=-1, random_state=0)),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            [
                ("prep", make_preprocessor(prep_kind)),
                ("model", HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.08, random_state=0)),
            ]
        ),
        "lightgbm": Pipeline(
            [
                ("prep", make_preprocessor(prep_kind)),
                ("model", lgb.LGBMRegressor(objective="poisson", n_estimators=500, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=0)),
            ]
        ),
        "xgboost": Pipeline(
            [
                ("prep", make_preprocessor(prep_kind)),
                ("model", xgb.XGBRegressor(objective="count:poisson", n_estimators=500, learning_rate=0.05, max_depth=6, subsample=0.9, colsample_bytree=0.9, random_state=0)),
            ]
        ),
    }


def classification_metrics(y_true: np.ndarray, proba: np.ndarray) -> dict:
    precision, recall, thresholds = precision_recall_curve(y_true, proba)
    f1 = np.divide(2 * precision * recall, precision + recall, out=np.zeros_like(precision), where=(precision + recall) > 0)
    best = int(np.nanargmax(f1[:-1])) if len(thresholds) else 0
    threshold = float(thresholds[best]) if len(thresholds) else 0.5
    predicted = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()

    fpr, tpr, _ = roc_curve(y_true, proba)
    # Operating point that keeps precision >= 0.8 (useful for "report only confident fires").
    high_precision_threshold = 0.5
    mask = precision[:-1] >= 0.8
    if mask.any():
        idx = np.argmax(recall[:-1][mask])
        high_precision_threshold = float(thresholds[np.flatnonzero(mask)[idx]])

    return {
        "roc_auc": float(roc_auc_score(y_true, proba)),
        "pr_auc": float(average_precision_score(y_true, proba)),
        "best_f1": float(f1[best]) if len(thresholds) else 0.0,
        "best_threshold": threshold,
        "precision_at_best_f1": float(precision[best]) if len(thresholds) else 0.0,
        "recall_at_best_f1": float(recall[best]) if len(thresholds) else 0.0,
        "f1_at_0_5": float(f1_score(y_true, (proba >= 0.5).astype(int))),
        "confusion_matrix": {
            "labels": ["no_viirs", "viirs"],
            "matrix": [[int(tn), int(fp)], [int(fn), int(tp)]],
        },
        "precision_ge_0_8_threshold": high_precision_threshold,
        "roc": {"fpr": fpr.tolist(), "tpr": tpr.tolist()},
    }


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    y_pred = np.clip(y_pred, 0, None)
    spearman = float(pd.Series(y_true).corr(pd.Series(y_pred), method="spearman"))
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)),
        "spearman": spearman,
        "mean_truth": float(np.mean(y_true)),
        "mean_prediction": float(np.mean(y_pred)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", nargs="+", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--grid", type=float, default=0.05, help="Grid size used to build the cell-days.")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    df = load(args.data)
    X = df[FEATURES]
    y_count = df["viirs_detections"].to_numpy(dtype=float)
    y_presence = (y_count > 0).astype(int)
    groups = df["date"].dt.strftime("%Y-%m-%d")

    splitter = GroupShuffleSplit(n_splits=1, test_size=args.test_size, random_state=args.seed)
    train_idx, test_idx = next(splitter.split(X, y_presence, groups))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y_presence[train_idx], y_presence[test_idx]
    c_train, c_test = y_count[train_idx], y_count[test_idx]
    print(
        f"rows train={len(train_idx)} test={len(test_idx)} | days train={groups.iloc[train_idx].nunique()} "
        f"test={groups.iloc[test_idx].nunique()} | positive rate train={y_train.mean():.3f} test={y_test.mean():.3f}"
    )

    results = {
        "data": [str(p) for p in args.data],
        "rows": int(len(df)),
        "features": FEATURES,
        "split": {
            "type": "GroupShuffleSplit by date",
            "test_size": args.test_size,
            "seed": args.seed,
            "train_rows": int(len(train_idx)),
            "test_rows": int(len(test_idx)),
        },
        "classification": {},
        "regression": {},
    }

    prep_kinds = ["none", "standard", "minmax", "log1p_standard"]
    best = {"cls": (-1.0, None, None), "reg": (np.inf, None, None)}

    for prep_kind in prep_kinds:
        for name, model in classifier_zoo(prep_kind).items():
            key = f"{name}__{prep_kind}"
            started = time.time()
            model.fit(X_train, y_train)
            proba = model.predict_proba(X_test)[:, 1]
            metrics = classification_metrics(y_test, proba)
            metrics["seconds"] = round(time.time() - started, 1)
            results["classification"][key] = metrics
            print(f"[cls] {key:45s} ROC-AUC={metrics['roc_auc']:.4f} PR-AUC={metrics['pr_auc']:.4f} F1={metrics['best_f1']:.4f}")
            if metrics["pr_auc"] > best["cls"][0]:
                best["cls"] = (metrics["pr_auc"], key, model)

        for name, model in regressor_zoo(prep_kind).items():
            key = f"{name}__{prep_kind}"
            started = time.time()
            model.fit(X_train, c_train)
            pred = np.clip(model.predict(X_test), 0, None)
            metrics = regression_metrics(c_test, pred)
            metrics["seconds"] = round(time.time() - started, 1)
            results["regression"][key] = metrics
            print(f"[reg] {key:45s} MAE={metrics['mae']:.3f} R2={metrics['r2']:.3f} rho={metrics['spearman']:.3f}")
            if metrics["mae"] < best["reg"][0]:
                best["reg"] = (metrics["mae"], key, model)

    # FRP model: only where VIIRS actually fired, otherwise "mean FRP" is 0 by construction.
    frp_mask_train = c_train > 0
    frp_mask_test = c_test > 0
    frp_train = df["viirs_frp_mean"].to_numpy()[train_idx][frp_mask_train]
    frp_model = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=31, verbose=-1, random_state=0)
    frp_model.fit(X_train[frp_mask_train], np.log1p(frp_train))
    frp_pred = np.clip(np.expm1(frp_model.predict(X_test[frp_mask_test])), 0, None)
    results["frp"] = regression_metrics(
        df["viirs_frp_mean"].to_numpy()[test_idx][frp_mask_test], frp_pred
    )
    results["frp"]["target"] = "log1p(viirs_frp_mean)" 
    print(f"[frp] lightgbm MAE={results['frp']['mae']:.3f} R2={results['frp']['r2']:.3f}")

    results["best"] = {"classification": best["cls"][1], "regression": best["reg"][1]}

    # Persist the winners plus the feature schema needed at inference time.
    joblib.dump(best["cls"][2], args.out / "model_presence.joblib")
    joblib.dump(best["reg"][2], args.out / "model_count.joblib")
    joblib.dump(frp_model, args.out / "model_frp.joblib")
    best_cls_metrics = results["classification"][best["cls"][1]]
    (args.out / "model_meta.json").write_text(
        json.dumps(
            {
                "presence_threshold": best_cls_metrics["best_threshold"],
                "precision_ge_0_8_threshold": best_cls_metrics["precision_ge_0_8_threshold"],
                "presence_model": best["cls"][1],
                "count_model": best["reg"][1],
                "frp_model": "lightgbm log1p",
                "grid_degrees": args.grid,
                "trained_on": [str(p) for p in args.data],
            },
            indent=2,
        )
    )
    (args.out / "feature_schema.json").write_text(
        json.dumps({"features": FEATURES, "grid_degrees": args.grid}, indent=2)
    )
    (args.out / "metrics.json").write_text(json.dumps(results, indent=2))

    # Feature importance of the best classifier when the model exposes it.
    cls_model = best["cls"][2].named_steps["model"]
    if hasattr(cls_model, "feature_importances_"):
        importance = pd.Series(cls_model.feature_importances_, index=FEATURES).sort_values(ascending=False)
        importance.to_csv(args.out / "feature_importance.csv", header=["importance"])
        print(importance.head(10).to_string())

    print(json.dumps(results["best"], indent=2))


if __name__ == "__main__":
    main()
