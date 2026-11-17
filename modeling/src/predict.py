"""Apply a trained MODIS -> VIIRS model to a year where VIIRS does not exist.

The output is a VIIRS-equivalent *estimate* (backcast). It is flagged in every
row (`is_estimate = True`) and never replaces an observation.

The grid size is read from the model (`feature_schema.json`), so a model trained
on one grid is never applied to another by mistake.

Usage:
    python predict.py --modis data/raw/modis_2005 --model outputs/run_2013 \
        --out outputs/viirs_like_2005.csv
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from build_cellday import (
    add_cell_centres,
    add_neighbour_features,
    add_time_features,
    expand_paths,
    load_cell_days,
)


def _load_verified(model_dir: Path, name: str, pins: dict[str, str]):
    """Load a joblib artifact only after verifying its pinned SHA-256.

    ``joblib.load`` is pickle-based and executes code on load. A digest recorded
    at training time lets us refuse a replaced or corrupted artifact instead of
    executing it. This is defense-in-depth, not a full trust boundary: anyone
    able to write the model directory can also rewrite both file and pin.
    """
    path = model_dir / name
    expected = pins.get(name)
    if not expected:
        sys.exit(
            f"Refusing to load {name}: no SHA-256 pin in model_meta.json. "
            "Re-train with a current train.py or add the pin explicitly."
        )
    if not path.is_file():
        sys.exit(f"Refusing to load {name}: artifact is missing: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        sys.exit(
            f"Refusing to load {name}: SHA-256 mismatch "
            f"(expected {expected}, got {actual}). Artifact may be corrupt or tampered with."
        )
    return joblib.load(path)


def build_modis_features(paths: list[Path], grid: float) -> tuple[pd.DataFrame, dict]:
    files = expand_paths(paths)
    table, report = load_cell_days(files, "modis", grid)
    table = add_neighbour_features(table)
    table = add_cell_centres(table, grid, with_id=True)
    table = add_time_features(table)
    return table, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modis", required=True, nargs="+", type=Path, help="CSV file(s) or folder(s)")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--year", type=int, default=None, help="Ignored (kept for old commands).")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument(
        "--match-positive-rate",
        type=float,
        default=None,
        help="Calibrate the threshold so the predicted positive share equals this rate "
        "(use the positive rate observed in the training data).",
    )
    args = parser.parse_args()

    schema = json.loads((args.model / "feature_schema.json").read_text())
    meta = json.loads((args.model / "model_meta.json").read_text())
    grid = float(schema.get("grid_degrees", 0.05))
    threshold = args.threshold if args.threshold is not None else meta["presence_threshold"]
    frp_useful = bool(meta.get("frp_useful", True))
    print(f"model grid = {grid} degrees")

    pins = meta.get("artifact_sha256") or {}
    presence_model = _load_verified(args.model, "model_presence.joblib", pins)
    count_model = _load_verified(args.model, "model_count.joblib", pins)
    frp_model = _load_verified(args.model, "model_frp.joblib", pins)
    calibrator_path = args.model / "calibrator_presence.joblib"
    calibrator = (
        _load_verified(args.model, "calibrator_presence.joblib", pins)
        if calibrator_path.exists()
        else None
    )

    table, report = build_modis_features(args.modis, grid)
    missing = [f for f in schema["features"] if f not in table.columns]
    if missing:
        sys.exit(f"Features missing from the MODIS table: {missing}")
    X = table[schema["features"]]

    proba_raw = presence_model.predict_proba(X)[:, 1]
    proba = calibrator.predict(proba_raw) if calibrator is not None else proba_raw
    if args.match_positive_rate is not None:
        # Domain shift: a target year can fire far more (or less) than the training
        # years, and tree models saturate. This only moves the classification
        # threshold; it never scales the expected counts (that is what K does).
        threshold = float(np.quantile(proba, 1 - args.match_positive_rate))
    raw_counts = np.clip(count_model.predict(X), 0, None)
    # train.py fits the count model on every row (zeros included), so it already
    # is E[VIIRS | X]. Multiplying or zeroing it again would bias the totals.
    counts = proba * raw_counts if meta.get("count_model_is_conditional", False) else raw_counts

    output = pd.DataFrame(
        {
            "cell_id": table["cell_id"],
            "date": table["date"].dt.strftime("%Y-%m-%d"),
            "cell_lat": table["cell_lat"].round(4),
            "cell_lon": table["cell_lon"].round(4),
            "modis_detections": table["modis_detections"].astype(int),
            "viirs_like_presence_prob": np.round(proba, 4),
            "viirs_like_presence": (proba >= threshold).astype(int),
            "viirs_like_detections": np.round(counts, 3),
        }
    )
    if frp_useful:
        # Only written when the FRP model beat the simple ratio baseline in training.
        frp = np.clip(np.expm1(frp_model.predict(X)), 0, None)
        output["viirs_like_frp_mean"] = np.round(frp, 3)
        output["viirs_like_frp_expected"] = np.round(proba * frp, 3)
        # A conditional FRP mean is meaningless where no fire is expected; the
        # soft expectation above keeps the totals unbiased.
        output.loc[output["viirs_like_presence"] == 0, "viirs_like_frp_mean"] = 0.0
    output["threshold"] = round(float(threshold), 4)
    output["positive_rate_matched"] = args.match_positive_rate
    output["model"] = meta["presence_model"]
    output["year"] = table["year"].to_numpy()
    output["is_estimate"] = True

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.suffix.lower() == ".parquet":
        output.to_parquet(args.out, index=False)
    else:
        output.to_csv(args.out, index=False)

    summary = {
        "years": sorted(int(y) for y in output["year"].unique()),
        "files": report["files"],
        "grid_degrees": grid,
        "cell_days": int(len(output)),
        "expected_viirs_cell_days": int(output["viirs_like_presence"].sum()),
        "expected_viirs_detections": round(float(output["viirs_like_detections"].sum()), 1),
        "expected_viirs_detections_in_classified_cells": round(
            float(output.loc[output["viirs_like_presence"] == 1, "viirs_like_detections"].sum()), 1
        ),
        "threshold": round(float(threshold), 4),
        "calibrated": calibrator is not None,
        "count_model_is_conditional": bool(meta.get("count_model_is_conditional", False)),
        "model": meta["presence_model"],
        "frp_written": frp_useful,
        "cleaning": report["steps"],
        "note": (
            "Conditional VIIRS-equivalent estimate from MODIS (only cell-days where "
            "MODIS fired). Multiply totals by the per-region k from the coverage "
            "table to reach the unconditional VIIRS scale."
        ),
    }
    args.out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()