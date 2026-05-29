"""Unit tests for the speed-based operational-mode classifier.

Pins the three thresholds from legacy ALGORITHM.md section 2.3:
  - cruising      : speed_kn >= 10
  - slow_steaming : 0.3 <= speed_kn < 10
  - hoteling      : speed_kn < 0.3  (and NaN/None default here)
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from ais_engine import constants as C
from ais_engine.mode import (
    MODE_CRUISING,
    MODE_HOTELING,
    MODE_SLOW_STEAMING,
    MODES,
    add_mode_column,
    classify_mode,
)


# --- Scalar API ---


@pytest.mark.parametrize(
    "speed,expected",
    [
        # cruising boundary
        (10.0, MODE_CRUISING),     # exactly 10 -> cruising
        (10.01, MODE_CRUISING),
        (25.0, MODE_CRUISING),
        # slow_steaming
        (9.99, MODE_SLOW_STEAMING),
        (5.0, MODE_SLOW_STEAMING),
        (0.3, MODE_SLOW_STEAMING),  # exactly 0.3 -> slow_steaming
        # hoteling
        (0.29, MODE_HOTELING),
        (0.0, MODE_HOTELING),
        (-1.0, MODE_HOTELING),     # nonsense negative also drops here
    ],
)
def test_classify_mode_thresholds(speed, expected):
    assert classify_mode(speed) == expected


def test_classify_mode_handles_none_and_nan():
    assert classify_mode(None) == MODE_HOTELING
    assert classify_mode(float("nan")) == MODE_HOTELING
    assert classify_mode(math.nan) == MODE_HOTELING


def test_modes_constant_lists_all_three():
    assert set(MODES) == {MODE_CRUISING, MODE_SLOW_STEAMING, MODE_HOTELING}
    assert len(MODES) == 3


def test_classify_mode_thresholds_match_constants():
    # Catches a future drift where someone bumps AUX_SPEED_HIGH_KN /
    # STATIONARY_SOG_KN in constants.py but forgets the mode classifier.
    assert classify_mode(C.AUX_SPEED_HIGH_KN) == MODE_CRUISING
    assert classify_mode(C.AUX_SPEED_HIGH_KN - 0.01) == MODE_SLOW_STEAMING
    assert classify_mode(C.STATIONARY_SOG_KN) == MODE_SLOW_STEAMING
    assert classify_mode(C.STATIONARY_SOG_KN - 0.01) == MODE_HOTELING


# --- DataFrame API ---


def test_add_mode_column_basic():
    df = pd.DataFrame({"speed_kn": [12.0, 5.0, 0.1]})
    out = add_mode_column(df)
    assert list(out["mode"]) == [MODE_CRUISING, MODE_SLOW_STEAMING, MODE_HOTELING]


def test_add_mode_column_does_not_mutate():
    df = pd.DataFrame({"speed_kn": [1.0]})
    cols_before = list(df.columns)
    _ = add_mode_column(df)
    assert list(df.columns) == cols_before


def test_add_mode_column_nan_falls_to_hoteling():
    df = pd.DataFrame({"speed_kn": [np.nan, 12.0]})
    out = add_mode_column(df)
    assert out["mode"].iloc[0] == MODE_HOTELING
    assert out["mode"].iloc[1] == MODE_CRUISING


def test_add_mode_column_custom_columns():
    df = pd.DataFrame({"my_speed": [11.0, 0.5]})
    out = add_mode_column(df, speed_col="my_speed", mode_col="activity")
    assert list(out["activity"]) == [MODE_CRUISING, MODE_SLOW_STEAMING]
    assert "mode" not in out.columns


def test_add_mode_column_empty_frame():
    df = pd.DataFrame({"speed_kn": pd.Series([], dtype="float64")})
    out = add_mode_column(df)
    assert len(out) == 0
    assert "mode" in out.columns


def test_add_mode_column_matches_scalar_classifier():
    # Vectorized + scalar must agree row-by-row.
    speeds = [25.0, 10.0, 9.99, 5.0, 0.3, 0.29, 0.0, np.nan]
    df = pd.DataFrame({"speed_kn": speeds})
    out = add_mode_column(df)
    for sp, m in zip(speeds, out["mode"]):
        scalar = classify_mode(float(sp) if not (isinstance(sp, float) and math.isnan(sp)) else None)
        assert m == scalar, f"speed={sp}: vectorized={m}, scalar={scalar}"
