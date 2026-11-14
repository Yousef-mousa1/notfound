"""Clean FIRMS MODIS/VIIRS CSVs and aggregate them to a 0.05-degree cell-day table.

Output: one row per (cell, day) that has at least one MODIS detection, with
MODIS-derived features and VIIRS-derived targets. Cells where only VIIRS fired
are not in the table (the model cannot see them without MODIS), which is
reported in the cleaning summary.

Usage:
    python build_cellday.py --modis m.csv --viirs v.csv --year 2012 --out out.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

GRID = 0.05  # degrees, same grid as the harmonization pipeline

MODIS_COLUMNS = {
    "latitude": "lat",
    "longitude": "lon",
    "brightness": "bt_primary",
    "bright_t31": "bt_secondary",
    "scan": "scan",
    "track": "track",
    "acq_date": "date",
    "acq_time": "time",
    "satellite": "platform",
    "confidence": "confidence_raw",
    "frp": "frp",
    "daynight": "daynight",
    "type": "type",
}

VIIRS_COLUMNS = {
    "latitude": "lat",
    "longitude": "lon",
    "bright_ti4": "bt_primary",
    "bright_ti5": "bt_secondary",
    "scan": "scan",
    "track": "track",
    "acq_date": "date",
    "acq_time": "time",
    "satellite": "platform",
    "confidence": "confidence_raw",
    "frp": "frp",
    "daynight": "daynight",
    "type": "type",
}


def column_mapping(sensor: str, columns: list[str]) -> dict[str, str]:
    """Pick the source columns for a sensor.

    Some VIIRS exports keep the MODIS column names (``brightness``,
    ``bright_t31``) instead of ``bright_ti4``/``bright_ti5``. The band choice
    follows the header that is actually present, so both spellings load.
    """
    if sensor == "modis":
        return dict(MODIS_COLUMNS)
    mapping = dict(VIIRS_COLUMNS)
    if "bright_ti4" not in columns:
        mapping["brightness"] = "bt_primary"
        mapping["bright_t31"] = "bt_secondary"
        mapping.pop("bright_ti4", None)
        mapping.pop("bright_ti5", None)
    return mapping


def read_firms(path: Path, sensor: str) -> tuple[pd.DataFrame, dict]:
    """Read one FIRMS CSV and apply the cleaning rules for that sensor."""
    raw = pd.read_csv(path, low_memory=False)
    mapping = column_mapping(sensor, list(raw.columns))
    missing = [c for c in mapping if c not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")

    df = raw[list(mapping)].rename(columns=mapping).copy()
    n_raw = len(df)
    report = {"file": path.name, "sensor": sensor, "rows_raw": int(n_raw)}

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["frp"] = pd.to_numeric(df["frp"], errors="coerce")
    df["bt_primary"] = pd.to_numeric(df["bt_primary"], errors="coerce")
    df["bt_secondary"] = pd.to_numeric(df["bt_secondary"], errors="coerce")
    df["scan"] = pd.to_numeric(df["scan"], errors="coerce")
    df["track"] = pd.to_numeric(df["track"], errors="coerce")
    df["type"] = pd.to_numeric(df["type"], errors="coerce")

    # Confidence: MODIS is 0-100, VIIRS is l/n/h.
    if sensor == "viirs":
        conf = df["confidence_raw"].astype(str).str.strip().str.lower()
        conf = conf.replace({"low": "l", "nominal": "n", "high": "h"})
        df["confidence_class"] = conf.map({"l": "low", "n": "nominal", "h": "high"})
        df["confidence_raw"] = conf.map({"l": 20, "n": 60, "h": 90})
    else:
        df["confidence_raw"] = pd.to_numeric(df["confidence_raw"], errors="coerce")
        df["confidence_class"] = pd.cut(
            df["confidence_raw"],
            bins=[-1, 30, 80, 101],
            labels=["low", "nominal", "high"],
        ).astype("object")

    # Timestamp: date + HHMM (UTC), 0000-2359.
    time = df["time"].fillna(0).astype(int).clip(0, 2359).astype(str).str.zfill(4)
    df["datetime_utc"] = pd.to_datetime(
        df["date"].astype(str) + " " + time.str[:2] + ":" + time.str[2:],
        format="%Y-%m-%d %H:%M",
        errors="coerce",
    )
    df["hour"] = df["datetime_utc"].dt.hour + df["datetime_utc"].dt.minute / 60

    steps = {}
    # 1. Non-vegetation fires (type != 0) are kept out of the modelling set.
    before = len(df)
    df = df[df["type"].fillna(0) == 0]
    steps["drop_non_vegetation"] = before - len(df)

    # 2. Coordinates are mandatory.
    before = len(df)
    df = df[df["lat"].between(-90, 90) & df["lon"].between(-180, 180)]
    steps["drop_invalid_coordinates"] = before - len(df)

    # 3. Timestamp is mandatory.
    before = len(df)
    df = df[df["datetime_utc"].notna()]
    steps["drop_invalid_timestamp"] = before - len(df)

    # 4. Exact duplicates (same pixel/time/sensor reported twice).
    before = len(df)
    keys = ["lat", "lon", "datetime_utc", "platform", "frp", "bt_primary"]
    df = df.drop_duplicates(subset=keys)
    steps["drop_exact_duplicates"] = before - len(df)

    # 5. FRP is the physical quantity the model learns; negative or absurd
    #    values are data errors. 10,000 MW is far above any real fire.
    before = len(df)
    df = df[df["frp"].between(0, 10_000)]
    steps["drop_invalid_frp"] = before - len(df)

    df["date"] = df["datetime_utc"].dt.normalize()

    report["rows_clean"] = int(len(df))
    report["steps"] = steps
    report["confidence_distribution"] = (
        df["confidence_class"].value_counts(dropna=False).astype(int).to_dict()
    )
    report["frp_median_mw"] = float(df["frp"].median()) if len(df) else None
    return df, report


def add_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the 0.05-degree grid cell and its centre coordinates."""
    df = df.copy()
    df["cell_row"] = np.floor(df["lat"] / GRID).astype(int)
    df["cell_col"] = np.floor(df["lon"] / GRID).astype(int)
    df["cell_id"] = df["cell_row"].map(lambda r: f"r{r:04d}") + df["cell_col"].map(
        lambda c: f"c{c:04d}"
    )
    df["cell_lat"] = (df["cell_row"] + 0.5) * GRID
    df["cell_lon"] = (df["cell_col"] + 0.5) * GRID
    return df


