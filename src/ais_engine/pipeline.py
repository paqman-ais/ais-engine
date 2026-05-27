"""End-to-end pipeline orchestration (DB-free).

Faithful port of ``ais_grid_module.create`` (no interpolation) and
``create_linear`` (linear interpolation), with the side effects removed: no
Excel writes, no module-import-time DB engine. The data source is injected as
an :class:`~ais_engine.repository.AISRepository`.

Spec reference: ``logic-spec/01-core-emission-grid-logic.md`` sections 3-5.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .fuel import get_pollution_data
from .grid import GridAggregator, GridRange, aggregate_to_grid
from .interpolation import build_interpolated_track
from .repository import AISRepository


@dataclass
class GridInfo:
    """Grid parameters (spec section 1 user input)."""

    center_lat: float
    center_lon: float
    radius_km: float
    grid_size_m: float


@dataclass
class QueryParams:
    """Query window (spec section 1 user input). ``mmsi=0`` means all ships."""

    region: int
    start_date: datetime
    end_date: datetime
    mmsi: int = 0


def _build_grid_range(grid_info: GridInfo) -> GridRange:
    return GridAggregator(
        grid_info.center_lat,
        grid_info.center_lon,
        grid_info.radius_km * 1000,  # km -> m, faithful to create()
        grid_info.grid_size_m,
    ).calculate_grid_range()


def _resolve_mmsis(repo: AISRepository, params: QueryParams) -> list[int]:
    if params.mmsi != 0:
        return [params.mmsi]
    return repo.get_mmsis(params.region, params.start_date, params.end_date)


def run_grid(
    repo: AISRepository, params: QueryParams, grid_info: GridInfo, *, interpolate: bool = False
) -> pd.DataFrame:
    """Compute the fuel-usage grid for the query window.

    When ``interpolate`` is False this mirrors ``create()`` (raw points). When
    True it mirrors ``create_linear()`` (moving segments resampled to 1s +
    linear interpolation). Returns the aggregated grid DataFrame (index=lats,
    columns=lons, values=total fuel usage in tonnes).

    Core output is format-agnostic: this returns the grid DataFrame and never
    writes to disk. Use :mod:`ais_engine.export` (``grid_to_excel`` /
    ``grid_to_csv``) to serialize it.

    Empty-result contract: a ship whose track is empty, has a single point, or is
    entirely outliers contributes nothing (its pollution frame is empty after the
    outlier + first-row drop), so the returned grid simply omits that ship's
    contribution. If no ship contributes, the all-zero base grid is returned.
    """
    grid_range = _build_grid_range(grid_info)
    grid = grid_range.grid.copy()

    for mmsi in _resolve_mmsis(repo, params):
        ship = repo.get_ship_params(mmsi)
        if ship is None:
            continue

        track = repo.get_ais_track(params.region, mmsi, params.start_date, params.end_date)
        if track.empty:
            continue

        if interpolate:
            track = build_interpolated_track(track)
            if track.empty:
                continue

        pollution_df = get_pollution_data(track, ship)
        if pollution_df.empty:
            continue

        ship_grid = aggregate_to_grid(pollution_df, grid_range)
        grid = grid.add(ship_grid, fill_value=0)

    return grid
