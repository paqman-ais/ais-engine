"""v0.3.0 API consistency tests (ADR-0002 layered data architecture).

These prove the new public APIs are numerically consistent with the existing
batch path (``run_grid``), so the layered Bronze/Silver/Gold pipeline produces
the SAME numbers as the whole-track batch call. The calculation formulas are
frozen ("정답지"); these tests pin the API-surface evolution, not the math.

Cited consistency properties (task section 5):
  1. ``aggregate(compute_pollution(track, ship) by total_usage)`` == ``run_grid``
     grid totals.
  2. Re-binning pre-summed fine cells into a target grid == aggregating the
     underlying points into that grid directly (float tolerance).
  3. ``compute_segment`` over each consecutive pair reproduces
     ``compute_pollution``'s per-row main/aux (clean track, no outliers, so the
     only track-pipeline concern is the mandatory first-row drop).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ais_engine import (
    GridInfo,
    QueryParams,
    ShipParams,
    compute_pollution,
    compute_segment,
    rebin_cells_to_grid,
    run_grid,
)
from ais_engine.grid import GridAggregator, aggregate_value_to_grid
from ais_engine.repository import CSVRepository

FIXTURES = Path(__file__).parent / "fixtures"
TRACK_CSV = FIXTURES / "synthetic_track.csv"
SHIPS_CSV = FIXTURES / "synthetic_ships.csv"

MMSI = 123456789
SHIP = ShipParams(
    mmsi=MMSI,
    total_kw_main_eng=10000.0,
    aux_engine_total_kw=2000.0,
    service_speed=20.0,
    ship_type="Tanker",
)


def _grid_info() -> GridInfo:
    return GridInfo(center_lat=35.0125, center_lon=129.0, radius_km=5.0, grid_size_m=500.0)


def _params() -> QueryParams:
    return QueryParams(
        region=1,
        start_date=datetime(2026, 1, 1, 0, 0, 0),
        end_date=datetime(2026, 1, 1, 23, 59, 59),
        mmsi=MMSI,
    )


def _load_track() -> pd.DataFrame:
    repo = CSVRepository(TRACK_CSV, SHIPS_CSV)
    return repo.get_ais_track(1, MMSI, _params().start_date, _params().end_date)


# --- compute_pollution shape / Silver contract ---------------------------------

def test_compute_pollution_columns_and_total_usage():
    """Silver rows carry the identifying + computed columns, total_usage = main+aux."""
    track = _load_track()
    out = compute_pollution(track, SHIP)
    for col in (
        "reg_date", "latitude", "longitude", "speed_kn",
        "main_usage", "aux_usage", "total_usage",
    ):
        assert col in out.columns, col
    # mmsi is carried through when present in input (here as user_id).
    assert "user_id" in out.columns
    assert np.allclose(
        out["total_usage"].to_numpy(),
        (out["main_usage"] + out["aux_usage"]).to_numpy(),
    )


# --- Property 1: compute_pollution + aggregate == run_grid ----------------------

@pytest.mark.parametrize("interpolate", [False, True])
def test_compute_pollution_then_aggregate_equals_run_grid(interpolate):
    """aggregate(compute_pollution by total_usage) == run_grid grid totals."""
    track = _load_track()
    grid_range = GridAggregator(
        _grid_info().center_lat,
        _grid_info().center_lon,
        _grid_info().radius_km * 1000,
        _grid_info().grid_size_m,
    ).calculate_grid_range()

    silver = compute_pollution(track, SHIP, interpolate=interpolate)
    layered_grid = aggregate_value_to_grid(silver, grid_range, value_col="total_usage")

    repo = CSVRepository(TRACK_CSV, SHIPS_CSV)
    batch_grid = run_grid(repo, _params(), _grid_info(), interpolate=interpolate)

    # Same shape, same per-cell values, same total (frozen formulas, one path).
    pd.testing.assert_frame_equal(layered_grid, batch_grid)
    assert layered_grid.values.sum() == pytest.approx(batch_grid.values.sum())


# --- Property 2: re-bin pre-summed cells == aggregate underlying points ---------

def test_rebin_presummed_cells_equals_direct_point_aggregation():
    """Gold re-bin of fine cells == direct aggregation of underlying points.

    Build a FINE base grid, aggregate the per-point Silver usage into it, then
    materialize each non-empty fine cell as a pre-summed (lat, lon, total_usage)
    row and re-bin into a COARSER target. That must equal aggregating the raw
    points into the target directly, as long as every fine cell lands in the
    same target cell its points do.
    """
    track = _load_track()
    silver = compute_pollution(track, SHIP)

    # Fine base grid (small cells) and a coarser target grid over the same area.
    fine = GridAggregator(35.0125, 129.0, 5000, 250).calculate_grid_range()
    target = GridAggregator(35.0125, 129.0, 5000, 1000).calculate_grid_range()

    # Step A: points -> fine grid (this is what Gold pre-aggregates and stores).
    fine_grid = aggregate_value_to_grid(silver, fine, value_col="total_usage")

    # Materialize non-empty fine cells as pre-summed (lat, lon, value) rows.
    cells = (
        fine_grid.stack()
        .rename("total_usage")
        .reset_index()
        .rename(columns={"level_0": "latitude", "level_1": "longitude"})
    )
    cells = cells[cells["total_usage"] != 0.0].reset_index(drop=True)

    # Step B (Gold re-bin): pre-summed fine cells -> coarse target.
    rebinned = rebin_cells_to_grid(cells, target, value_col="total_usage")

    # Direct: raw points -> coarse target.
    direct = aggregate_value_to_grid(silver, target, value_col="total_usage")

    # Totals must match within float tolerance (no mass lost/created).
    assert rebinned.values.sum() == pytest.approx(direct.values.sum(), rel=1e-9)
    # And cell-for-cell within tolerance.
    np.testing.assert_allclose(rebinned.values, direct.values, atol=1e-12)


# --- Property 3: compute_segment reproduces compute_pollution per-row -----------

def test_compute_segment_reproduces_compute_pollution_per_row():
    """compute_segment over each consecutive pair == compute_pollution per-row.

    The synthetic track is clean (no >30 kn outliers), so the ONLY track-pipeline
    concern is the mandatory first-row drop: compute_pollution's surviving rows
    correspond to consecutive pairs (orig[i-1] -> orig[i]) for i >= 1. We feed
    those same pairs to compute_segment and expect identical main/aux/total.
    """
    track = _load_track().reset_index(drop=True)
    silver = compute_pollution(track, SHIP)

    # No outliers were removed (clean track), so surviving rows are orig[1:].
    assert len(silver) == len(track) - 1

    for i in range(1, len(track)):
        prev = track.iloc[i - 1]
        curr = track.iloc[i]
        seg = compute_segment(
            {
                "latitude": prev["latitude"],
                "longitude": prev["longitude"],
                "sog": prev["sog"],
                "reg_date": prev["reg_date"],
            },
            {
                "latitude": curr["latitude"],
                "longitude": curr["longitude"],
                "sog": curr["sog"],
                "reg_date": curr["reg_date"],
                "time_diff_second": curr["time_diff_second"],
            },
            SHIP,
        )
        row = silver.iloc[i - 1]
        assert seg.main_usage == pytest.approx(row["main_usage"])
        assert seg.aux_usage == pytest.approx(row["aux_usage"])
        assert seg.total_usage == pytest.approx(row["total_usage"])
        assert seg.speed_kn == pytest.approx(row["speed_kn"])
        assert seg.distance_km == pytest.approx(row["distance_km"])


def test_compute_segment_derives_time_diff_from_reg_date():
    """time_diff_second may be omitted when both points carry reg_date."""
    prev = {
        "latitude": 35.0, "longitude": 129.0, "sog": 5.0,
        "reg_date": pd.Timestamp("2026-01-01 00:00:00"),
    }
    curr = {
        "latitude": 35.005, "longitude": 129.0, "sog": 5.0,
        "reg_date": pd.Timestamp("2026-01-01 00:30:00"),
    }
    seg = compute_segment(prev, curr, SHIP)
    assert seg.time_diff_hours == pytest.approx(0.5)
    assert seg.total_usage > 0


def test_compute_segment_requires_time_source():
    """Without time_diff_second AND without reg_date on both points -> error."""
    prev = {"latitude": 35.0, "longitude": 129.0, "sog": 5.0}
    curr = {"latitude": 35.005, "longitude": 129.0, "sog": 5.0}
    with pytest.raises(ValueError):
        compute_segment(prev, curr, SHIP)


def test_compute_segment_zeroing_gates_match_formula():
    """Per-segment zeroing matches the frozen gates (main: stationary OR gap)."""
    # Large gap (>=1 h) zeroes main; aux only zeroed if also moving (sog>0.3).
    prev = {
        "latitude": 35.0, "longitude": 129.0, "sog": 5.0,
        "reg_date": pd.Timestamp("2026-01-01 00:00:00"),
    }
    curr = {
        "latitude": 35.05, "longitude": 129.0, "sog": 5.0,
        "reg_date": pd.Timestamp("2026-01-01 02:00:00"),  # 2 h gap
        "time_diff_second": 7200.0,
    }
    seg = compute_segment(prev, curr, SHIP)
    assert seg.main_usage == 0.0          # large gap -> main zeroed
    assert seg.aux_usage == 0.0           # moving (sog>0.3) AND large gap -> 0


# --- Housekeeping: v0.3 public surface ------------------------------------------

def test_v3_public_surface_and_version():
    """Public surface lock — bump expected version + new-name set on each release.

    The lock prevents accidental removal of exported names. When a release adds
    names, append them below; when it bumps the version, update the literal.
    """
    import ais_engine

    assert ais_engine.__version__ == "0.6.0"
    # v0.3 additions are exported.
    for name in ("compute_pollution", "rebin_cells_to_grid", "compute_segment", "SegmentUsage"):
        assert name in ais_engine.__all__, name
        assert hasattr(ais_engine, name), name
    # v0.5 additions (fuel -> pollutant emissions in kg, IMO defaults).
    for name in (
        "compute_emissions_kg", "add_emission_columns", "EmissionKg", "POLLUTANTS",
        "EMISSION_FACTOR_NOX_KG_PER_TON", "EMISSION_FACTOR_SOX_KG_PER_TON",
        "EMISSION_FACTOR_PM_KG_PER_TON", "EMISSION_FACTOR_CO2_KG_PER_TON",
    ):
        assert name in ais_engine.__all__, name
        assert hasattr(ais_engine, name), name
    # v0.6 additions (speed → operational mode label).
    for name in (
        "classify_mode", "add_mode_column", "MODES",
        "MODE_CRUISING", "MODE_SLOW_STEAMING", "MODE_HOTELING",
    ):
        assert name in ais_engine.__all__, name
        assert hasattr(ais_engine, name), name
    # v0.2 surface is preserved.
    for name in (
        "run_grid", "GridInfo", "QueryParams", "AISRepository",
        "InMemoryRepository", "CSVRepository", "ShipParams", "GridRange",
        "KN_TO_KM", "KM_TO_KN", "SFOC_MULTIPLIER", "AUX_USAGE_FACTOR",
    ):
        assert name in ais_engine.__all__, name
