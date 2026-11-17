"""Clean FIRMS MODIS/VIIRS CSVs and aggregate them to a cell-day table.

Output: one row per (cell, day) that has at least one MODIS detection, with
MODIS-derived features and VIIRS-derived targets. VIIRS-only cell-days are not in
the table (the model cannot see them without MODIS); their number and the share of
VIIRS detections that fall outside the table are reported.

Memory: every country file is cleaned and reduced to partial cell-day statistics
(counts, sums, maxima) on its own, then the partials are merged. Raw detections
are never all in memory at once. Duplicates across country files (a border pixel)
are not removed; they are rare.

Other points
  * --modis / --viirs accept CSV files or folders (one file per country).
  * MODIS files whose (year, country) has no VIIRS file are skipped.
  * Confidence is read as numbers (0-100) or letters (l/n/h), detected from the values.
    Classes follow FIRMS: low 0-29, nominal 30-79, high 80-100.
  * FRP outside [0, 10000] is set to NaN, the detection itself is still counted.
  * The hour of day uses a circular mean.
  * Coverage checks: MODIS days outside the VIIRS date range, and 1-degree blocks
    with plenty of MODIS but no VIIRS at all, are dropped (--keep-uncovered disables).

Usage:
    python build_cellday.py --modis data/raw/modis_2025 --viirs data/raw/viirs_2025 \
        --out data/processed/cellday_2025.parquet
    # quick test on a few countries (names as in the file names)
    python build_cellday.py --modis data/raw/modis_2025 --viirs data/raw/viirs_2025 \
        --countries Benin Nigeria Ghana Togo Cameroon --out data/processed/cellday_test.parquet
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_GRID = 0.05  # degrees
KEYS = ["cell_row", "cell_col", "date"]
DEDUP_KEYS = ["lat", "lon", "datetime_utc", "platform", "frp", "bt_primary"]
NAME_RE = re.compile(r"_(\d{4})_(.+)\.csv$")
MAX_COLUMNS = {"frp_max", "bt1_max", "bt2_max"}

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


# ------------------------------------------------------------------------- files
def normalise_country(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def file_key(path: Path) -> tuple[str, str] | None:
    """(year, country) from a FIRMS archive name such as viirs-snpp_2025_Benin.csv."""
    match = NAME_RE.search(path.name)
    if not match:
        return None
    return match.group(1), normalise_country(match.group(2))


def expand_paths(paths: list[Path]) -> list[Path]:
    """CSV files given directly, plus every CSV found inside the given folders."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                sorted(
                    p
                    for p in path.rglob("*.csv")
                    if not p.name.startswith(".") and "__MACOSX" not in p.parts
                )
            )
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(path)
    if not files:
        raise FileNotFoundError("No CSV files found in: " + ", ".join(str(p) for p in paths))
    return files


# ----------------------------------------------------------------------- cleaning
def column_mapping(sensor: str, columns: list[str]) -> dict[str, str]:
    """Pick the source columns for a sensor.

    Some VIIRS exports keep the MODIS column names (``brightness``,
    ``bright_t31``) instead of ``bright_ti4``/``bright_ti5``.
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


def parse_confidence(raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return (numeric score or NaN, class low/nominal/high) for either format.

    FIRMS exports confidence as numbers (0-100, MODIS) or letters (l/n/h, VIIRS 375 m).
    The format is detected from the values themselves.
    """
    numeric = pd.to_numeric(raw, errors="coerce")
    from_numbers = pd.cut(
        numeric, bins=[0, 30, 80, 101], right=False, labels=["low", "nominal", "high"]
    ).astype("object")

    letters = raw.astype(str).str.strip().str.lower()
    letters = letters.replace({"low": "l", "nominal": "n", "high": "h"})
    from_letters = letters.map({"l": "low", "n": "nominal", "h": "high"})

    return numeric, from_numbers.where(numeric.notna(), from_letters)


STEP_NAMES = (
    "drop_non_vegetation",
    "drop_invalid_coordinates",
    "drop_invalid_timestamp",
    "drop_exact_duplicates",
    "drop_outside_viirs_coverage",
    "frp_set_to_nan",
)


