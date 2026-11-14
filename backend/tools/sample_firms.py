"""Cut a small, usable sample out of a large FIRMS CSV.

The sample keeps a contiguous area and a contiguous time range instead of random
rows: harmonization, matching and anomalies all depend on neighbouring cells and
neighbouring days, so a random row sample would break the physics of the data.

Streams the input in chunks, so a 1.25 GB file is fine on a laptop.

Usage (from the project root):
    python tools/sample_firms.py --input "D:/data/viirs_all.csv" --out dataSets \
        --bbox 0.7,6.2,3.9,12.5 --start 2019-01-01 --end 2019-12-31

    # كل دول غرب أفريقيا لسنة واحدة
    python tools/sample_firms.py --input viirs.csv --bbox -18,4,16,25 --start 2019-01-01 --end 2019-12-31

    # بدون فلتر مكاني (سنة كاملة عالمي) — ممكن يطلع كبير
    python tools/sample_firms.py --input modis.csv --start 2019-01-01 --end 2019-12-31
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def sample(
    path: Path,
    out_dir: Path,
    bbox: tuple[float, float, float, float] | None,
    start: str | None,
    end: str | None,
    chunk_rows: int = 1_000_000,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = []
    if bbox:
        suffix.append(f"{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}")
    if start:
        suffix.append(start[:4])
    name = f"{path.stem}_sample" + ("_" + "_".join(suffix) if suffix else "") + ".csv"
    out_path = out_dir / name

    kept = 0
    read = 0
    first = True
    for chunk in pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, chunksize=chunk_rows):
        read += len(chunk)
        if bbox:
            lat = pd.to_numeric(chunk["latitude"], errors="coerce")
            lon = pd.to_numeric(chunk["longitude"], errors="coerce")
            west, south, east, north = bbox
            chunk = chunk[(lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)]
        if start:
            chunk = chunk[chunk["acq_date"] >= start]
        if end:
            chunk = chunk[chunk["acq_date"] <= end]
        if len(chunk):
            chunk.to_csv(out_path, mode="w" if first else "a", header=first, index=False)
            first = False
            kept += len(chunk)
        print(f"  read {read:,} rows, kept {kept:,}", flush=True)

    if first:
        raise SystemExit(f"no rows matched the filters for {path.name}")
    print(f"{path.name}: kept {kept:,} of {read:,} rows -> {out_path} ({out_path.stat().st_size/1e6:.1f} MB)")
    return out_path


def parse_bbox(text: str | None) -> tuple[float, float, float, float] | None:
    if not text:
        return None
    parts = [float(p) for p in text.split(",")]
    if len(parts) != 4:
        raise SystemExit("--bbox must be west,south,east,north")
    return parts[0], parts[1], parts[2], parts[3]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("dataSets"))
    parser.add_argument("--bbox", default=None, help="west,south,east,north in degrees")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD")
    args = parser.parse_args()

    bbox = parse_bbox(args.bbox)
    for path in args.input:
        sample(path, args.out, bbox, args.start, args.end)


if __name__ == "__main__":
    main()
