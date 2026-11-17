"""Assign each model estimate cell to a country (Natural Earth 1:50m polygons).

Creates the table ``estimate_country(entity_id, iso_a3, country)`` inside the
application DuckDB. It uses the centroid (lat/lon) of each 1-degree estimate
cell from ``estimates`` — these are model grid cells, NOT observations, and
the country is a display filter only. It does not change any estimate value.

Run with the API stopped (DuckDB allows a single writer)::

    cd backend && source .venv/bin/activate
    python tools/assign_estimate_countries.py --db data/processed/pyroscope_trimmed.duckdb
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import shapely
from shapely import STRtree
from shapely.geometry import shape

DEFAULT_DB = "data/processed/pyroscope_trimmed.duckdb"
DEFAULT_CACHE = "data/interim/ne_50m_admin_0_countries.geojson"


def load_countries(cache: Path):
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--cache", default=DEFAULT_CACHE)
    parser.add_argument("--snap-deg", type=float, default=0.5)
    args = parser.parse_args()

    geoms, codes, names = load_countries(Path(args.cache))
    print(f"{len(geoms)} country polygons loaded")

    con = duckdb.connect(args.db)
    rows = con.execute(
        "SELECT DISTINCT CAST(entity_id AS VARCHAR) AS entity_id, "
        "centroid_lat AS lat, centroid_lon AS lon FROM estimates "
        "WHERE centroid_lat IS NOT NULL AND centroid_lon IS NOT NULL"
    ).fetchdf()
    print(f"{len(rows):,} estimate cells to assign")

    points = shapely.points(rows["lon"].to_numpy(float), rows["lat"].to_numpy(float))
    tree = STRtree(geoms)
    idx = np.full(len(rows), -1, dtype=np.int64)

    point_i, geom_i = tree.query(points, predicate="within")
    if point_i.size:
        order = np.argsort(point_i, kind="stable")
        unique_points, first_pos = np.unique(point_i[order], return_index=True)
        idx[unique_points] = geom_i[order][first_pos]
    inside = int((idx >= 0).sum())

    missing = np.where(idx < 0)[0]
    snapped = 0
    if len(missing) and args.snap_deg > 0:
        near = tree.query_nearest(points[missing], max_distance=args.snap_deg, all_matches=False)
        if near.size:
            idx[missing[near[0]]] = near[1]
            snapped = int(near.shape[1])

    assigned = idx >= 0
    import pandas as pd

    result = pd.DataFrame(
        {
            "entity_id": rows["entity_id"].to_numpy()[assigned],
            "iso_a3": codes[idx[assigned]],
            "country": names[idx[assigned]],
        }
    )

    con.register("assigned_df", result)
    con.execute("DROP TABLE IF EXISTS estimate_country")
    con.execute("CREATE TABLE estimate_country AS SELECT * FROM assigned_df")
    con.unregister("assigned_df")

    total = len(rows)
    print(f"Inside a country : {inside:,}")
    print(f"Snapped to coast : {snapped:,}")
    print(f"Unassigned (sea) : {total - int(assigned.sum()):,} of {total:,}")
    print("Countries:", result["country"].nunique())
    print(result["country"].value_counts().head(10).to_string())
    con.close()


if __name__ == "__main__":
    main()
