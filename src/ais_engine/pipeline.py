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
from .grid import GridAggregator, GridRange, aggregate_value_to_grid
from .interpolation import build_interpolated_track
from .models import ShipParams
from .repository import AISRepository

__all__ = ["GridInfo", "QueryParams", "compute_pollution", "run_grid"]


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


def compute_pollution(
    track: pd.DataFrame, ship: ShipParams, *, interpolate: bool = False
) -> pd.DataFrame:
    """Per-point fuel/emission rows for one ship's track (ADR-0002 Silver).

    This is the public, stable entry point that the platform calls ONCE per
    point to materialize the Silver layer. It promotes the internal
    :func:`ais_engine.fuel.get_pollution_data` (plus the optional interpolation
    pre-pass) to a clean public API and is NOT aggregated to a grid.

    When ``interpolate`` is False this mirrors the no-interp ``create()`` point
    pipeline (raw points). When True it first builds the moving/stationary
    interpolated track (``create_linear()``) and then runs the point pipeline.

    The returned DataFrame carries the input's identifying columns where present
    (``reg_date``, ``mmsi``/``user_id``, ``latitude``, ``longitude``) plus the
    per-point computed columns ``time_diff_hours``, ``distance_km``,
    ``speed_km/h``, ``speed_kn``, ``main_usage``, ``aux_usage`` and
    ``total_usage`` (= ``main_usage + aux_usage``, the value stored per point and
    later rolled up into a grid).

    Empty-result contract (unchanged): the outlier filter + mandatory first-row
    drop mean a track with <= 1 surviving row yields an empty frame.
    """
    if interpolate and not track.empty:
        track = build_interpolated_track(track)

    pollution = get_pollution_data(track, ship)
    pollution["total_usage"] = pollution["main_usage"] + pollution["aux_usage"]
    return pollution


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

        # One code path: Silver per-point compute (compute_pollution) -> grid
        # aggregation over the per-point ``total_usage``, so run_grid's numbers
        # are guaranteed identical to the public compute/aggregate APIs.
        pollution_df = compute_pollution(track, ship, interpolate=interpolate)
        if pollution_df.empty:
            continue

        ship_grid = aggregate_value_to_grid(pollution_df, grid_range, value_col="total_usage")
        grid = grid.add(ship_grid, fill_value=0)

    return grid
