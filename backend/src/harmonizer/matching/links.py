"""Cross-sensor link generation.

Both functions produce link tables only. No row is ever deleted or merged.
Distances are geodesic (haversine, metres); degrees are never used as distance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_RADIUS_M = 6_371_008.8
METRES_PER_DEGREE = 111_320.0


def haversine_m(
    lat1: np.ndarray | float,
    lon1: np.ndarray | float,
    lat2: np.ndarray | float,
    lon2: np.ndarray | float,
) -> np.ndarray:
    """Great-circle distance in metres between WGS84 points."""
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    d_phi = np.radians(np.asarray(lat2) - np.asarray(lat1))
    d_lambda = np.radians(np.asarray(lon2) - np.asarray(lon1))

    a = np.sin(d_phi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(d_lambda / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize an observation frame for matching.

    Requires columns: ``observation_id, sensor, lat, lon, datetime_utc``.
    ``ts`` is seconds since epoch; rows without a timestamp stay ``NaT``.
    """
    prepared = frame[["observation_id", "sensor", "lat", "lon", "datetime_utc"]].copy()
    prepared["lat"] = pd.to_numeric(prepared["lat"], errors="coerce")
    prepared["lon"] = pd.to_numeric(prepared["lon"], errors="coerce")
    prepared = prepared.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    timestamps = pd.to_datetime(prepared["datetime_utc"], errors="coerce")
    prepared["ts"] = timestamps.map(lambda value: value.timestamp() if pd.notna(value) else np.nan)
    return prepared


