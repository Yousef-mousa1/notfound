"""A quick look at the raw FIRMS folders: a text report plus small sample CSVs.

Run it from modeling/ with the backend virtualenv active (needs pandas + numpy only):
    python tools/peek_data.py                      # every folder under data/raw
    python tools/peek_data.py data/raw/modis_2025 data/raw/viirs_2025

It writes:
    data/samples/report.txt             what is inside each folder
    data/samples/<folder>_sample.csv    300 random rows per folder (all columns)

The report covers: files and rows per file, columns, satellites, instruments, versions,
day/night, type, confidence (numbers or letters), FRP, rows per month (to spot gaps)
and, for MODIS/VIIRS folders of the same year, which countries exist on only one side.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw")
OUT = Path("data/samples")
SAMPLE_ROWS = 300
PER_FILE_SAMPLE = 40
CATEGORICAL = ["satellite", "instrument", "version", "daynight", "type"]
NAME_RE = re.compile(r"_(\d{4})_(.+)\.csv$")


def csv_files(folder: Path) -> list[Path]:
    return sorted(
        p
        for p in folder.rglob("*.csv")
        if not p.name.startswith(".") and "__MACOSX" not in p.parts
    )


def top(counter: Counter, n: int = 12) -> str:
    total = sum(counter.values()) or 1
    return ", ".join(f"{k!s}: {v:,} ({100 * v / total:.1f}%)" for k, v in counter.most_common(n)) or "(none)"


def peek_folder(folder: Path, lines: list[str], rng: np.random.Generator) -> set[str]:
    files = csv_files(folder)
    lines += ["=" * 78, f"{folder}   ({len(files)} csv files)"]
    if not files:
        lines.append("  no csv files found")
        return set()

    lines.append("  first files: " + ", ".join(f.name for f in files[:5]) + (" ..." if len(files) > 5 else ""))
    headers = {tuple(pd.read_csv(f, nrows=0).columns) for f in files}
    lines.append(f"  columns: {list(next(iter(headers)))}")
    if len(headers) > 1:
        lines.append(f"  WARNING: {len(headers)} different header layouts across the files")

    counters = {col: Counter() for col in CATEGORICAL}
    months: Counter = Counter()
    letters: Counter = Counter()
    rows_per_file: list[tuple[str, int]] = []
    samples, frp_parts = [], []
    total = numeric_total = 0
    classes = Counter()
    conf_min, conf_max = np.inf, -np.inf
    date_min = date_max = None
    lat_min = lon_min = np.inf
    lat_max = lon_max = -np.inf

    for file in files:
        df = pd.read_csv(file, low_memory=False, dtype={"confidence": str})
        n = len(df)
        rows_per_file.append((file.name, n))
        if not n:
            continue
        total += n
        samples.append(df.sample(min(n, PER_FILE_SAMPLE), random_state=int(rng.integers(1 << 31))))

        for col in CATEGORICAL:
            if col in df.columns:
                counters[col].update(df[col].astype(str).value_counts().to_dict())
        if "acq_date" in df.columns:
            dates = df["acq_date"].astype(str)
            months.update(dates.str[:7].value_counts().to_dict())
            date_min = dates.min() if date_min is None else min(date_min, dates.min())
            date_max = dates.max() if date_max is None else max(date_max, dates.max())
        if "confidence" in df.columns:
            conf = df["confidence"].astype(str).str.strip()
            numeric = pd.to_numeric(conf, errors="coerce")
            numeric_total += int(numeric.notna().sum())
            if numeric.notna().any():
                conf_min = min(conf_min, float(numeric.min()))
                conf_max = max(conf_max, float(numeric.max()))
                classes["low (0-29)"] += int((numeric < 30).sum())
                classes["nominal (30-79)"] += int(((numeric >= 30) & (numeric < 80)).sum())
                classes["high (80-100)"] += int((numeric >= 80).sum())
            letters.update(conf[numeric.isna()].str.lower().value_counts().to_dict())
        if "frp" in df.columns:
            frp_parts.append(pd.to_numeric(df["frp"], errors="coerce").to_numpy(dtype=np.float32))
        for col, is_lat in (("latitude", True), ("longitude", False)):
            if col in df.columns:
                values = pd.to_numeric(df[col], errors="coerce")
                if is_lat:
                    lat_min, lat_max = min(lat_min, values.min()), max(lat_max, values.max())
                else:
                    lon_min, lon_max = min(lon_min, values.min()), max(lon_max, values.max())

    lines.append(f"  rows: {total:,}   dates: {date_min} -> {date_max}")
    lines.append(f"  lat {lat_min:.2f}..{lat_max:.2f}   lon {lon_min:.2f}..{lon_max:.2f}")
    for col in CATEGORICAL:
        if counters[col]:
            lines.append(f"  {col}: {top(counters[col])}")

    if total:
        share = 100 * numeric_total / total
        lines.append(f"  confidence: {share:.1f}% of values are numbers, {100 - share:.1f}% are text")
        if numeric_total:
            lines.append(f"    numeric range {conf_min:g}..{conf_max:g}; FIRMS classes: {top(classes)}")
        if letters:
            lines.append(f"    text values: {top(letters)}")

    if frp_parts:
        frp = np.concatenate(frp_parts)
        frp = frp[np.isfinite(frp)]
        if frp.size:
            q = np.quantile(frp, [0.01, 0.5, 0.99])
            lines.append(
                f"  frp MW: min={frp.min():g} p01={q[0]:g} median={q[1]:g} p99={q[2]:g} max={frp.max():g}"
                f"   (>10000: {int((frp > 10_000).sum())})"
            )

    if months:
        lines.append("  rows per month: " + ", ".join(f"{m}={months[m]:,}" for m in sorted(months)))
    biggest = sorted(rows_per_file, key=lambda item: -item[1])[:8]
    lines.append("  biggest files: " + ", ".join(f"{name}={n:,}" for name, n in biggest))
    empty = sum(1 for _, n in rows_per_file if n == 0)
    if empty:
        lines.append(f"  empty files: {empty}")

    if samples:
        sample = pd.concat(samples, ignore_index=True)
        sample = sample.sample(min(len(sample), SAMPLE_ROWS), random_state=0)
        if "acq_date" in sample.columns:
            sample = sample.sort_values(["acq_date", "acq_time"] if "acq_time" in sample.columns else "acq_date")
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{folder.name}_sample.csv"
        sample.to_csv(path, index=False)
        lines.append(f"  sample written: {path}")

    countries = set()
    for file in files:
        match = NAME_RE.search(file.name)
        if match:
            countries.add(match.group(2))
    return countries


def main() -> None:
    folders = [Path(arg) for arg in sys.argv[1:]] or sorted(p for p in RAW.iterdir() if p.is_dir())
    if not folders:
        sys.exit("No folders found. Run this from the modeling/ folder.")

    rng = np.random.default_rng(0)
    lines: list[str] = []
    countries_by_folder: dict[str, set[str]] = {}
    for folder in folders:
        countries_by_folder[folder.name] = peek_folder(folder, lines, rng)

    # MODIS and VIIRS of the same year must cover the same countries.
    lines += ["=" * 78, "country coverage, MODIS vs VIIRS (by file name)"]
    years = sorted({m.group(1) for name in countries_by_folder if (m := re.search(r"(\d{4})$", name))})
    for year in years:
        modis = next((c for n, c in countries_by_folder.items() if n.startswith("modis") and n.endswith(year)), None)
        viirs = next((c for n, c in countries_by_folder.items() if n.startswith("viirs") and n.endswith(year)), None)
        if modis is None or viirs is None:
            lines.append(f"  {year}: only one sensor present")
            continue
        lines.append(
            f"  {year}: MODIS {len(modis)} countries, VIIRS {len(viirs)}, "
            f"only in MODIS: {sorted(modis - viirs)[:15]}, only in VIIRS: {sorted(viirs - modis)[:15]}"
        )

    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / "report.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()