def read_firms(path: Path, sensor: str) -> tuple[pd.DataFrame, dict]:
    """Read one FIRMS CSV and apply the cleaning rules for that sensor."""
    header = pd.read_csv(path, nrows=0).columns.tolist()
    mapping = column_mapping(sensor, header)
    missing = [c for c in mapping if c not in header]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")

    raw = pd.read_csv(path, usecols=list(mapping), dtype={"confidence": str}, low_memory=False)
    report = {
        "file": path.name,
        "sensor": sensor,
        "rows_raw": int(len(raw)),
        "rows_clean": 0,
        "steps": {name: 0 for name in STEP_NAMES},
        "confidence_classes": {},
    }
    if raw.empty:
        return pd.DataFrame(), report

    df = raw.rename(columns=mapping)
    for column in ("lat", "lon", "frp", "bt_primary", "bt_secondary", "scan", "track", "type"):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["confidence_raw"], df["confidence_class"] = parse_confidence(df["confidence_raw"])

    # Timestamp: date + HHMM (UTC), 0000-2359.
    hhmm = pd.to_numeric(df["time"], errors="coerce").fillna(0).astype(int).clip(0, 2359)
    hhmm = hhmm.astype(str).str.zfill(4)
    df["datetime_utc"] = pd.to_datetime(
        df["date"].astype(str) + " " + hhmm.str[:2] + ":" + hhmm.str[2:],
        format="%Y-%m-%d %H:%M",
        errors="coerce",
    )
    df["hour"] = df["datetime_utc"].dt.hour + df["datetime_utc"].dt.minute / 60

    steps = report["steps"]
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
    df = df.drop_duplicates(subset=DEDUP_KEYS)
    steps["drop_exact_duplicates"] = before - len(df)

    # 5. FRP outside [0, 10000] MW is a retrieval error. The detection stays (it is
    #    still a detection for the counts); only its FRP value is ignored.
    df = df.copy()
    bad_frp = ~df["frp"].between(0, 10_000)
    steps["frp_set_to_nan"] = int(bad_frp.sum())
    df.loc[bad_frp, "frp"] = np.nan

    df["date"] = df["datetime_utc"].dt.normalize()
    report["rows_clean"] = int(len(df))
    report["confidence_classes"] = {
        str(k): int(v) for k, v in df["confidence_class"].value_counts(dropna=False).items()
    }
    return df, report


def add_cells(df: pd.DataFrame, grid: float) -> pd.DataFrame:
    """Attach the integer grid cell (row, col) for a grid size in degrees."""
    df["cell_row"] = np.floor(df["lat"] / grid).astype(np.int32)
    df["cell_col"] = np.floor(df["lon"] / grid).astype(np.int32)
    return df


# ------------------------------------------------------------------- aggregation
def safe_div(numerator, denominator) -> np.ndarray:
    num = np.asarray(numerator, dtype="float64")
    den = np.asarray(denominator, dtype="float64")
    return np.divide(num, den, out=np.full(num.shape, np.nan), where=den > 0)


