"""Self-consistency tests + a documented harness for a REAL server golden.

WHAT THIS IS / IS NOT
---------------------
This module is a **self-consistency** test, NOT a verified golden regression.
``_expected_total_no_interp`` re-derives the expected total with the *same*
formulas the engine uses (cubic main load factor, aux load factor keyed on the
position-derived ``speed_kn``, the zeroing gates, etc.). It therefore pins that
the assembled pipeline matches the documented per-point math and catches drift
(e.g. an accidental revert of the aux load factor back to ``sog``), but it can
NOT prove faithfulness to the verified server output — both sides share the same
formulas, so a formula that is wrong in the same way on both sides would still
pass. Do not read these passing tests as "verified faithful to the server".

PLUGGING IN A REAL GOLDEN (TODO)
--------------------------------
The verified Jupyter server produces real golden outputs at:

    ~/lab/grid_output/*.xlsx          (final grid, per region/mmsi/date range)
    중간계산(보간x).xlsx               (per-point intermediate calc, no interp)

To turn this into a *real* golden regression:
  1. Drop a captured ``grid_output/<...>_선형보간x.xlsx`` into ``tests/fixtures/``.
  2. Drop the matching raw ``ais_new2`` export as ``tests/fixtures/<name>.csv``
     and the ``ship_info`` row(s) as ``tests/fixtures/<ships>.csv``.
  3. Load the golden grid with ``pd.read_excel(..., index_col=0)`` and compare to
     ``run_grid(CSVRepository(...), params, grid_info)`` via
     ``pandas.testing.assert_frame_equal`` (with an ``atol`` tolerance). A ready
     skeleton is provided in :func:`test_real_golden_regression` (skipped until
     the fixture exists).

Until that fixture is committed, the self-consistency total below is the
strongest claim this suite makes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from geopy.distance import geodesic

from ais_engine import constants as C
from ais_engine.fuel import get_sfoc
from ais_engine.pipeline import GridInfo, QueryParams, run_grid
from ais_engine.repository import CSVRepository

FIXTURES = Path(__file__).parent / "fixtures"
TRACK_CSV = FIXTURES / "synthetic_track.csv"
SHIPS_CSV = FIXTURES / "synthetic_ships.csv"

# Real golden fixtures (not committed yet — see module docstring / TODO).
GOLDEN_GRID_XLSX = FIXTURES / "golden_grid_선형보간x.xlsx"
GOLDEN_TRACK_CSV = FIXTURES / "golden_track.csv"
GOLDEN_SHIPS_CSV = FIXTURES / "golden_ships.csv"

# Synthetic ship (must match synthetic_ships.csv).
MAIN_KW = 10000.0
AUX_KW = 2000.0
SERVICE_SPEED = 20.0
SHIP_TYPE = "Tanker"


def _expected_total_no_interp() -> float:
    """Self-consistency total for the synthetic track, no interpolation.

    Reproduces the engine's documented per-point math by hand so the test pins
    the assembled pipeline against the spec formulas:

      - 6 points, 30 min apart (time_diff_hours = 0.5)
      - first row dropped after distance/speed computed; no speed_kn > 30 here
      - main load factor: cubic on position-derived speed_km/h
      - aux load factor: keyed on the position-derived ``speed_kn`` (NOT ``sog``)
        — faithful to ais_module.py:113. ``sog`` only drives the zeroing gate.

    This is NOT a verified golden (it shares formulas with the engine); see the
    module docstring.
    """
    lats = [35.00000, 35.00500, 35.01000, 35.01500, 35.02000, 35.02500]
    sogs = [5.0, 5.0, 5.0, 5.0, 5.0, 0.1]
    lon = 129.0
    dt_hours = 0.5

    total = 0.0
    # The pipeline drops the very first row after computing diffs, so usage is
    # accumulated for rows index 1..5 (0-based) of the original track.
    for i in range(1, len(lats)):
        dist_km = geodesic((lats[i - 1], lon), (lats[i], lon)).kilometers
        speed_kmh = dist_km / dt_hours
        speed_kn = speed_kmh * C.KM_TO_KN
        sog = sogs[i]

        # main usage (zero if speed_kn<=0.3 or dt>=1; neither happens here)
        if speed_kn <= C.STATIONARY_SPEED_KN or dt_hours >= C.LARGE_GAP_HOURS:
            main = 0.0
        else:
            lf = (speed_kmh / (SERVICE_SPEED * C.KN_TO_KM)) ** 3
            main = MAIN_KW * lf * dt_hours * get_sfoc(MAIN_KW) * C.SFOC_MULTIPLIER

        # aux load factor keyed on speed_kn (faithful), zeroing gate keyed on sog
        if speed_kn >= C.AUX_SPEED_HIGH_KN:
            aux_lf = C.AUX_LF_HIGH
        elif speed_kn >= C.STATIONARY_SOG_KN:
            aux_lf = C.AUX_LF_MID
        else:
            aux_lf = C.AUX_LF_LOW_TANKER_PAX  # Tanker, speed_kn < 0.3
        # aux usage zeroed only if sog>0.3 AND dt>=1; dt<1 so never zeroed here
        if sog > C.STATIONARY_SOG_KN and dt_hours >= C.LARGE_GAP_HOURS:
            aux = 0.0
        else:
            aux = AUX_KW * aux_lf * dt_hours * C.AUX_USAGE_FACTOR

        total += main + aux
    return total


def _grid_info() -> GridInfo:
    # Radius large enough to contain the whole ~2.8 km track.
    return GridInfo(center_lat=35.0125, center_lon=129.0, radius_km=5.0, grid_size_m=500.0)


def _params() -> QueryParams:
    return QueryParams(
        region=1,
        start_date=datetime(2026, 1, 1, 0, 0, 0),
        end_date=datetime(2026, 1, 1, 23, 59, 59),
        mmsi=123456789,
    )


def test_self_consistency_no_interp_total():
    """Self-consistency (NOT a verified golden): pipeline == documented math."""
    repo = CSVRepository(TRACK_CSV, SHIPS_CSV)
    grid = run_grid(repo, _params(), _grid_info(), interpolate=False)
    assert grid.values.sum() == pytest.approx(_expected_total_no_interp(), rel=1e-9)


def test_regression_grid_is_deterministic():
    repo = CSVRepository(TRACK_CSV, SHIPS_CSV)
    g1 = run_grid(repo, _params(), _grid_info(), interpolate=False)
    g2 = run_grid(repo, _params(), _grid_info(), interpolate=False)
    pd.testing.assert_frame_equal(g1, g2)


def test_interpolated_total_is_positive_and_finite():
    repo = CSVRepository(TRACK_CSV, SHIPS_CSV)
    grid = run_grid(repo, _params(), _grid_info(), interpolate=True)
    total = grid.values.sum()
    assert total > 0
    assert np.isfinite(total)


def test_unknown_ship_yields_empty_grid():
    repo = CSVRepository(TRACK_CSV, SHIPS_CSV)
    params = QueryParams(
        region=1,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 2),
        mmsi=999999999,  # not in ships fixture
    )
    grid = run_grid(repo, params, _grid_info(), interpolate=False)
    assert grid.values.sum() == pytest.approx(0.0)


@pytest.mark.skipif(
    not GOLDEN_GRID_XLSX.exists(),
    reason="Real server golden not committed yet (see module docstring TODO).",
)
def test_real_golden_regression():
    """REAL golden regression — runs only once the golden fixtures exist.

    Drop ``golden_grid_선형보간x.xlsx`` (captured from ~/lab/grid_output/) plus the
    matching ``golden_track.csv`` (ais_new2 export) and ``golden_ships.csv``
    (ship_info row) into tests/fixtures/, then fill in the params/grid_info the
    server used. This is the test that would justify a "verified faithful" claim.
    """
    repo = CSVRepository(GOLDEN_TRACK_CSV, GOLDEN_SHIPS_CSV)
    # TODO: set params/grid_info to match the captured golden run.
    params = _params()
    grid_info = _grid_info()
    produced = run_grid(repo, params, grid_info, interpolate=False)
    golden = pd.read_excel(GOLDEN_GRID_XLSX, index_col=0)
    golden.columns = [float(c) for c in golden.columns]
    pd.testing.assert_frame_equal(produced, golden, atol=1e-6, check_dtype=False)