def _split(prepared: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    modis = prepared[prepared["sensor"] == "modis"].reset_index(drop=True)
    viirs = prepared[prepared["sensor"] == "viirs"].reset_index(drop=True)
    return modis, viirs


def _spatial_index(viirs: pd.DataFrame, radius_m: float) -> tuple[dict, float, float, float, float]:
    """Bucket VIIRS rows into a grid whose cells are about one radius wide."""
    mean_lat = float(viirs["lat"].mean()) if len(viirs) else 0.0
    cell_lat = radius_m / METRES_PER_DEGREE
    cos_lat = max(np.cos(np.radians(mean_lat)), 0.01)
    cell_lon = radius_m / (METRES_PER_DEGREE * cos_lat)

    min_lat = float(viirs["lat"].min()) if len(viirs) else 0.0
    min_lon = float(viirs["lon"].min()) if len(viirs) else 0.0
    row = np.floor((viirs["lat"].to_numpy() - min_lat) / cell_lat).astype(int)
    col = np.floor((viirs["lon"].to_numpy() - min_lon) / cell_lon).astype(int)

    buckets: dict[tuple[int, int], np.ndarray] = {}
    for cell, indices in pd.Series(range(len(viirs))).groupby([row, col]):
        buckets[cell] = indices.to_numpy()
    return buckets, cell_lat, cell_lon, min_lat, min_lon


def spatial_links(
    frame: pd.DataFrame,
    radius_m: float,
    time_window_h: float | None,
    max_pairs_per_detection: int,
    max_links: int,
) -> tuple[pd.DataFrame, dict]:
    """Link MODIS detections to VIIRS detections within ``radius_m``.

    Time is an optional additional constraint. For every MODIS detection the
    closest ``max_pairs_per_detection`` VIIRS detections are kept, so a single
    large fire does not explode into thousands of links. This cap is an
    engineering choice, reported in the result metadata.
    """
    prepared = prepare_frame(frame)
    modis, viirs = _split(prepared)
    notes = {
        "criterion": "geodesic distance <= radius_m"
        + (" and |dt| <= time_window_h" if time_window_h else " (no time constraint)"),
        "distance": "haversine metres",
        "max_pairs_per_detection": max_pairs_per_detection,
        "max_links": max_links,
        "modis_count": int(len(modis)),
        "viirs_count": int(len(viirs)),
    }
    if modis.empty or viirs.empty:
        return pd.DataFrame(columns=_LINK_COLUMNS), {**notes, "truncated": False, "pairs": 0}

    window_s = None if time_window_h is None else float(time_window_h) * 3600.0
    if window_s is not None:
        viirs = viirs.sort_values("ts", kind="stable").reset_index(drop=True)
        usable = viirs[viirs["ts"].notna()].reset_index(drop=True)
    else:
        usable = viirs

    buckets, cell_lat, cell_lon, min_lat, min_lon = _spatial_index(usable, radius_m)
    v_lat = usable["lat"].to_numpy()
    v_lon = usable["lon"].to_numpy()
    v_ts = usable["ts"].to_numpy()
    v_id = usable["observation_id"].to_numpy()

    links: list[dict] = []
    truncated = False

    for _, row in modis.iterrows():
        if window_s is not None:
            if pd.isna(row["ts"]):
                continue
            lo = int(np.searchsorted(v_ts, row["ts"] - window_s, side="left"))
            hi = int(np.searchsorted(v_ts, row["ts"] + window_s, side="right"))
            if hi <= lo:
                continue
            candidate_index = np.arange(lo, hi)
        else:
            r = int(np.floor((row["lat"] - min_lat) / cell_lat))
            c = int(np.floor((row["lon"] - min_lon) / cell_lon))
            parts = [
                buckets[(r + dr, c + dc)]
                for dr in (-1, 0, 1)
                for dc in (-1, 0, 1)
                if (r + dr, c + dc) in buckets
            ]
            if not parts:
                continue
            candidate_index = np.concatenate(parts)

        distances = haversine_m(row["lat"], row["lon"], v_lat[candidate_index], v_lon[candidate_index])
        keep = distances <= radius_m
        if not keep.any():
            continue
        idx = candidate_index[keep]
        dist = distances[keep]

        if len(idx) > max_pairs_per_detection:
            nearest = np.argsort(dist, kind="stable")[:max_pairs_per_detection]
            idx, dist = idx[nearest], dist[nearest]

        for j, distance in zip(idx, dist, strict=True):
            links.append(
                {
                    "observation_a": row["observation_id"],
                    "observation_b": v_id[j],
                    "distance_m": float(distance),
                    "delta_t_s": (
                        None
                        if pd.isna(v_ts[j]) or pd.isna(row["ts"])
                        else float(v_ts[j] - row["ts"])
                    ),
                }
            )
        if len(links) >= max_links:
            links = links[:max_links]
            truncated = True
            break

    return pd.DataFrame(links, columns=_LINK_COLUMNS), {
        **notes,
        "truncated": truncated,
        "pairs": len(links),
    }


def temporal_links(
    frame: pd.DataFrame,
    time_window_h: float,
    max_pairs_per_detection: int,
    max_links: int,
) -> tuple[pd.DataFrame, dict]:
    """Link MODIS detections to the closest VIIRS detections in time.

    Distance is still recorded for information, but it is not a criterion.
    """
    prepared = prepare_frame(frame)
    modis, viirs = _split(prepared)
    notes = {
        "criterion": "|dt| <= time_window_h (time only; distance reported, not filtered)",
        "max_pairs_per_detection": max_pairs_per_detection,
        "max_links": max_links,
        "modis_count": int(len(modis)),
        "viirs_count": int(len(viirs)),
    }
    usable = viirs[viirs["ts"].notna()].sort_values("ts", kind="stable").reset_index(drop=True)
    if modis.empty or usable.empty:
        return pd.DataFrame(columns=_LINK_COLUMNS), {**notes, "truncated": False, "pairs": 0}

    window_s = float(time_window_h) * 3600.0
    v_ts = usable["ts"].to_numpy()
    v_id = usable["observation_id"].to_numpy()
    v_lat = usable["lat"].to_numpy()
    v_lon = usable["lon"].to_numpy()

    links: list[dict] = []
    truncated = False

    for _, row in modis.iterrows():
        if pd.isna(row["ts"]):
            continue
        lo = int(np.searchsorted(v_ts, row["ts"] - window_s, side="left"))
        hi = int(np.searchsorted(v_ts, row["ts"] + window_s, side="right"))
        if hi <= lo:
            continue
        within = np.arange(lo, hi)
        deltas = np.abs(v_ts[within] - row["ts"])
        if within.size > max_pairs_per_detection:
            within = within[np.argsort(deltas, kind="stable")[:max_pairs_per_detection]]
        distances = haversine_m(row["lat"], row["lon"], v_lat[within], v_lon[within])
        for j, distance in zip(within, distances, strict=True):
            links.append(
                {
                    "observation_a": row["observation_id"],
                    "observation_b": v_id[j],
                    "distance_m": float(distance),
                    "delta_t_s": float(v_ts[j] - row["ts"]),
                }
            )
        if len(links) >= max_links:
            links = links[:max_links]
            truncated = True
            break

    return pd.DataFrame(links, columns=_LINK_COLUMNS), {
        **notes,
        "truncated": truncated,
        "pairs": len(links),
    }


_LINK_COLUMNS = ["observation_a", "observation_b", "distance_m", "delta_t_s"]