def partial_aggregate(df: pd.DataFrame, slim: bool) -> pd.DataFrame:
    """Per (cell, day) partial statistics of ONE file. Partials can be merged by sum/max.

    ``slim`` keeps only what the VIIRS targets need (counts, FRP mean, confidence counts).
    """
    work = pd.DataFrame(
        {
            "cell_row": df["cell_row"].to_numpy(),
            "cell_col": df["cell_col"].to_numpy(),
            "date": df["date"].to_numpy(),
            "frp": df["frp"].to_numpy(dtype="float64"),
            "low": (df["confidence_class"] == "low").to_numpy(dtype="int32"),
            "nominal": (df["confidence_class"] == "nominal").to_numpy(dtype="int32"),
            "high": (df["confidence_class"] == "high").to_numpy(dtype="int32"),
        }
    )
    spec = {
        "n": ("frp", "size"),
        "frp_sum": ("frp", "sum"),
        "frp_n": ("frp", "count"),
        "low": ("low", "sum"),
        "nominal": ("nominal", "sum"),
        "high": ("high", "sum"),
    }

    if not slim:
        angle = 2 * np.pi * df["hour"].to_numpy(dtype="float64") / 24
        work["frp2"] = work["frp"] ** 2
        work["bt1"] = df["bt_primary"].to_numpy(dtype="float64")
        work["bt2"] = df["bt_secondary"].to_numpy(dtype="float64")
        work["scan"] = df["scan"].to_numpy(dtype="float64")
        work["track"] = df["track"].to_numpy(dtype="float64")
        work["night"] = (df["daynight"] == "N").to_numpy(dtype="int32")
        work["hsin"] = np.sin(angle)
        work["hcos"] = np.cos(angle)
        platforms = pd.get_dummies(df["platform"].astype(str), prefix="plat", dtype="int8")
        for column in platforms.columns:
            work[column] = platforms[column].to_numpy()
        spec.update(
            {
                "frp_sumsq": ("frp2", "sum"),
                "frp_max": ("frp", "max"),
                "bt1_sum": ("bt1", "sum"),
                "bt1_n": ("bt1", "count"),
                "bt1_max": ("bt1", "max"),
                "bt2_sum": ("bt2", "sum"),
                "bt2_n": ("bt2", "count"),
                "bt2_max": ("bt2", "max"),
                "scan_sum": ("scan", "sum"),
                "scan_n": ("scan", "count"),
                "track_sum": ("track", "sum"),
                "track_n": ("track", "count"),
                "night": ("night", "sum"),
                "hsin": ("hsin", "sum"),
                "hcos": ("hcos", "sum"),
            }
        )
        spec.update({column: (column, "max") for column in platforms.columns})

    return work.groupby(KEYS, sort=False, observed=True).agg(**spec).reset_index()


def combine_partials(parts: list[pd.DataFrame]) -> pd.DataFrame:
    df = pd.concat(parts, ignore_index=True, sort=False)
    platform_columns = [c for c in df.columns if c.startswith("plat_")]
    if platform_columns:
        df[platform_columns] = df[platform_columns].fillna(0)
    how = {
        column: ("max" if column in MAX_COLUMNS or column.startswith("plat_") else "sum")
        for column in df.columns
        if column not in KEYS
    }
    return df.groupby(KEYS, sort=False).agg(how).reset_index()


