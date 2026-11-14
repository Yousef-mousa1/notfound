"""Split a large FIRMS CSV into smaller files that the importer can load safely.

Why: the importer reads a whole file into pandas (dtype=str) and then converts
every row to a dict. A 1.25 GB VIIRS file (~18 million rows) needs tens of GB
of RAM that way, so it is split into parts of a few hundred thousand rows.

Each part keeps the original header and is grouped by acquisition year, so the
file names stay readable (modis_2019_part01.csv). Parts are written into the
output directory and can be imported one by one with
`python -m scripts.demo_run --file <part>` or all at once by putting them in
dataSets/ and letting the demo scan that folder.

Usage (from the project root):
    python tools/split_firms_csv.py --input "C:/data/viirs_all.csv" --out dataSets --rows 400000
    python tools/split_firms_csv.py --input a.csv b.csv --out dataSets
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def split_file(path: Path, out_dir: Path, rows_per_part: int, chunk_rows: int = 1_000_000) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem.replace(" ", "_")
    written: list[Path] = []
    # Per-year state: current open part number, rows already written, and the
    # file handle we append to.
    state: dict[str, dict] = {}

    def write_rows(year: str, frame: pd.DataFrame) -> None:
        info = state.setdefault(year, {"part": 1, "rows": 0, "path": None})
        remaining = frame
        while len(remaining):
            if info["rows"] >= rows_per_part:
                info["part"] += 1
                info["rows"] = 0
                info["path"] = None
            if info["path"] is None:
                info["path"] = out_dir / f"{stem}_{year}_part{info['part']:02d}.csv"
                written.append(info["path"])
            space = rows_per_part - info["rows"]
            piece, remaining = remaining.iloc[:space], remaining.iloc[space:]
            header = not info["path"].exists()
            piece.to_csv(info["path"], mode="a", header=header, index=False)
            info["rows"] += len(piece)

    for chunk in pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, chunksize=chunk_rows):
        if "acq_date" not in chunk.columns:
            raise ValueError(f"{path.name}: no acq_date column, is this a FIRMS detection file?")
        years = chunk["acq_date"].str.slice(0, 4)
        for year, group in chunk.groupby(years, sort=True):
            write_rows(str(year), group)

    for item in written:
        print(f"  {item.name}: {item.stat().st_size / 1e6:.1f} MB")
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs="+", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("dataSets"))
    parser.add_argument("--rows", type=int, default=400_000, help="Rows per part (default 400k).")
    args = parser.parse_args()

    for path in args.input:
        print(f"splitting {path} ({path.stat().st_size / 1e6:.0f} MB) ...")
        parts = split_file(path, args.out, args.rows)
        print(f"  -> {len(parts)} parts in {args.out}")


if __name__ == "__main__":
    main()
