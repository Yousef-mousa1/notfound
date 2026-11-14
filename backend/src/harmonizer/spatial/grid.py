"""Common spatial grid on an equirectangular approximation.

Cells are defined in degrees, sized in kilometres at the mid-latitude of the
data extent. This is an engineering approximation, not a projected CRS: at
Benin's latitude range (6-12 N) the east-west cell width varies by roughly 1.5%
across the extent, which is reported with every grid so users can judge it.
Distances between detections are always computed geodesically, never from the
grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

METRES_PER_DEGREE = 111_320.0


@dataclass(frozen=True)
class GridSpec:
    """Geometry of a generated grid."""

    cell_km: float
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    lat_step: float
    lon_step: float
    n_rows: int
    n_cols: int
    mean_lat: float
    area_distortion_pct: float

    @property
    def cell_count(self) -> int:
        return self.n_rows * self.n_cols

    def as_dict(self) -> dict[str, float | int]:
        return {
            "cell_km": self.cell_km,
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
            "lat_step": self.lat_step,
            "lon_step": self.lon_step,
            "n_rows": self.n_rows,
            "n_cols": self.n_cols,
            "cell_count": self.cell_count,
            "mean_lat": self.mean_lat,
            "area_distortion_pct": self.area_distortion_pct,
        }


def build_grid(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    cell_km: float,
) -> tuple[GridSpec, pd.DataFrame]:
    """Build a grid over a bounding box.

    Args:
        min_lat: Southern edge in WGS84 degrees.
        max_lat: Northern edge.
        min_lon: Western edge.
        max_lon: Eastern edge.
        cell_km: Nominal cell size in kilometres (measured at the mid-latitude).

    Returns:
        The grid specification and one row per cell.

    Raises:
        ValueError: If the box is invalid or the cell size is not positive.
    """
    if not (0 < cell_km <= 1000):
        raise ValueError("cell_km must be between 0 and 1000.")
    if not (min_lat < max_lat and min_lon < max_lon):
        raise ValueError("Grid bounds must have min < max.")

    mean_lat = (min_lat + max_lat) / 2.0
    cos_mean = max(math.cos(math.radians(mean_lat)), 0.01)
    lat_step = cell_km / (METRES_PER_DEGREE / 1000.0)
    lon_step = cell_km / ((METRES_PER_DEGREE / 1000.0) * cos_mean)

    n_rows = max(1, math.ceil((max_lat - min_lat) / lat_step))
    n_cols = max(1, math.ceil((max_lon - min_lon) / lon_step))

    cos_extremes = [
        max(math.cos(math.radians(min_lat)), 0.01),
        max(math.cos(math.radians(max_lat)), 0.01),
    ]
    distortion = (max(cos_extremes) / min(cos_extremes) - 1.0) * 100.0

    spec = GridSpec(
        cell_km=cell_km,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        lat_step=lat_step,
        lon_step=lon_step,
        n_rows=n_rows,
        n_cols=n_cols,
        mean_lat=mean_lat,
        area_distortion_pct=round(distortion, 3),
    )

    rows: list[dict] = []
    for row in range(n_rows):
        cell_min_lat = min_lat + row * lat_step
        cell_max_lat = min(max_lat, cell_min_lat + lat_step)
        for col in range(n_cols):
            cell_min_lon = min_lon + col * lon_step
            cell_max_lon = min(max_lon, cell_min_lon + lon_step)
            rows.append(
                {
                    "cell_id": f"r{row:04d}c{col:04d}",
                    "row_index": row,
                    "col_index": col,
                    "min_lat": cell_min_lat,
                    "max_lat": cell_max_lat,
                    "min_lon": cell_min_lon,
                    "max_lon": cell_max_lon,
                    "center_lat": (cell_min_lat + cell_max_lat) / 2.0,
                    "center_lon": (cell_min_lon + cell_max_lon) / 2.0,
                }
            )

    return spec, pd.DataFrame(rows)