def finalize(out: pd.DataFrame, prefix: str, slim: bool) -> pd.DataFrame:
    """Turn merged partial statistics into the feature / target columns."""
    res = out[KEYS].copy()
    detections = out["n"].to_numpy(dtype="float64")
    res[f"{prefix}_detections"] = detections
    res[f"{prefix}_frp_mean"] = safe_div(out["frp_sum"], out["frp_n"])
    res[f"{prefix}_frp_sum"] = out["frp_sum"].to_numpy()
    res[f"{prefix}_conf_low"] = out["low"].to_numpy()
    res[f"{prefix}_conf_nominal"] = out["nominal"].to_numpy()
    res[f"{prefix}_conf_high"] = out["high"].to_numpy()
    if slim:
        return res

    n = out["frp_n"].to_numpy(dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        variance = (out["frp_sumsq"].to_numpy() - out["frp_sum"].to_numpy() ** 2 / n) / (n - 1)
    variance = np.where(n > 1, np.maximum(variance, 0.0), np.nan)
    res[f"{prefix}_frp_std"] = np.sqrt(variance)
    res[f"{prefix}_frp_max"] = out["frp_max"].to_numpy()
    res[f"{prefix}_bt_primary_mean"] = safe_div(out["bt1_sum"], out["bt1_n"])
    res[f"{prefix}_bt_primary_max"] = out["bt1_max"].to_numpy()
    res[f"{prefix}_bt_secondary_mean"] = safe_div(out["bt2_sum"], out["bt2_n"])
    res[f"{prefix}_bt_secondary_max"] = out["bt2_max"].to_numpy()
    res[f"{prefix}_scan_mean"] = safe_div(out["scan_sum"], out["scan_n"])
    res[f"{prefix}_track_mean"] = safe_div(out["track_sum"], out["track_n"])
    res[f"{prefix}_night_share"] = safe_div(out["night"], detections)
    res[f"{prefix}_hour_sin"] = safe_div(out["hsin"], detections)
    res[f"{prefix}_hour_cos"] = safe_div(out["hcos"], detections)
    # Circular mean of the hour of day (UTC), in [0, 24).
    res[f"{prefix}_hour_mean"] = (
        np.arctan2(out["hsin"].to_numpy(), out["hcos"].to_numpy()) * 24 / (2 * np.pi)
    ) % 24
    platform_columns = [c for c in out.columns if c.startswith("plat_")]
    res[f"{prefix}_platforms"] = (
        out[platform_columns].sum(axis=1).to_numpy() if platform_columns else 0
    )
    return res


def load_cell_days(
    files: list[Path],
    sensor: str,
    grid: float,
    start: str | None = None,
    end: str | None = None,
    windows: dict[tuple[str, str], tuple[pd.Timestamp, pd.Timestamp] | None] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Clean and aggregate many files (one per country) into one cell-day table.

    ``windows`` maps (year, country) to the date range actually covered by that
    country's VIIRS file. A MODIS row outside its own country's window is dropped
    instead of being labelled "0 VIIRS": a partial-year VIIRS file must not create
    false negatives in the remaining months. ``None`` means the country has no
    usable VIIRS data at all, so its MODIS rows are dropped too.
    """
    slim = sensor == "viirs"
    low = pd.Timestamp(start) if start else None
    high = pd.Timestamp(end) if end else None

    parts, reports = [], []
    file_windows: dict[str, list[str] | None] = {}
    for index, file in enumerate(files, 1):
        df, report = read_firms(file, sensor)
        if not df.empty:
            if low is not None:
                df = df[df["date"] >= low]
            if high is not None:
                df = df[df["date"] <= high]

        key = file_key(file)
        window_key = "|".join(key) if key is not None else file.name
        if not df.empty:
            window = [str(df["date"].min().date()), str(df["date"].max().date())]
            previous = file_windows.get(window_key)
            if previous is not None:
                # More than one file for the same (year, country): union the ranges.
                window = [min(previous[0], window[0]), max(previous[1], window[1])]
            file_windows[window_key] = window
        else:
            file_windows.setdefault(window_key, None)

        if not df.empty and windows is not None:
            covered = windows.get(key) if key is not None else None
            before = len(df)
            if covered is None:
                df = df.iloc[0:0]
            else:
                df = df[df["date"].between(covered[0], covered[1])]
            report["steps"]["drop_outside_viirs_coverage"] = before - len(df)

        report["rows_used"] = int(len(df))
        reports.append(report)
        if not df.empty:
            parts.append(partial_aggregate(add_cells(df, grid), slim))
        if index % 20 == 0 or index == len(files):
            print(f"  {sensor}: {index}/{len(files)} files", flush=True)

    if not parts:
        sys.exit(f"No {sensor} rows left after cleaning / date filter.")
    table = finalize(combine_partials(parts), sensor, slim)

    classes: Counter = Counter()
    steps: Counter = Counter()
    for report in reports:
        classes.update(report["confidence_classes"])
        steps.update(report["steps"])
    summary = {
        "sensor": sensor,
        "files": len(files),
        "rows_raw": int(sum(r["rows_raw"] for r in reports)),
        "rows_clean": int(sum(r["rows_clean"] for r in reports)),
        "rows_used": int(sum(r["rows_used"] for r in reports)),
        "steps": {name: int(steps[name]) for name in STEP_NAMES},
        "confidence_classes": dict(classes),
        "date_min": str(table["date"].min().date()),
        "date_max": str(table["date"].max().date()),
        "cell_days": int(len(table)),
        "file_windows": file_windows,
    }
    return table, summary


# ------------------------------------------------------------------- features
def add_neighbour_features(cell_days: pd.DataFrame) -> pd.DataFrame:
    """Add 3x3 neighbourhood and previous-days context for the MODIS counts.

    Only information a real-time application would have is used: same-day
    neighbours and the previous three days of the same cell.
    """
    df = cell_days.sort_values(["date", "cell_row", "cell_col"]).reset_index(drop=True)
    rows = df["cell_row"].to_numpy(dtype=np.int64)
    cols = df["cell_col"].to_numpy(dtype=np.int64)
    days = (df["date"] - df["date"].min()).dt.days.to_numpy(dtype=np.int64) + 5
    counts = df["modis_detections"].to_numpy(dtype=np.float64)

    row0, col0 = rows.min() - 2, cols.min() - 2
    n_cols = int(cols.max() - col0 + 3)
    n_days = int(days.max() + 10)

    def key(r, c, d):
        return ((r - row0) * n_cols + (c - col0)) * n_days + d

    keys = key(rows, cols, days)
    order = np.argsort(keys)
    sorted_keys, sorted_counts = keys[order], counts[order]

    def count_at(d_row: int, d_col: int, lag: int = 0) -> np.ndarray:
        query = key(rows + d_row, cols + d_col, days - lag)
        pos = np.searchsorted(sorted_keys, query)
        clipped = np.minimum(pos, len(sorted_keys) - 1)
        hit = (pos < len(sorted_keys)) & (sorted_keys[clipped] == query)
        return np.where(hit, sorted_counts[clipped], 0.0)

    neighbours = np.zeros(len(df))
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            if d_row or d_col:
                neighbours += count_at(d_row, d_col)
    df["modis_neighbour_count"] = neighbours

    previous = []
    for lag, name in ((1, "prev1"), (2, "prev2"), (3, "prev3")):
        values = count_at(0, 0, lag)
        df[f"modis_{name}_count"] = values
        previous.append(values)
    df["modis_prev3_mean"] = np.mean(previous, axis=0)
    return df


def add_cell_centres(table: pd.DataFrame, grid: float, with_id: bool = False) -> pd.DataFrame:
    """Cell centre coordinates (and, optionally, a readable cell id)."""
    table["cell_lat"] = (table["cell_row"] + 0.5) * grid
    table["cell_lon"] = (table["cell_col"] + 0.5) * grid
    if with_id:
        table["cell_id"] = "r" + table["cell_row"].astype(str) + "c" + table["cell_col"].astype(str)
    return table


def add_time_features(table: pd.DataFrame) -> pd.DataFrame:
    """Seasonal and time-of-day features (shared by training and prediction)."""
    table["doy"] = table["date"].dt.day_of_year
    table["doy_sin"] = np.sin(2 * np.pi * table["doy"] / 365.25)
    table["doy_cos"] = np.cos(2 * np.pi * table["doy"] / 365.25)
    table["hour_sin"] = table["modis_hour_sin"]
    table["hour_cos"] = table["modis_hour_cos"]
    table["year"] = table["date"].dt.year
    return table


# ------------------------------------------------------------------------ build
def coverage_ratio_table(viirs_cd: pd.DataFrame, table: pd.DataFrame, grid: float) -> pd.DataFrame:
    """VIIRS detections that exist vs. those inside the MODIS cell-day table.

    One row per (1-degree block, calendar month). ``k = v_full / v_in`` is the
    factor needed to lift a conditional (MODIS-observed) estimate to the
    unconditional VIIRS scale. VIIRS-only cell-days are the reason ``k > 1``.
    """
    year = int(table["date"].dt.year.mode().iloc[0]) if len(table) else 0
    full = (
        pd.DataFrame(
            {
                "br": np.floor((viirs_cd["cell_row"].to_numpy() + 0.5) * grid).astype(np.int32),
                "bc": np.floor((viirs_cd["cell_col"].to_numpy() + 0.5) * grid).astype(np.int32),
                "month": viirs_cd["date"].dt.month.to_numpy(),
                "v_full": viirs_cd["viirs_detections"].to_numpy(dtype="float64"),
                "days_full": 1,
            }
        )
        .groupby(["br", "bc", "month"], sort=False)
        .agg(v_full=("v_full", "sum"), days_full=("days_full", "size"))
        .reset_index()
    )
    inside = (
        pd.DataFrame(
            {
                "br": np.floor(table["cell_lat"].to_numpy()).astype(np.int32),
                "bc": np.floor(table["cell_lon"].to_numpy()).astype(np.int32),
                "month": table["date"].dt.month.to_numpy(),
                "v_in": table["viirs_detections"].to_numpy(dtype="float64"),
                "days_in": 1,
            }
        )
        .groupby(["br", "bc", "month"], sort=False)
        .agg(v_in=("v_in", "sum"), days_in=("days_in", "size"))
        .reset_index()
    )
    ratio = full.merge(inside, on=["br", "bc", "month"], how="left")
    ratio[["v_in", "days_in"]] = ratio[["v_in", "days_in"]].fillna(0)
    ratio["year"] = year
    ratio["k"] = np.where(
        ratio["v_in"] > 0,
        ratio["v_full"] / ratio["v_in"].clip(lower=1e-9),
        np.nan,
    )
    return ratio


def build(
    modis_paths: list[Path],
    viirs_paths: list[Path],
    grid: float,
    start: str | None = None,
    end: str | None = None,
    countries: list[str] | None = None,
    drop_uncovered: bool = True,
    uncovered_min_modis: int = 20,
    coverage_out: Path | None = None,
) -> tuple[pd.DataFrame, dict]:
    modis_files = expand_paths(modis_paths)
    viirs_files = expand_paths(viirs_paths)

    if countries:
        wanted = {normalise_country(c) for c in countries}

        def wanted_file(file: Path) -> bool:
            key = file_key(file)
            return key is not None and key[1] in wanted

        modis_files = [f for f in modis_files if wanted_file(f)]
        viirs_files = [f for f in viirs_files if wanted_file(f)]
        if not modis_files or not viirs_files:
            sys.exit("--countries matched no files. Use the names as they appear in the file names.")

    # MODIS countries without a VIIRS file (same year) would get a wrong "0 VIIRS" label.
    skipped: list[str] = []
    viirs_keys = {key for key in map(file_key, viirs_files) if key is not None}
    if viirs_keys:
        paired = []
        for file in modis_files:
            key = file_key(file)
            if key is None or key in viirs_keys:
                paired.append(file)
            else:
                skipped.append(file.name)
        modis_files = paired
    print(f"MODIS files: {len(modis_files)} (skipped without VIIRS: {len(skipped)}), VIIRS files: {len(viirs_files)}")

    # VIIRS first: each country's actual date range is needed to label MODIS
    # correctly. Without this, a partial-year VIIRS file creates false zeros.
    viirs_cd, viirs_report = load_cell_days(viirs_files, "viirs", grid, start, end)
    viirs_windows: dict[tuple[str, str], tuple[pd.Timestamp, pd.Timestamp] | None] = {}
    for window_key, window in viirs_report.get("file_windows", {}).items():
        parts = window_key.split("|", 1)
        if len(parts) != 2:
            continue
        viirs_windows[(parts[0], parts[1])] = (
            (pd.Timestamp(window[0]), pd.Timestamp(window[1])) if window else None
        )
    modis_cd, modis_report = load_cell_days(
        modis_files, "modis", grid, start, end, windows=viirs_windows
    )

    modis_cd = add_neighbour_features(modis_cd)
    in_modis = len(viirs_cd[KEYS].merge(modis_cd[KEYS], on=KEYS, how="inner"))
    viirs_only = len(viirs_cd) - in_modis
    viirs_total = float(viirs_cd["viirs_detections"].sum())

    table = modis_cd.merge(viirs_cd, on=KEYS, how="left")
    for column in ("viirs_detections", "viirs_conf_low", "viirs_conf_nominal", "viirs_conf_high"):
        table[column] = table[column].fillna(0)
    del modis_cd

    viirs_dates = (viirs_cd["date"].min(), viirs_cd["date"].max())
    coverage: dict = {
        "viirs_date_min": str(viirs_dates[0].date()),
        "viirs_date_max": str(viirs_dates[1].date()),
        "modis_files_skipped_without_viirs": skipped,
    }

    # 1) MODIS days outside the period VIIRS was downloaded for.
    in_range = table["date"].between(*viirs_dates)
    coverage["cell_days_outside_viirs_dates"] = int((~in_range).sum())
    table = table[in_range].copy()
    table = add_cell_centres(table, grid)

    # 2) 1-degree blocks with plenty of MODIS but no VIIRS at all: almost certainly a
    #    missing VIIRS area, so a "0" label there would be wrong.
    block = pd.DataFrame(
        {
            "br": np.floor(table["cell_lat"]).astype(np.int32).to_numpy(),
            "bc": np.floor(table["cell_lon"]).astype(np.int32).to_numpy(),
            "m": table["modis_detections"].to_numpy(),
            "v": table["viirs_detections"].to_numpy(),
        }
    )
    totals = block.groupby(["br", "bc"]).agg(m=("m", "sum"), v=("v", "sum"))
    uncovered_blocks = totals[(totals["m"] >= uncovered_min_modis) & (totals["v"] == 0)].index
    uncovered = pd.MultiIndex.from_arrays([block["br"], block["bc"]]).isin(uncovered_blocks)
    coverage["uncovered_blocks"] = int(len(uncovered_blocks))
    coverage["cell_days_in_uncovered_blocks"] = int(uncovered.sum())
    coverage["uncovered_dropped"] = bool(drop_uncovered)
    if drop_uncovered:
        table = table[~uncovered].copy()
    del block

    if table.empty:
        sys.exit("The table is empty after the coverage checks. Check that MODIS and VIIRS cover the same countries and dates.")

    table = add_time_features(table)

    # Conditional -> unconditional correction, per 1-degree block and month.
    ratio = coverage_ratio_table(viirs_cd, table, grid)
    if coverage_out is not None:
        coverage_out.parent.mkdir(parents=True, exist_ok=True)
        ratio.to_parquet(coverage_out, index=False)

    detected = float(table["viirs_detections"].sum())
    summary = {
        "grid_degrees": grid,
        "years": sorted(int(y) for y in table["year"].unique()),
        "modis": modis_report,
        "viirs": viirs_report,
        "cell_days_modis_after_checks": int(len(table)),
        "cell_days_viirs": int(viirs_report["cell_days"]),
        "viirs_only_cell_days_excluded": int(viirs_only),
        "viirs_detections_total": viirs_total,
        "viirs_detections_in_table": detected,
        "viirs_detections_share_in_table": float(detected / viirs_total) if viirs_total else None,
        "viirs_only_scale_factor": float(viirs_total / max(detected, 1e-9)),
        "coverage_ratio": {
            "rows": int(len(ratio)),
            "k_median": float(ratio["k"].median()) if len(ratio) else None,
            "k_p10": float(ratio["k"].quantile(0.10)) if len(ratio) else None,
            "k_p90": float(ratio["k"].quantile(0.90)) if len(ratio) else None,
            "file": str(coverage_out) if coverage_out is not None else None,
        },
        "coverage": coverage,
        "positive_rate": float((table["viirs_detections"] > 0).mean()),
        "mean_viirs_per_modis_detection": float(
            table["viirs_detections"].sum() / max(table["modis_detections"].sum(), 1.0)
        ),
    }
    return table, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modis", required=True, nargs="+", type=Path, help="CSV file(s) or folder(s)")
    parser.add_argument("--viirs", required=True, nargs="+", type=Path, help="CSV file(s) or folder(s)")
    parser.add_argument("--grid", type=float, default=DEFAULT_GRID, help="Grid size in degrees (default 0.05).")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument(
        "--coverage-out",
        type=Path,
        default=None,
        help="Per-block/month VIIRS coverage ratio 'k' (default: next to --out).",
    )
    parser.add_argument("--start", default=None, help="YYYY-MM-DD, for quick tests")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD, for quick tests")
    parser.add_argument("--countries", nargs="*", default=None, help="Only these countries (file-name spelling)")
    parser.add_argument("--keep-uncovered", action="store_true", help="Do not drop 1-degree blocks without any VIIRS.")
    parser.add_argument("--uncovered-min-modis", type=int, default=20)
    parser.add_argument("--year", type=int, default=None, help="Ignored (kept for old commands).")
    args = parser.parse_args()

    table, summary = build(
        args.modis,
        args.viirs,
        args.grid,
        start=args.start,
        end=args.end,
        countries=args.countries,
        drop_uncovered=not args.keep_uncovered,
        uncovered_min_modis=args.uncovered_min_modis,
        coverage_out=args.coverage_out or args.out.with_suffix(".coverage.parquet"),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(args.out, index=False)
    summary_path = args.summary or args.out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nTable: {args.out}  ({len(table):,} rows)\nSummary: {summary_path}")


if __name__ == "__main__":
    main()