def aggregate(df: pd.DataFrame, sensor: str) -> pd.DataFrame:
    """Aggregate detections to one row per (cell, day)."""
    grouped = df.groupby(["cell_id", "cell_row", "cell_col", "date"], observed=True)
    agg = grouped.agg(
        detections=("frp", "size"),
        frp_mean=("frp", "mean"),
        frp_max=("frp", "max"),
        frp_sum=("frp", "sum"),
        frp_std=("frp", "std"),
        bt_primary_mean=("bt_primary", "mean"),
        bt_primary_max=("bt_primary", "max"),
        bt_secondary_mean=("bt_secondary", "mean"),
        bt_secondary_max=("bt_secondary", "max"),
        scan_mean=("scan", "mean"),
        track_mean=("track", "mean"),
        hour_mean=("hour", "mean"),
        night_share=("daynight", lambda s: float((s == "N").mean())),
        platforms=("platform", "nunique"),
    ).reset_index()

    conf = (
        pd.crosstab([df["cell_id"], df["date"]], df["confidence_class"])
        .reindex(columns=["low", "nominal", "high"], fill_value=0)
        .reset_index()
        .rename(
            columns={"low": "conf_low", "nominal": "conf_nominal", "high": "conf_high"}
        )
    )
    agg = agg.merge(conf, on=["cell_id", "date"], how="left")

    prefix = "modis" if sensor == "modis" else "viirs"
    keep = ("cell_id", "cell_row", "cell_col", "date")
    agg = agg.rename(
        columns={c: f"{prefix}_{c}" for c in agg.columns if c not in keep}
    )
    return agg


