"""Pure grid construction and aggregation (no DB, no I/O).

Faithful port of ``reference/legacy-jupyter/ais_modules/grid.py`` (the
``GridAggregator``) plus the ``pd.cut`` binning + cell-summation loop that lives
inside ``ais_grid_module.create`` / ``create_linear``.

Spec reference: ``logic-spec/01-core-emission-grid-logic.md`` section 4.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from geopy.distance import geodesic


@dataclass
class GridRange:
    """Result of :meth:`GridAggregator.calculate_grid_range`.

    Mirrors the 5-tuple returned by the reference, kept as a named struct:

    - ``grid``: zero-filled DataFrame (index=lats, columns=lons)
    - ``lats_bins`` / ``lons_bins``: ``pd.cut`` bin edges
    - ``lats`` / ``lons``: sorted cell-center labels
    """

    grid: pd.DataFrame
    lats_bins: np.ndarray
    lons_bins: np.ndarray
    lats: list[float]
    lons: list[float]


class GridAggregator:
    """Builds a lat/lon grid by geodesic stepping from a center point.

    From ``(center_lat, center_lon)`` it steps ``grid_size`` meters in each of
    the four cardinal directions until exceeding ``radius`` meters, collecting
    the latitude/longitude boundaries. Faithful to the reference implementation.
    """

    def __init__(self, center_lat: float, center_lon: float, radius: float, grid_size: float):
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.radius = radius  # meters
        self.grid_size = grid_size  # meters

    def calculate_grid_range(self) -> GridRange:
        lats, lons = [self.center_lat], [self.center_lon]
        # (bearing, step): North/South affect lats, East/West affect lons.
        directions = [(0, 1), (180, -1), (90, 1), (270, -1)]

        for bearing, _step in directions:
            current_lat, current_lon = self.center_lat, self.center_lon
            while True:
                next_point = geodesic(meters=self.grid_size).destination(
                    (current_lat, current_lon), bearing
                )
                if (
                    geodesic(
                        (self.center_lat, self.center_lon),
                        (next_point.latitude, next_point.longitude),
                    ).meters
                    > self.radius
                ):
                    break
                if bearing in (0, 180):
                    lats.append(next_point.latitude)
                else:
                    lons.append(next_point.longitude)
                current_lat, current_lon = next_point.latitude, next_point.longitude

        lats = sorted(lats)
        lons = sorted(lons)
        grid = pd.DataFrame(np.zeros((len(lats), len(lons))), index=lats, columns=lons)
        # NOTE (faithful): bins are an even linspace over [min, max] with
        # len(lats)+1 edges, NOT the geodesic-stepped lat values themselves.
        lats_bins = np.linspace(min(lats), max(lats), len(lats) + 1)
        lons_bins = np.linspace(min(lons), max(lons), len(lons) + 1)
        return GridRange(grid=grid, lats_bins=lats_bins, lons_bins=lons_bins, lats=lats, lons=lons)


def aggregate_to_grid(pollution_df: pd.DataFrame, grid_range: GridRange) -> pd.DataFrame:
    """Bin each track point and sum ``main_usage + aux_usage`` per cell.

    Faithful to the binning + accumulation loop in ``create``/``create_linear``
    (spec section 4): ``pd.cut`` assigns ``lat_bin``/``lon_bin`` labels, then
    each row's total fuel usage is added to the matching grid cell.

    Returns a *new* grid DataFrame (does not mutate ``grid_range.grid``).
    """
    grid = grid_range.grid.copy()
    df = pollution_df.copy()

    df["lat_bin"] = pd.cut(
        df["latitude"], bins=grid_range.lats_bins, labels=grid_range.lats, include_lowest=True
    )
    df["lon_bin"] = pd.cut(
        df["longitude"], bins=grid_range.lons_bins, labels=grid_range.lons, include_lowest=True
    )

    for _idx, row in df.iterrows():
        lat_bin = row["lat_bin"]
        lon_bin = row["lon_bin"]
        if lat_bin in grid.index and lon_bin in grid.columns:
            grid.loc[lat_bin, lon_bin] += row["aux_usage"] + row["main_usage"]

    return grid
