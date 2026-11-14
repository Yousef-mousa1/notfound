"""Apply a trained MODIS -> VIIRS model to a year where VIIRS does not exist.

The output is a VIIRS-equivalent *estimate* (backcast). It is flagged in every
row (`is_estimate = True`) and never replaces an observation.

Usage:
    python predict.py --modis modis_2005_Benin.csv --year 2005 --model outputs/run_2015_2025 \
        --out outputs/viirs_like_2005_Benin.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from build_cellday import add_cells, add_neighbour_features, aggregate, read_firms


def build_modis_features(path: Path, year: int) -> tuple[pd.DataFrame, dict]:
    modis, report = read_firms(path, "modis")
    modis = add_cells(modis)
    cell_days = aggregate(modis, "modis")
    table = add_neighbour_features(cell_days)
    table["cell_lat"] = (table["cell_row"] + 0.5) * 0.05
    table["cell_lon"] = (table["cell_col"] + 0.5) * 0.05
    table["year"] = year
    table["doy"] = table["date"].dt.day_of_year
    table["doy_sin"] = np.sin(2 * np.pi * table["doy"] / 365.25)
    table["doy_cos"] = np.cos(2 * np.pi * table["doy"] / 365.25)
    table["hour_sin"] = np.sin(2 * np.pi * table["modis_hour_mean"] / 24)
    table["hour_cos"] = np.cos(2 * np.pi * table["modis_hour_mean"] / 24)
    return table, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modis", required=True, type=Path)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument(
        "--match-positive-rate",
        type=float,
        default=None,
        help="Calibrate the threshold so the predicted positive share equals this rate "
        "(use the positive rate observed in the training year).",
    )
    args = parser.parse_args()

    schema = json.loads((args.model / "feature_schema.json").read_text())
    meta = json.loads((args.model / "model_meta.json").read_text())
    threshold = args.threshold if args.threshold is not None else meta["presence_threshold"]

    presence_model = joblib.load(args.model / "model_presence.joblib")
    count_model = joblib.load(args.model / "model_count.joblib")
    frp_model = joblib.load(args.model / "model_frp.joblib")

    table, report = build_modis_features(args.modis, args.year)
    X = table[schema["features"]]

    proba = presence_model.predict_proba(X)[:, 1]
    if args.match_positive_rate is not None:
        # Domain shift: a target year can fire far more (or less) than the training
        # year, and tree models saturate. Matching the positive rate keeps the
        # ranking but restores the expected share of cell-days with VIIRS.
        threshold = float(np.quantile(proba, 1 - args.match_positive_rate))
    counts = np.clip(count_model.predict(X), 0, None)
    frp = np.clip(np.expm1(frp_model.predict(X)), 0, None)

    output = pd.DataFrame(
        {
            "cell_id": table["cell_id"],
            "date": table["date"].dt.strftime("%Y-%m-%d"),
            "cell_lat": table["cell_lat"].round(4),
            "cell_lon": table["cell_lon"].round(4),
            "modis_detections": table["modis_detections"].astype(int),
            "viirs_like_presence_prob": np.round(proba, 4),
            "viirs_like_presence": (proba >= threshold).astype(int),
            "viirs_like_detections": np.round(counts, 2),
            "viirs_like_frp_mean": np.round(frp, 3),
            "threshold": round(float(threshold), 4),
            "positive_rate_matched": args.match_positive_rate,
            "model": meta["presence_model"],
            "year": args.year,
            "is_estimate": True,
        }
    )
    output.loc[output["viirs_like_presence"] == 0, ["viirs_like_detections", "viirs_like_frp_mean"]] = 0.0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.out, index=False)

    summary = {
        "year": args.year,
        "file": args.modis.name,
        "cell_days": int(len(output)),
        "expected_viirs_cell_days": int(output["viirs_like_presence"].sum()),
        "expected_viirs_detections": round(float(output["viirs_like_detections"].sum()), 1),
        "threshold": round(float(threshold), 4),
        "model": meta["presence_model"],
        "cleaning": report["steps"],
        "note": "VIIRS-equivalent estimate from MODIS; VIIRS did not observe this year.",
    }
    (args.out.with_suffix(".summary.json")).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
