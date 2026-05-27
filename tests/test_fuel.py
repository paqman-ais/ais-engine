"""Unit tests for pure fuel-usage calculations.

Each test cites the spec section it pins
(``logic-spec/01-core-emission-grid-logic.md``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ais_engine import constants as C
from ais_engine.fuel import (
    calculate_distance,
    get_aux_load_factor,
    get_aux_usage,
    get_load_factor,
    get_main_usage,
    get_pollution_data,
    get_sfoc,
)
from ais_engine.models import ShipParams


# --- SFOC thresholds (spec section 2 + the CORRECTED mapping from section 6) ---

@pytest.mark.parametrize(
    "main_kw, expected",
    [
        (20000, 175),   # > 15000 -> 175
        (15001, 175),   # just above 15000 -> 175
        (15000, 185),   # boundary inclusive in 5000..15000 -> 185
        (10000, 185),   # mid range -> 185
        (5000, 185),    # boundary inclusive -> 185
        (4999, 195),    # just below 5000 -> 195
        (1000, 195),    # < 5000 -> 195
    ],
)
def test_sfoc_corrected_mapping(main_kw, expected):
    assert get_sfoc(main_kw) == expected


def test_sfoc_is_not_inverted():
    """Guard against the January bug (which had >=15000 -> 195, <5000 -> 175).

    Large engines must be MORE efficient (lower SFOC) than small ones.
    """
    assert get_sfoc(20000) < get_sfoc(1000)
    assert get_sfoc(20000) == 175
    assert get_sfoc(1000) == 195


# --- Auxiliary load-factor branches (spec section 2) ---

def test_aux_load_factor_branches_non_tanker():
    sog = pd.Series([12.0, 10.0, 5.0, 0.3, 0.1])
    lf = get_aux_load_factor(sog, "Cargo")
    # >=10 -> 0.3 ; 0.3<=sog<10 -> 0.5 ; <0.3 (non-tanker/pax) -> 0.4
    assert list(lf) == [C.AUX_LF_HIGH, C.AUX_LF_HIGH, C.AUX_LF_MID, C.AUX_LF_MID, C.AUX_LF_LOW_OTHER]


def test_aux_load_factor_low_tanker_and_passenger():
    sog = pd.Series([0.0])
    assert get_aux_load_factor(sog, "Tanker").iloc[0] == C.AUX_LF_LOW_TANKER_PAX
    assert get_aux_load_factor(sog, "Passenger Ship").iloc[0] == C.AUX_LF_LOW_TANKER_PAX
    assert get_aux_load_factor(sog, "Bulk Carrier").iloc[0] == C.AUX_LF_LOW_OTHER


# --- Main-engine cubic load factor (spec section 3.6) ---

def test_load_factor_cubic_formula():
    # At speed == service_speed_in_kmh, load factor == 1.0.
    service_speed_kn = 20.0
    speed_kmh = pd.Series([service_speed_kn * C.KN_TO_KM])
    lf = get_load_factor(speed_kmh, service_speed_kn)
    assert lf.iloc[0] == pytest.approx(1.0)

    # Half the design speed -> (0.5)**3 = 0.125.
    speed_half = pd.Series([0.5 * service_speed_kn * C.KN_TO_KM])
    assert get_load_factor(speed_half, service_speed_kn).iloc[0] == pytest.approx(0.125)


# --- Distance / speed (spec section 3.3-3.4) ---

def test_calculate_distance_none_is_zero():
    assert calculate_distance(None, 1.0, 2.0, 3.0) == 0.0


def test_calculate_distance_positive():
    # ~1 degree of latitude is ~111 km.
    d = calculate_distance(35.0, 129.0, 36.0, 129.0)
    assert 110 < d < 112


# --- Main usage zeroing: stationary or large gap (spec section 3.6) ---

def test_main_usage_zero_when_stationary_or_gap():
    ship = ShipParams(1, total_kw_main_eng=10000, aux_engine_total_kw=2000,
                      service_speed=20.0, ship_type="Cargo")
    df = pd.DataFrame(
        {
            "speed_km/h": [37.04, 37.04, 0.1, 37.04],
            "speed_kn": [20.0, 20.0, 0.05, 20.0],     # row 2: <=0.3 stationary
            "time_diff_hours": [0.5, 1.0, 0.5, 0.5],  # row 1: >=1 large gap
            "sog": [20.0, 20.0, 0.05, 20.0],
        }
    )
    out = get_main_usage(ship, df.copy())
    assert out["main_usage"].iloc[0] > 0       # normal
    assert out["main_usage"].iloc[1] == 0      # large gap
    assert out["main_usage"].iloc[2] == 0      # stationary
    assert out["main_usage"].iloc[3] > 0       # normal


def test_main_usage_matches_explicit_formula():
    ship = ShipParams(1, total_kw_main_eng=10000, aux_engine_total_kw=2000,
                      service_speed=20.0, ship_type="Cargo")
    df = pd.DataFrame(
        {"speed_km/h": [18.52], "speed_kn": [10.0], "time_diff_hours": [0.5], "sog": [10.0]}
    )
    out = get_main_usage(ship, df.copy())
    lf = (18.52 / (20.0 * C.KN_TO_KM)) ** 3
    expected = 10000 * lf * 0.5 * get_sfoc(10000) * C.SFOC_MULTIPLIER
    assert out["main_usage"].iloc[0] == pytest.approx(expected)


# --- Aux usage zeroing: moving AND large gap (spec section 3.7) ---

def test_aux_usage_zero_only_when_moving_and_gap():
    ship = ShipParams(1, total_kw_main_eng=10000, aux_engine_total_kw=2000,
                      service_speed=20.0, ship_type="Tanker")
    df = pd.DataFrame(
        {
            "sog": [5.0, 5.0, 0.1],
            "time_diff_hours": [1.0, 0.5, 1.0],
            "speed_kn": [5.0, 5.0, 0.1],
        }
    )
    out = get_aux_usage(ship, df.copy())
    assert out["aux_usage"].iloc[0] == 0       # moving (sog>0.3) AND gap>=1 -> 0
    assert out["aux_usage"].iloc[1] > 0        # moving but small gap -> nonzero
    # stationary with a large gap is NOT zeroed (condition is AND on sog>0.3):
    assert out["aux_usage"].iloc[2] > 0


def test_aux_usage_matches_explicit_formula():
    ship = ShipParams(1, total_kw_main_eng=10000, aux_engine_total_kw=2000,
                      service_speed=20.0, ship_type="Cargo")
    df = pd.DataFrame({"sog": [5.0], "time_diff_hours": [0.5], "speed_kn": [5.0]})
    out = get_aux_usage(ship, df.copy())
    expected = 2000 * C.AUX_LF_MID * 0.5 * C.AUX_USAGE_FACTOR
    assert out["aux_usage"].iloc[0] == pytest.approx(expected)


# --- Point pipeline: outlier removal + first-row drop (spec section 3.5) ---

def test_get_pollution_data_drops_outlier_and_first_row():
    ship = ShipParams(1, total_kw_main_eng=10000, aux_engine_total_kw=2000,
                      service_speed=20.0, ship_type="Cargo")
    # 5 points 0.5h apart, all ~1.85 km steps (~2 kn) except an injected outlier
    # jump that exceeds 30 kn.
    times = pd.to_datetime(
        ["2026-01-01 00:00:00", "2026-01-01 00:30:00", "2026-01-01 01:00:00",
         "2026-01-01 01:30:00", "2026-01-01 02:00:00"]
    )
    df = pd.DataFrame(
        {
            "latitude": [35.0, 35.01, 35.02, 40.0, 40.01],  # row 3 is a huge jump
            "longitude": [129.0, 129.0, 129.0, 129.0, 129.0],
            "sog": [2.0, 2.0, 2.0, 2.0, 2.0],
            "reg_date": times,
        }
    )
    df["time_diff_second"] = df["reg_date"].diff().dt.total_seconds()
    out = get_pollution_data(df, ship)
    # outlier row (speed_kn>30) removed, then first remaining row dropped.
    assert (out["speed_kn"] <= C.MAX_SPEED_LIMIT_KN).all()
    assert "main_usage" in out.columns and "aux_usage" in out.columns
    assert "is_outlier" not in out.columns


# --- Aux load factor uses speed_kn, NOT sog (spec section 2, review 2026-05-27) ---

def test_aux_usage_load_factor_uses_speed_kn_not_sog():
    """PIN: aux load factor is keyed on the position-derived ``speed_kn``.

    Faithful to ``ais_module.py:113`` (the call passes ``speed_kn``). This test
    MUST FAIL if anyone reverts the load-factor input to ``sog``.

    Construct two rows with the SAME ``speed_kn`` (12 kn -> AUX_LF_HIGH) but very
    different ``sog`` (0.1 vs 12). If the load factor were keyed on ``sog`` the
    two rows would use different factors (0.6 Tanker-low vs 0.3 high); keyed on
    ``speed_kn`` they are identical. Neither row is zeroed (time_diff_hours<1).
    """
    ship = ShipParams(1, total_kw_main_eng=10000, aux_engine_total_kw=2000,
                      service_speed=20.0, ship_type="Tanker")
    df = pd.DataFrame(
        {
            "sog": [0.1, 12.0],          # would pick 0.6 vs 0.3 if sog-keyed
            "speed_kn": [12.0, 12.0],    # both HIGH branch (0.3) when speed-keyed
            "time_diff_hours": [0.5, 0.5],
        }
    )
    out = get_aux_usage(ship, df.copy())
    # Both rows use AUX_LF_HIGH because the factor is keyed on speed_kn.
    expected = 2000 * C.AUX_LF_HIGH * 0.5 * C.AUX_USAGE_FACTOR
    assert out["aux_usage"].iloc[0] == pytest.approx(expected)
    assert out["aux_usage"].iloc[1] == pytest.approx(expected)
    # And explicitly: the two rows are EQUAL despite different sog.
    assert out["aux_usage"].iloc[0] == pytest.approx(out["aux_usage"].iloc[1])
    # Sanity: this is NOT the sog-keyed value for row 0 (0.6 Tanker-low branch).
    sog_keyed_row0 = 2000 * C.AUX_LF_LOW_TANKER_PAX * 0.5 * C.AUX_USAGE_FACTOR
    assert out["aux_usage"].iloc[0] != pytest.approx(sog_keyed_row0)


def test_get_pollution_data_aux_lf_keyed_on_speed_kn_end_to_end():
    """End-to-end PIN through get_pollution_data: aux LF follows speed_kn.

    A fast position move (>10 kn position-derived) with a reported sog of 0.1
    must use AUX_LF_HIGH (0.3), not the sog<0.3 Tanker branch (0.6).
    """
    ship = ShipParams(1, total_kw_main_eng=10000, aux_engine_total_kw=2000,
                      service_speed=20.0, ship_type="Tanker")
    # ~0.18 deg lat over 0.5 h ~= 20 km / 0.5 h = 40 km/h ~= 21.6 kn (>10, <30).
    times = pd.to_datetime(
        ["2026-01-01 00:00:00", "2026-01-01 00:30:00", "2026-01-01 01:00:00"]
    )
    df = pd.DataFrame(
        {
            "latitude": [35.0, 35.18, 35.36],
            "longitude": [129.0, 129.0, 129.0],
            "sog": [0.1, 0.1, 0.1],   # low sog but fast position move
            "reg_date": times,
        }
    )
    df["time_diff_second"] = df["reg_date"].diff().dt.total_seconds()
    out = get_pollution_data(df, ship)
    assert (out["speed_kn"] > C.AUX_SPEED_HIGH_KN).all()      # genuinely >10 kn
    assert (out["speed_kn"] <= C.MAX_SPEED_LIMIT_KN).all()    # not outliers
    expected = 2000 * C.AUX_LF_HIGH * out["time_diff_hours"] * C.AUX_USAGE_FACTOR
    assert out["aux_usage"].to_numpy() == pytest.approx(expected.to_numpy())


# --- Robustness guard: dt=0 / duplicate position -> no NaN (review HIGH) ---

def test_get_pollution_data_duplicate_timestamp_no_nan():
    """0/0 (duplicate position + same timestamp) must not NaN-poison the grid.

    A duplicate point yields distance_km=0 and time_diff_hours=0 -> 0/0 = NaN.
    The guard replaces non-finite speeds with 0 BEFORE the >30 outlier filter,
    so the row is treated as stationary and the totals stay finite.
    """
    ship = ShipParams(1, total_kw_main_eng=10000, aux_engine_total_kw=2000,
                      service_speed=20.0, ship_type="Cargo")
    # Rows 2 and 3 share the SAME position (distance 0); row 3 also has a 0s gap.
    times = pd.to_datetime(
        ["2026-01-01 00:00:00", "2026-01-01 00:30:00",
         "2026-01-01 01:00:00", "2026-01-01 01:00:00"]
    )
    df = pd.DataFrame(
        {
            "latitude": [35.0, 35.005, 35.010, 35.010],
            "longitude": [129.0, 129.0, 129.0, 129.0],
            "sog": [2.0, 2.0, 2.0, 2.0],
            "reg_date": times,
        }
    )
    df["time_diff_second"] = df["reg_date"].diff().dt.total_seconds()
    out = get_pollution_data(df, ship)
    assert np.isfinite(out["speed_km/h"]).all()
    assert np.isfinite(out["speed_kn"]).all()
    assert np.isfinite(out["main_usage"]).all()
    assert np.isfinite(out["aux_usage"]).all()
    total = (out["main_usage"] + out["aux_usage"]).sum()
    assert np.isfinite(total)


# --- Degenerate tracks: empty / single-point / all-outliers (review HIGH) ---

def _empty_track() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "latitude": pd.Series([], dtype=float),
            "longitude": pd.Series([], dtype=float),
            "sog": pd.Series([], dtype=float),
            "time_diff_second": pd.Series([], dtype=float),
        }
    )


def test_get_pollution_data_empty_track():
    ship = ShipParams(1, 10000, 2000, 20.0, "Cargo")
    out = get_pollution_data(_empty_track(), ship)
    assert out.empty


def test_get_pollution_data_single_point_is_empty_after_first_row_drop():
    """A 1-point track is empty after the mandatory first-row drop."""
    ship = ShipParams(1, 10000, 2000, 20.0, "Cargo")
    df = pd.DataFrame(
        {
            "latitude": [35.0],
            "longitude": [129.0],
            "sog": [2.0],
            "time_diff_second": [np.nan],  # diff() of a single row is NaN
        }
    )
    out = get_pollution_data(df, ship)
    assert out.empty


def test_get_pollution_data_all_outliers_is_empty():
    """Every row a >30 kn outlier -> all removed -> empty (after first-row drop)."""
    ship = ShipParams(1, 10000, 2000, 20.0, "Cargo")
    # Huge jumps every 60 s -> way over 30 kn.
    times = pd.to_datetime(
        ["2026-01-01 00:00:00", "2026-01-01 00:01:00",
         "2026-01-01 00:02:00", "2026-01-01 00:03:00"]
    )
    df = pd.DataFrame(
        {
            "latitude": [35.0, 40.0, 35.0, 40.0],
            "longitude": [129.0, 129.0, 129.0, 129.0],
            "sog": [2.0, 2.0, 2.0, 2.0],
            "reg_date": times,
        }
    )
    df["time_diff_second"] = df["reg_date"].diff().dt.total_seconds()
    out = get_pollution_data(df, ship)
    assert out.empty
