"""Matched-pair construction shared by harmonization and validation.

Pairs come from ``harmonizer.matching.spatial_links``; FRP and coordinates are
attached from the observation frame. No pair is assumed to be the same fire.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from harmonizer.matching import spatial_links
from harmonizer.store import Database
from harmonizer.store import sql

from ..errors import ApiError


def build_pairs(
    database: Database,
    filters: dict[str, Any],
    radius_m: float,
    time_window_h: float | None,
    max_pairs_per_detection: int,
    max_links: int = 200_000,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return matched pairs with FRP and coordinates, plus matching metadata."""
    frame_sql, frame_params = sql.observations_for_matching(filters)
    frame = database.fetch_frame(frame_sql, frame_params)
    if frame.empty:
        raise ApiError(
            "no_observations",
            "No observations match the requested filters.",
            409,
        )

    links, notes = spatial_links(
        frame,
        radius_m=radius_m,
        time_window_h=time_window_h,
        max_pairs_per_detection=max_pairs_per_detection,
        max_links=max_links,
    )
    if links.empty:
        raise ApiError(
            "no_pairs",
            "No MODIS/VIIRS pairs satisfy the requested radius and time window.",
            409,
            {"criteria": notes["criterion"]},
        )

    lookup = frame.set_index("observation_id")[["frp_mw", "lat", "lon"]]
    pairs = links.copy()
    pairs["frp_a"] = pairs["observation_a"].map(lookup["frp_mw"])
    pairs["frp_b"] = pairs["observation_b"].map(lookup["frp_mw"])
    pairs["lat_a"] = pairs["observation_a"].map(lookup["lat"])
    pairs["lon_a"] = pairs["observation_a"].map(lookup["lon"])
    pairs["lat_b"] = pairs["observation_b"].map(lookup["lat"])
    pairs["lon_b"] = pairs["observation_b"].map(lookup["lon"])

    return pairs, notes
