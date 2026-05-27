"""Unit tests for linear-interpolation preprocessing (spec section 5).

Pins the gap-break behaviour (a gap > INTERP_GAP_THRESHOLD_SECONDS is never
bridged by interpolation) and one exact value-level interpolation assertion.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ais_engine import constants as C
from ais_engine.interpolation import (
    build_interpolated_track,
    resample_and_interpolate_fast_sog,
)


def test_resample_interpolates_to_1s_with_pinned_midpoint():
    """A moving segment resamples to 1s and linearly interpolates positions.

    Two points 4 s apart (35.0000 -> 35.0004 lat) yield 5 rows at 1s spacing and
    a midpoint (t=2s) latitude of exactly 35.0002.
    """
    times = pd.to_datetime(["2026-01-01 00:00:00", "2026-01-01 00:00:04"])
    df = pd.DataFrame(
        {
            "reg_date": times,
            "latitude": [35.0000, 35.0004],
            "longitude": [129.0, 129.0],
            "sog": [5.0, 5.0],
            "time_diff_second": [None, 4.0],
        }
    )
    out = resample_and_interpolate_fast_sog(df.copy())
    assert len(out) == 5  # 0,1,2,3,4 seconds
    midpoint = out.loc[out["reg_date"] == pd.Timestamp("2026-01-01 00:00:02"), "latitude"]
    assert midpoint.iloc[0] == pytest.approx(35.0002)


def test_resample_does_not_bridge_large_gap():
    """A gap > INTERP_GAP_THRESHOLD_SECONDS splits the segment (no bridging).

    Two 2-second clusters 3 hours apart must resample independently (3+3 rows),
    NOT bridge the 3-hour gap (which would generate ~10,800 rows).
    """
    assert C.INTERP_GAP_THRESHOLD_SECONDS == 3600
    times = pd.to_datetime(
        [
            "2026-01-01 00:00:00",
            "2026-01-01 00:00:02",
            "2026-01-01 03:00:00",
            "2026-01-01 03:00:02",
        ]
    )
    df = pd.DataFrame(
        {
            "reg_date": times,
            "latitude": [35.0000, 35.0002, 36.0000, 36.0002],
            "longitude": [129.0, 129.0, 129.0, 129.0],
            "sog": [5.0, 5.0, 5.0, 5.0],
        }
    )
    df["time_diff_second"] = df["reg_date"].diff().dt.total_seconds()
    out = resample_and_interpolate_fast_sog(df.copy())
    # Each 2 s cluster -> 3 rows (0,1,2 s); the 3-hour gap is NOT filled.
    assert len(out) == 6
    # No timestamps invented inside the gap.
    assert not (
        (out["reg_date"] > pd.Timestamp("2026-01-01 00:00:02"))
        & (out["reg_date"] < pd.Timestamp("2026-01-01 03:00:00"))
    ).any()


def test_build_interpolated_track_splits_moving_and_stationary():
    """Moving (sog>0.3) groups are resampled; stationary groups pass through.

    A 3-point moving run (2 s spacing) then a stationary point: the moving run
    is densified to 1s while the stationary tail is kept as a single raw row.
    """
    times = pd.to_datetime(
        [
            "2026-01-01 00:00:00",
            "2026-01-01 00:00:02",
            "2026-01-01 00:00:04",
            "2026-01-01 00:10:00",
        ]
    )
    df = pd.DataFrame(
        {
            "reg_date": times,
            "latitude": [35.0000, 35.0002, 35.0004, 35.0004],
            "longitude": [129.0, 129.0, 129.0, 129.0],
            "sog": [5.0, 5.0, 5.0, 0.0],  # last point stationary
        }
    )
    # The reference computes time_diff_second (via get_ais_data) before the
    # moving/stationary split, so each group carries it into resampling.
    df["time_diff_second"] = df["reg_date"].diff().dt.total_seconds()
    out = build_interpolated_track(df)
    # Moving run densified to 1s (5 rows: 0..4 s) + 1 stationary row = 6 rows.
    assert len(out) == 6
    assert "time_diff_second" in out.columns
    # recomputed from the recombined reg_date diff; first row is NaN.
    assert out["time_diff_second"].iloc[0] != out["time_diff_second"].iloc[0]  # NaN
    assert out["time_diff_second"].iloc[1] == pytest.approx(1.0)
