"""Download FIRMS Area API data for a full year in 5-day chunks.

The Area API returns at most 5 days per request, so a year is 73 requests.
Each (source, year, bbox) combination is cached as one CSV.

Usage:
    python download_firms.py --key MAP_KEY --bbox 0.7,6.2,3.9,12.5 \
        --jobs MODIS_SP:2025 VIIRS_SNPP_SP:2025 MODIS_SP:2005
"""

from __future__ import annotations

import argparse
import io
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def download(key: str, source: str, year: int, bbox: str, out_dir: Path) -> Path:
    cache = out_dir / f"{source}_{year}.csv"
    if cache.exists() and cache.stat().st_size > 0:
        print(f"cached {cache.name} ({cache.stat().st_size/1e6:.1f} MB)", flush=True)
        return cache

    frames: list[pd.DataFrame] = []
    day = pd.Timestamp(year=year, month=1, day=1)
    end = pd.Timestamp(year=year, month=12, day=31)
    step = 1
    while day <= end:
        chunk_end = min(day + pd.Timedelta(days=4), end)
        n_days = (chunk_end - day).days + 1
        url = f"{API}/{key}/{source}/{bbox}/{n_days}/{day.date()}"
        for attempt in range(4):
            try:
                response = requests.get(url, timeout=180)
                text = response.text.strip()
                if response.status_code == 200 and text.startswith("latitude"):
                    frames.append(pd.read_csv(io.StringIO(text)))
                    break
                if "Invalid" in text[:40] or "Error" in text[:40]:
                    raise RuntimeError(text[:120])
            except Exception as error:  # noqa: BLE001 - retry any transport error
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        print(f"  {source} {year} {day.date()}..{chunk_end.date()} rows={len(frames[-1]) if frames else 0}", flush=True)
        day = chunk_end + pd.Timedelta(days=1)
        step += 1
        time.sleep(0.25)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    df.to_csv(cache, index=False)
    print(f"saved {cache.name}: {len(df):,} rows", flush=True)
    return cache


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument("--bbox", required=True)
    parser.add_argument("--jobs", nargs="+", required=True, help="SOURCE:YEAR pairs")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    for job in args.jobs:
        source, year = job.split(":")
        download(args.key, source, int(year), args.bbox, RAW)


if __name__ == "__main__":
    main()
