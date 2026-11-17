"""Build one harmonized burning-activity series from observed and backcast years.

Two scales are written side by side:

* ``viirs_harmonized``: observed VIIRS where it exists, and the MODIS -> VIIRS
  backcast (from ``predict.py``) multiplied by the per-block/month correction
  ``k`` where it does not. ``k`` fixes the fact that the model only sees
  cell-days where MODIS fired, while the calendar needs all VIIRS hotspots.
* ``modis_raw``: the MODIS detection counts. This needs no model at all and is
  the safest backbone for a 20-year series (MODIS is observed in every year).

Output is long format (one row per region x month x scale), ready for the API.

Usage:
    python src/harmonize.py \\
        --observed data/processed/cellday_2013.parquet data/processed/cellday_2024.parquet \\
        --backcast outputs/viirs_like_2005.csv outputs/viirs_like_2006.csv \\
        --coverage data/processed/cellday_2013.coverage.parquet \\
        --out outputs/harmonized.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def region_index(lat: np.ndarray, lon: np.ndarray, region_deg: float) -> tuple[np.ndarray, int]:
    """Global region id for a grid of ``region_deg`` degrees, plus the lon count."""
    n_lon = int(round(360.0 / region_deg))
    lat_i = np.floor((np.asarray(lat, dtype=float) + 90.0) / region_deg).astype(np.int64)
    lon_i = np.floor((np.asarray(lon, dtype=float) + 180.0) / region_deg).astype(np.int64)
    lat_i = np.clip(lat_i, 0, int(round(180.0 / region_deg)) - 1)
    lon_i = np.clip(lon_i, 0, n_lon - 1)
    return lat_i * n_lon + lon_i, n_lon


def region_centres(ids: np.ndarray, region_deg: float, n_lon: int) -> tuple[np.ndarray, np.ndarray]:
    lat_i = ids // n_lon
    lon_i = ids % n_lon
    lat = (lat_i + 0.5) * region_deg - 90.0
    lon = (lon_i + 0.5) * region_deg - 180.0
    return lat, lon


def read_any(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def load_observed(paths: list[Path], region_deg: float) -> pd.DataFrame:
    frames = []
    for path in paths:
        df = pd.read_parquet(
            path,
            columns=["cell_lat", "cell_lon", "date", "viirs_detections", "modis_detections"],
        )
        df["date"] = pd.to_datetime(df["date"])
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["region"], n_lon = region_index(df["cell_lat"].to_numpy(), df["cell_lon"].to_numpy(), region_deg)
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["viirs_raw"] = df["viirs_detections"].astype(float)
    df["viirs_harmonized"] = df["viirs_raw"]
    df["is_estimate"] = False
    df["scale_factor"] = 1.0
    df["model"] = "observed"
    return df


def load_backcast(paths: list[Path], region_deg: float) -> pd.DataFrame:
    frames = []
    for path in paths:
        df = read_any(path)
        if "viirs_like_detections" not in df.columns:
            raise SystemExit(f"{path}: missing viirs_like_detections (rerun predict.py)")
        df["date"] = pd.to_datetime(df["date"])
        frames.append(
            df[
                [
                    "cell_lat",
                    "cell_lon",
                    "date",
                    "modis_detections",
                    "viirs_like_detections",
                    *(["model"] if "model" in df.columns else []),
                ]
            ].copy()
        )
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["region"], _ = region_index(df["cell_lat"].to_numpy(), df["cell_lon"].to_numpy(), region_deg)
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["viirs_raw"] = df["viirs_like_detections"].astype(float)
    df["is_estimate"] = True
    df["scale_factor"] = 1.0
    if "model" not in df.columns:
        df["model"] = "backcast"
    return df


def load_coverage(paths: list[Path], region_deg: float) -> dict:
    """Coverage correction ``k`` with a zoom-out fallback chain.

    ``k`` = all VIIRS detections / VIIRS detections inside the MODIS cell-day
    table. It is needed because the table starts from MODIS detections, so a
    real VIIRS hotspot in a cell-day with no MODIS detection is invisible.

    Levels, from most to least specific:
      * ``region_month_year`` - exact, used for observed years.
      * ``region_month``      - pooled over observed years, used for backcasts.
      * ``global_month``      - same calendar month everywhere.
      * ``global``            - single number.
    """
    frames = []
    for path in paths:
        df = read_any(path)
        needed = {"br", "bc", "month", "year", "v_full", "v_in"}
        if not needed.issubset(df.columns):
            raise SystemExit(f"{path}: expected columns {sorted(needed)}")
        df = df.copy()
        # 1-degree block centres -> region id
        df["region"], _ = region_index(
            df["br"].to_numpy() + 0.5, df["bc"].to_numpy() + 0.5, region_deg
        )
        frames.append(df)
    if not frames:
        return {
            "exact": pd.DataFrame(columns=["region", "month", "year", "k_exact"]),
            "pooled": pd.DataFrame(columns=["region", "month", "k_region_month"]),
            "month": pd.DataFrame(columns=["month", "k_month"]),
            "global_k": 1.0,
        }
    cov = pd.concat(frames, ignore_index=True)

    def ratio(grouped: pd.DataFrame) -> np.ndarray:
        return np.where(
            grouped["v_in"] > 0,
            grouped["v_full"] / grouped["v_in"].clip(lower=1e-9),
            np.nan,
        )

    exact = (
        cov.groupby(["region", "month", "year"], sort=False)
        .agg(v_full=("v_full", "sum"), v_in=("v_in", "sum"))
        .reset_index()
    )
    exact["k_exact"] = ratio(exact)

    pooled = (
        cov.groupby(["region", "month"], sort=False)
        .agg(v_full=("v_full", "sum"), v_in=("v_in", "sum"), years=("year", "nunique"))
        .reset_index()
    )
    pooled["k_region_month"] = ratio(pooled)

    by_month = cov.groupby("month").agg(v_full=("v_full", "sum"), v_in=("v_in", "sum")).reset_index()
    by_month["k_month"] = ratio(by_month)

    return {
        "exact": exact[["region", "month", "year", "k_exact", "v_full", "v_in"]].rename(
            columns={"v_full": "v_full_exact", "v_in": "v_in_exact"}
        ),
        "pooled": pooled[["region", "month", "k_region_month"]],
        "month": by_month[["month", "k_month"]],
        "global_k": float(cov["v_full"].sum() / max(cov["v_in"].sum(), 1e-9)),
        "rows": int(len(cov)),
    }


def resolve_k(df: pd.DataFrame, coverage: dict) -> tuple[np.ndarray, np.ndarray]:
    """Attach the best available ``k`` to each (region, month, year) row."""
    out = df[["region", "year", "month"]].copy()
    out = out.merge(coverage["exact"], on=["region", "month", "year"], how="left")
    out = out.merge(coverage["pooled"], on=["region", "month"], how="left")
    out = out.merge(coverage["month"], on="month", how="left")
    global_k = float(coverage["global_k"])
    k = (
        out["k_exact"]
        .fillna(out["k_region_month"])
        .fillna(out["k_month"])
        .fillna(global_k)
        .clip(lower=1.0, upper=50.0)
    )
    baseline = np.select(
        [out["k_exact"].notna(), out["k_region_month"].notna(), out["k_month"].notna()],
        ["region_month_year", "region_month", "global_month"],
        default="global",
    )
    return k.to_numpy(), baseline


def aggregate(df: pd.DataFrame, value: str) -> pd.DataFrame:
    out = (
        df.groupby(["region", "year", "month"], sort=False)
        .agg(detections=(value, "sum"), cell_days=(value, "size"))
        .reset_index()
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--observed", nargs="*", type=Path, default=[], help="Cell-day parquets with VIIRS.")
    parser.add_argument("--backcast", nargs="*", type=Path, default=[], help="predict.py outputs (CSV/parquet).")
    parser.add_argument(
        "--coverage",
        nargs="*",
        type=Path,
        default=[],
        help="build_cellday.py .coverage.parquet files (one per observed year).",
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Also write a CSV next to the parquet (for tools that cannot read parquet).",
    )
    parser.add_argument("--region-deg", type=float, default=1.0, help="Region size in degrees (default 1.0).")
    parser.add_argument(
        "--rel-error",
        type=float,
        default=0.35,
        help="Relative band for backcast estimates (heuristic; shown as low/high).",
    )
    parser.add_argument(
        "--no-rake-k",
        action="store_true",
        help=(
            "Disable raking of backcast k to the observed global ratio. By default "
            "backcast k is rescaled so that the weighted mean matches the global "
            "VIIRS/MODIS ratio; per-region-month structure is preserved."
        ),
    )
    args = parser.parse_args()

    if not args.observed and not args.backcast:
        raise SystemExit("Pass at least one --observed or --backcast input.")

    observed = load_observed(args.observed, args.region_deg)
    backcast = load_backcast(args.backcast, args.region_deg)
    coverage = load_coverage(args.coverage, args.region_deg) if args.coverage else {}

    # A backcast must never be mixed into a year VIIRS actually observed: the
    # calendar would show two different numbers for the same region and month.
    overlap = set(observed["year"].unique()) & set(backcast["year"].unique())
    dropped_backcast_years: list[int] = []
    if overlap:
        dropped_backcast_years = sorted(int(y) for y in overlap)
        print(
            "[warn] years present in BOTH --observed and --backcast: "
            f"{dropped_backcast_years}. Dropping the backcast for them "
            "(observed VIIRS always wins).",
            file=sys.stderr,
        )

    rows = []
    k_rake_factor = 1.0

    if not observed.empty:
        # Observed VIIRS in the table is still conditional on MODIS firing, so it
        # needs the same coverage correction. Without it, observed years would
        # look ~4x lower than backcast years and the 2013->2005 step would be an
        # artefact of the sensor, not of fire activity.
        obs = aggregate(observed, "viirs_harmonized")
        if coverage:
            k, baseline = resolve_k(obs, coverage)
        else:
            k, baseline = np.ones(len(obs)), np.array(["none"] * len(obs))
        obs["viirs_raw_in_table"] = obs["detections"]
        obs["detections"] = obs["detections"] * k
        obs["scale"] = "viirs_harmonized"
        obs["is_estimate"] = False
        obs["coverage_corrected"] = True
        obs["scale_factor"] = k
        obs["baseline"] = baseline
        obs["model"] = "observed"
        rows.append(obs)

        modis_obs = aggregate(observed, "modis_detections")
        modis_obs["viirs_raw_in_table"] = np.nan
        modis_obs["scale"] = "modis_raw"
        modis_obs["is_estimate"] = False
        modis_obs["coverage_corrected"] = False
        modis_obs["scale_factor"] = 1.0
        modis_obs["baseline"] = "observed"
        modis_obs["model"] = "observed"
        rows.append(modis_obs)

    if not backcast.empty:
        if dropped_backcast_years:
            backcast = backcast[~backcast["year"].isin(dropped_backcast_years)]
        if not coverage:
            raise SystemExit(
                "Backcast needs --coverage (from build_cellday.py) to correct for VIIRS-only cell-days."
            )
        bc = aggregate(backcast, "viirs_raw")
        k, baseline = resolve_k(bc, coverage)
        k_rake_factor = 1.0
        if not args.no_rake_k:
            # Pooled per-region-month k is unbiased for the observed spatial mix,
            # but a backcast year has a different mix. Its weighted mean can be
            # ~30% above the observed global ratio, which would make the
            # backcast years look artificially more active. Rake k so that
            # sum(detections * k) == global_k * sum(detections), while preserving
            # all relative region/month structure.
            raw = bc["detections"].to_numpy(dtype=float)
            weighted = float(np.sum(raw * k))
            if weighted > 0 and coverage.get("global_k"):
                k_rake_factor = float(coverage["global_k"] * raw.sum() / weighted)
                k = k * k_rake_factor
                baseline = np.where(
                    baseline == "region_month", "region_month_raked", baseline
                )
        bc["viirs_raw_in_table"] = np.nan
        bc["detections"] = bc["detections"] * k
        bc["scale"] = "viirs_harmonized"
        bc["is_estimate"] = True
        bc["coverage_corrected"] = True
        bc["scale_factor"] = k
        bc["baseline"] = baseline
        bc["model"] = "modis_to_viirs_backcast"
        rows.append(bc)

        modis_bc = aggregate(backcast, "modis_detections")
        modis_bc["viirs_raw_in_table"] = np.nan
        modis_bc["scale"] = "modis_raw"
        modis_bc["is_estimate"] = False
        modis_bc["coverage_corrected"] = False
        modis_bc["scale_factor"] = 1.0
        modis_bc["baseline"] = "observed"
        modis_bc["model"] = "observed"
        rows.append(modis_bc)

    series = pd.concat(rows, ignore_index=True)
    # A band only makes sense where a correction factor was applied.
    band = series["coverage_corrected"].to_numpy(dtype=bool)
    series["low"] = np.where(band, series["detections"] * (1.0 - args.rel_error), series["detections"])
    series["high"] = np.where(band, series["detections"] * (1.0 + args.rel_error), series["detections"])
    series["month_of_year"] = series["month"]
    ids = series["region"].to_numpy(dtype=np.int64)
    n_lon = int(round(360.0 / args.region_deg))
    lat, lon = region_centres(ids, args.region_deg, n_lon)
    series["region_lat"] = np.round(lat, 4)
    series["region_lon"] = np.round(lon, 4)
    series["region_deg"] = args.region_deg
    series = series.sort_values(["scale", "region", "year", "month"]).reset_index(drop=True)
    columns = [
        "scale",
        "region",
        "region_lat",
        "region_lon",
        "region_deg",
        "year",
        "month",
        "month_of_year",
        "detections",
        "viirs_raw_in_table",
        "low",
        "high",
        "cell_days",
        "is_estimate",
        "coverage_corrected",
        "scale_factor",
        "baseline",
        "model",
    ]
    series = series[columns]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    series.to_parquet(args.out, index=False)
    if args.csv:
        series.to_csv(args.out.with_suffix(".csv"), index=False)

    wide = series.pivot_table(
        index=["region", "region_lat", "region_lon", "year", "month"],
        columns="scale",
        values="detections",
        aggfunc="sum",
    ).reset_index()
    wide.columns.name = None
    wide.to_parquet(args.out.with_name(args.out.stem + "_wide.parquet"), index=False)

    baseline_counts = (
        series.loc[series["coverage_corrected"], "baseline"].value_counts().to_dict()
        if len(series)
        else {}
    )
    summary = {
        "rows": int(len(series)),
        "region_deg": args.region_deg,
        "years": sorted(int(y) for y in series["year"].unique()),
        "observed_years": sorted(int(y) for y in observed["year"].unique()) if not observed.empty else [],
        "backcast_years": sorted(int(y) for y in backcast["year"].unique()) if not backcast.empty else [],
        "backcast_years_dropped_as_observed": dropped_backcast_years,
        "global_k": float(coverage["global_k"]) if coverage else None,
        "k_backcast_rake_factor": k_rake_factor,
        "k_baseline_usage": baseline_counts,
        "totals": {
            scale: {
                "observed": float(group.loc[~group["is_estimate"], "detections"].sum()),
                "estimated": float(group.loc[group["is_estimate"], "detections"].sum()),
            }
            for scale, group in series.groupby("scale")
        },
        "totals_by_year": {
            str(year): {
                scale: float(group["detections"].sum())
                for scale, group in series[series["year"] == year].groupby("scale")
            }
            for year in sorted(series["year"].unique())
        },
        "note": (
            "viirs_harmonized = (observed VIIRS in the MODIS table OR MODIS->VIIRS "
            "backcast) * k, where k restores VIIRS-only cell-days. modis_raw is "
            "uncorrected MODIS detections. low/high are a heuristic "
            f"+/-{args.rel_error:.0%} band on corrected rows, not a fitted interval. "
            "Backcast k is raked to the observed global ratio; use --no-rake-k "
            "to see the unmodified estimate."
        ),
    }
    args.out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nSeries: {args.out}\nWide:   {args.out.with_name(args.out.stem + '_wide.parquet')}")


if __name__ == "__main__":
    main()