def add_neighbour_features(cell_days: pd.DataFrame) -> pd.DataFrame:
    """Add 3x3 neighbourhood and previous-day context for the MODIS counts.

    Only past information is used (same day neighbours and the previous day),
    so the features stay usable for a real-time application.
    """
    df = cell_days.sort_values("date").copy()
    rows = df["cell_row"]
    cols = df["cell_col"]

    def shift_neighbour(offset_r: int, offset_c: int) -> pd.Series:
        lookup = df.set_index(["cell_row", "cell_col", "date"])["modis_detections"]
        idx = pd.MultiIndex.from_arrays([rows + offset_r, cols + offset_c, df["date"]])
        return pd.Series(lookup.reindex(idx).to_numpy(), index=df.index).fillna(0)

    neighbours = [
        shift_neighbour(dr, dc)
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        if not (dr == 0 and dc == 0)
    ]
    df["modis_neighbour_count"] = np.sum(neighbours, axis=0)

    counts = df.set_index(["cell_id", "date"])["modis_detections"]
    for lag, name in ((1, "prev1"), (2, "prev2"), (3, "prev3")):
        idx = pd.MultiIndex.from_arrays(
            [df["cell_id"], df["date"] - pd.Timedelta(days=lag)]
        )
        df[f"modis_{name}_count"] = pd.Series(
            counts.reindex(idx).to_numpy(), index=df.index
        ).fillna(0)
    df["modis_prev3_mean"] = df[["modis_prev1_count", "modis_prev2_count", "modis_prev3_count"]].mean(axis=1)
    return df


def build(modis_path: Path, viirs_path: Path, year: int) -> tuple[pd.DataFrame, dict]:
    modis, modis_report = read_firms(modis_path, "modis")
    viirs, viirs_report = read_firms(viirs_path, "viirs")
    modis = add_cells(modis)
    viirs = add_cells(viirs)

    modis_cell_days = aggregate(modis, "modis")
    viirs_cell_days = aggregate(viirs, "viirs")

    # Grid coordinates come from the MODIS side; the VIIRS copy is redundant.
    viirs_cell_days = viirs_cell_days.drop(columns=["cell_row", "cell_col"])
    table = modis_cell_days.merge(viirs_cell_days, on=["cell_id", "date"], how="left")
    target_columns = [c for c in table.columns if c.startswith("viirs_")]
    table[target_columns] = table[target_columns].fillna(0)

    table = add_neighbour_features(table)
    table["cell_lat"] = (table["cell_row"] + 0.5) * GRID
    table["cell_lon"] = (table["cell_col"] + 0.5) * GRID
    table["year"] = year
    table["doy"] = table["date"].dt.day_of_year
    table["doy_sin"] = np.sin(2 * np.pi * table["doy"] / 365.25)
    table["doy_cos"] = np.cos(2 * np.pi * table["doy"] / 365.25)
    table["hour_sin"] = np.sin(2 * np.pi * table["modis_hour_mean"] / 24)
    table["hour_cos"] = np.cos(2 * np.pi * table["modis_hour_mean"] / 24)

    viirs_only = len(viirs_cell_days) - len(
        viirs_cell_days.merge(modis_cell_days[["cell_id", "date"]], on=["cell_id", "date"], how="inner")
    )
    summary = {
        "year": year,
        "grid_degrees": GRID,
        "modis": modis_report,
        "viirs": viirs_report,
        "cell_days_modis": int(len(modis_cell_days)),
        "cell_days_viirs": int(len(viirs_cell_days)),
        "cell_days_joined": int(len(table)),
        "viirs_only_cell_days_excluded": int(viirs_only),
        "positive_rate": float((table["viirs_detections"] > 0).mean()),
    }
    return table, summary


def main() -> None:
    global GRID
    parser = argparse.ArgumentParser()
    parser.add_argument("--modis", required=True, type=Path)
    parser.add_argument("--viirs", required=True, type=Path)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--grid", type=float, default=GRID, help="Grid size in degrees (default 0.05).")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--summary", type=Path, default=None)
    args = parser.parse_args()

    GRID = args.grid
    table, summary = build(args.modis, args.viirs, args.year)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(args.out, index=False)
    summary_path = args.summary or args.out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
