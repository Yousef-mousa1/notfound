"""Assign every stored observation to a country (Natural Earth 1:50m polygons).

Creates (or replaces) the table `observation_country(observation_id, iso_a3, country)`
in the application DuckDB. Observations that fall at sea, farther than --snap-deg
from any country, are left out.

Run it with the API server stopped (DuckDB allows a single writer process):

    cd backend && source .venv/bin/activate
    pip install "shapely>=2.0" certifi
    python tools/assign_countries.py

Re-run it after importing new observation files.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import shapely

from shapely import STRtree
from shapely.geometry import shape

URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "refs/heads/master/geojson/ne_50m_admin_0_countries.geojson"
)
DEFAULT_DB = "data/processed/pyroscope.duckdb"
DEFAULT_CACHE = "data/interim/ne_50m_admin_0_countries.geojson"


def ssl_context() -> ssl.SSLContext:
    """Verify HTTPS with certifi's CA bundle (python.org builds on macOS ship without one)."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading country polygons -> {destination}")
    request = urllib.request.Request(url, headers={"User-Agent": "pyroscope-tools"})
    with urllib.request.urlopen(request, timeout=120, context=ssl_context()) as response:
        destination.write_bytes(response.read())


def load_countries(cache: Path):
    if not cache.exists():
        download(URL, cache)

    data = json.loads(cache.read_text(encoding="utf-8"))
    geoms, codes, names = [], [], []
    for feature in data["features"]:
        props = feature.get("properties") or {}
        code = props.get("ADM0_A3") or props.get("ADM0_ISO")
        name = props.get("NAME") or props.get("ADMIN")
        geometry = feature.get("geometry")
        if not code or code == "-99" or not name or not geometry:
            continue
        geom = shape(geometry)
        if not geom.is_valid:
            geom = shapely.make_valid(geom)
        geoms.append(geom)
        codes.append(str(code))
        names.append(str(name))
    return geoms, np.array(codes, dtype=object), np.array(names, dtype=object)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--cache", default=DEFAULT_CACHE)
    parser.add_argument(
        "--snap-deg",
        type=float,
        default=0.05,
        help="سحب النقط الساحلية لأقرب دولة في حدود الدرجات دي (0.05 ~ 5 كم). 0 = بدون سحب",
    )
    args = parser.parse_args()

    geoms, codes, names = load_countries(Path(args.cache))
    print(f"{len(geoms)} country polygons loaded")

    con = duckdb.connect(args.db)
    rows = con.execute(
        "SELECT CAST(observation_id AS VARCHAR) AS observation_id, lat, lon "
        "FROM observations WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ).fetchdf()
    if rows.empty:
        sys.exit("No observations found. Import data first (python -m scripts.demo_run).")
    print(f"{len(rows):,} observations to assign (this can take a minute)")

    points = shapely.points(
        rows["lon"].to_numpy(dtype=float), rows["lat"].to_numpy(dtype=float)
    )
    tree = STRtree(geoms)
    country_idx = np.full(len(rows), -1, dtype=np.int64)

    # 1) النقطة جوه حدود دولة
    point_i, geom_i = tree.query(points, predicate="within")
    if point_i.size:
        order = np.argsort(point_i, kind="stable")
        point_i, geom_i = point_i[order], geom_i[order]
        unique_points, first_pos = np.unique(point_i, return_index=True)
        country_idx[unique_points] = geom_i[first_pos]
    inside = int((country_idx >= 0).sum())

    # 2) نقط على الساحل خارج الحدود المبسّطة: أقرب دولة جوه المسافة المسموحة
    snapped = 0
    missing = np.where(country_idx < 0)[0]
    if len(missing) and args.snap_deg > 0:
        near = tree.query_nearest(points[missing], max_distance=args.snap_deg, all_matches=False)
        if near.size:
            country_idx[missing[near[0]]] = near[1]
            snapped = int(near.shape[1])

    assigned = country_idx >= 0
    result = pd.DataFrame(
        {
            "observation_id": rows["observation_id"].to_numpy()[assigned],
            "iso_a3": codes[country_idx[assigned]],
            "country": names[country_idx[assigned]],
        }
    )

    con.register("assigned_df", result)
    con.execute("DROP TABLE IF EXISTS observation_country")
    con.execute("CREATE TABLE observation_country AS SELECT * FROM assigned_df")
    con.unregister("assigned_df")
    con.close()

    total = len(rows)
    print(f"Inside a country polygon : {inside:,}")
    print(f"Snapped to nearest coast : {snapped:,}")
    print(f"Left unassigned (sea)    : {total - int(assigned.sum()):,} of {total:,}")
    print("Top countries:")
    print(result["country"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()