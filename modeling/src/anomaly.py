"""Anomaly layer: how unusual is a month's burning activity for that place?

This is deliberately *not* a model. For every (region, month-of-year) it compares
the current year against the other years in the series and reports where it falls
in that distribution:

* ``median`` / ``mad`` / ``p10`` / ``p90`` of the other years,
* ``percentile`` rank of this year inside them,
* ``robust_z`` = (value - median) / (1.4826 * MAD),
* a ``severity`` class.

The comparison is leave-one-year-out, so a year is never part of its own baseline.
With only a handful of observed years the MAD is coarse; ``n_baseline_years`` is
written on every row so the consumer can decide how much to trust it.

Falling back, from most to least specific:
    region x month_of_year  ->  global month_of_year  ->  global

By default the baseline is built from *observed* years only (so a model estimate
cannot move the baseline it is judged against). ``--include-estimates`` pools them.

Usage:
    python src/anomaly.py --series outputs/harmonized.parquet \
        --out outputs/anomaly.parquet
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

LEVELS = (
    ("region_month", ["region", "month_of_year"]),
    ("global_month", ["month_of_year"]),
    ("global", []),
)


def add_baseline_stats(
    targets: pd.DataFrame, pool: pd.DataFrame, keys: list[str], min_years: int
) -> pd.DataFrame:
    """Leave-one-year-out stats aligned to ``targets``, for one specificity level.

    ``targets`` holds every year that must be scored (observed *and* backcast),
    while ``pool`` holds only the years allowed in the baseline. A target year
    that is absent from the pool simply uses the whole pool.
    """
    if keys:
        wide = pool.pivot_table(index=keys, columns="year", values="detections", aggfunc="sum")
    else:
        wide = pool.groupby("year")["detections"].sum().to_frame().T
    # No row for a region-month means "no burning detected there", which is a
    # real zero in a count series, not a missing value.
    wide = wide.fillna(0.0).sort_index(axis=1)
    years = wide.columns.to_numpy()
    mat = wide.to_numpy(dtype=float)

    if keys:
        if len(keys) == 1:
            row_index = pd.Index(wide.index)
            target_index = pd.Index(targets[keys[0]])
        else:
            row_index = wide.index
            target_index = pd.MultiIndex.from_frame(targets[keys])
        positions = row_index.get_indexer(target_index)
    else:
        positions = np.zeros(len(targets), dtype=np.int64)

    columns = ["baseline_n", "baseline_median", "baseline_mad", "baseline_p10", "baseline_p90", "percentile"]
    out = pd.DataFrame(np.nan, index=targets.index, columns=columns, dtype=float)
    target_year = targets["year"].to_numpy()
    target_value = targets["detections"].to_numpy(dtype=float)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        for year in np.unique(target_year):
            rows = np.flatnonzero(target_year == year)
            place = positions[rows]
            keep = place >= 0
            if not keep.any():
                continue
            block = mat[place[keep]].copy()
            drop = np.searchsorted(years, year)
            if drop < len(years) and years[drop] == year:
                block[:, drop] = np.nan
            n = (~np.isnan(block)).sum(axis=1)
            value = target_value[rows][keep]
            median = np.nanmedian(block, axis=1)
            mad = np.nanmedian(np.abs(block - median[:, None]), axis=1)
            p10 = np.nanpercentile(block, 10, axis=1)
            p90 = np.nanpercentile(block, 90, axis=1)
            at_or_below = np.nansum(block <= value[:, None], axis=1)
            percentile = at_or_below / np.maximum(n, 1)

            where = rows[keep]
            out.iloc[where, out.columns.get_loc("baseline_n")] = n
            out.iloc[where, out.columns.get_loc("baseline_median")] = median
            out.iloc[where, out.columns.get_loc("baseline_mad")] = mad
            out.iloc[where, out.columns.get_loc("baseline_p10")] = p10
            out.iloc[where, out.columns.get_loc("baseline_p90")] = p90
            out.iloc[where, out.columns.get_loc("percentile")] = percentile

    # A level with too few baseline years is not usable; let the next one win.
    out.loc[out["baseline_n"] < min_years, columns] = np.nan
    return out


def severity_from(robust_z: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    """Classify using the robust z, or the ratio when the baseline is flat."""
    out = np.full(len(robust_z), "normal", dtype=object)
    finite = np.isfinite(robust_z)
    z = np.where(finite, robust_z, 0.0)
    classes = np.select(
        [z <= -3.0, z <= -1.5, z < 1.5, z < 3.0],
        ["very_low", "low", "normal", "high"],
        default="very_high",
    )
    out[finite] = classes[finite]
    # Flat baseline (MAD == 0): the median is the only reference we have.
    flat = ~finite
    safe = np.where(np.isfinite(ratio), ratio, 1.0)
    out[flat & (safe <= 0.5)] = "very_low"
    out[flat & (safe > 0.5) & (safe < 0.8)] = "low"
    out[flat & (safe >= 0.8) & (safe <= 1.25)] = "normal"
    out[flat & (safe > 1.25) & (safe <= 2.0)] = "high"
    out[flat & (safe > 2.0)] = "very_high"
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--series", required=True, type=Path, help="Long series from harmonize.py.")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Also write a CSV next to the parquet.",
    )
    parser.add_argument(
        "--scale",
        default="viirs_harmonized",
        choices=["viirs_harmonized", "modis_raw"],
        help="Which series to score (default: viirs_harmonized).",
    )
    parser.add_argument(
        "--include-estimates",
        action="store_true",
        help="Also use backcast years in the baseline (default: observed years only).",
    )
    parser.add_argument(
        "--min-years",
        type=int,
        default=2,
        help="Minimum other years needed before this level is used (default 2).",
    )
    args = parser.parse_args()

    series = pd.read_parquet(args.series)
    series = series[series["scale"] == args.scale].copy()
    needed = {"region", "year", "month", "detections"}
    missing = sorted(needed - set(series.columns))
    if missing:
        raise SystemExit(f"{args.series}: missing columns {missing}")

    series["month_of_year"] = series.get("month_of_year", series["month"]).astype(int)
    series["year"] = series["year"].astype(int)
    series["detections"] = series["detections"].astype(float)
    if "is_estimate" not in series.columns:
        series["is_estimate"] = False

    pool = series if args.include_estimates else series[~series["is_estimate"].astype(bool)]
    pool = pool[["region", "month_of_year", "year", "detections"]]
    if pool["year"].nunique() < 2:
        raise SystemExit(
            f"Need at least 2 years in the baseline, got {pool['year'].nunique()}. "
            "Pass --include-estimates or add observed years."
        )

    stat_columns = ["baseline_n", "baseline_median", "baseline_mad", "baseline_p10", "baseline_p90", "percentile"]
    merged = series.copy()
    merged["baseline_level"] = "none"
    for level, keys in LEVELS:
        stats = add_baseline_stats(merged, pool, keys, args.min_years).add_suffix(f"__{level}")
        merged = pd.concat([merged, stats], axis=1)
        fresh = merged["baseline_level"].eq("none") & merged[f"baseline_n__{level}"].notna()
        merged.loc[fresh, "baseline_level"] = level

    # Coalesce from the most specific level to the least specific one.
    for column in stat_columns:
        merged[column] = np.nan
        for level, _ in LEVELS:
            merged[column] = merged[column].fillna(merged[f"{column}__{level}"])
    merged = merged.drop(columns=[c for c in merged.columns if "__" in c])
    merged["baseline_n"] = merged["baseline_n"].fillna(0).astype(int)

    scale = 1.4826 * merged["baseline_mad"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        robust_z = (merged["detections"].to_numpy(dtype=float) - merged["baseline_median"].to_numpy(dtype=float)) / scale
        ratio = merged["detections"].to_numpy(dtype=float) / merged["baseline_median"].to_numpy(dtype=float)
    # A flat baseline means MAD == 0; that is not an anomaly signal by itself.
    robust_z[~np.isfinite(robust_z)] = np.nan
    ratio = np.where(np.isfinite(ratio), ratio, np.nan)
    # Nothing burned in the baseline and nothing burned now: not an anomaly.
    calm = (merged["baseline_median"].to_numpy(dtype=float) <= 0) & (
        merged["detections"].to_numpy(dtype=float) <= 0
    )
    robust_z[calm] = 0.0
    ratio[calm] = 1.0
    merged["robust_z"] = robust_z
    merged["ratio_to_median"] = ratio
    merged["severity"] = severity_from(robust_z, ratio)
    # A baseline of exactly zero means this place normally does not burn in this
    # month. Any fire at all is a real signal, not a divide-by-zero artefact.
    new_fire = (merged["baseline_median"].to_numpy(dtype=float) <= 0) & (
        merged["detections"].to_numpy(dtype=float) > 0
    )
    merged.loc[new_fire, "severity"] = "very_high"
    merged.loc[new_fire, "percentile"] = 1.0
    merged.loc[merged["baseline_level"] == "none", "severity"] = "unknown"

    columns = [
        "scale",
        "region",
        "year",
        "month",
        "month_of_year",
        "detections",
        "baseline_level",
        "baseline_n",
        "baseline_median",
        "baseline_mad",
        "baseline_p10",
        "baseline_p90",
        "percentile",
        "robust_z",
        "ratio_to_median",
        "severity",
        "is_estimate",
        "coverage_corrected",
        "region_lat",
        "region_lon",
    ]
    for optional in ("region_lat", "region_lon", "is_estimate", "coverage_corrected"):
        if optional not in merged.columns:
            merged[optional] = np.nan
    merged = merged[columns].sort_values(["region", "year", "month"]).reset_index(drop=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(args.out, index=False)
    if args.csv:
        merged.to_csv(args.out.with_suffix(".csv"), index=False)

    scored = merged[merged["baseline_level"] != "none"]

    def finite(value) -> float | None:
        value = float(value)
        return value if np.isfinite(value) else None

    summary = {
        "rows": int(len(merged)),
        "scored_rows": int(len(scored)),
        "scale": args.scale,
        "baseline_years": sorted(int(y) for y in pool["year"].unique()),
        "baseline_source": "observed + estimates" if args.include_estimates else "observed only",
        "levels": merged["baseline_level"].value_counts().to_dict(),
        "baseline_n": merged["baseline_n"].value_counts().sort_index().to_dict(),
        "severity": merged["severity"].value_counts().to_dict(),
        "severity_by_year": {
            str(year): group["severity"].value_counts().to_dict()
            for year, group in merged.groupby("year")
        },
        "robust_z": {
            "median": finite(scored["robust_z"].median()) if len(scored) else None,
            "p10": finite(scored["robust_z"].quantile(0.10)) if len(scored) else None,
            "p90": finite(scored["robust_z"].quantile(0.90)) if len(scored) else None,
        },
        "note": (
            "Leave-one-year-out robust anomaly. With few baseline years the MAD is "
            "coarse: read baseline_n before trusting a severity class."
        ),
    }
    args.out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nAnomaly table: {args.out}")


if __name__ == "__main__":
    main()
