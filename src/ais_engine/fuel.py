"""Pure fuel-usage calculations (no DB, no I/O).

Faithful port of ``reference/legacy-jupyter/ais_modules/ais_module.py`` and the
point pipeline in ``ais_grid_module.getPollutionData``.

Spec reference: ``logic-spec/01-core-emission-grid-logic.md`` sections 2-3.

Everything here operates on plain pandas DataFrames + a :class:`ShipParams`,
so it is fully unit-testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from geopy.distance import geodesic

from .constants import (
    AUX_LF_HIGH,
    AUX_LF_LOW_OTHER,
    AUX_LF_LOW_TANKER_PAX,
    AUX_LF_MID,
    AUX_SPEED_HIGH_KN,
    AUX_USAGE_FACTOR,
    KM_TO_KN,
    KN_TO_KM,
    LARGE_GAP_HOURS,
    MAX_SPEED_LIMIT_KN,
    SFOC_MULTIPLIER,
    STATIONARY_SOG_KN,
    STATIONARY_SPEED_KN,
)
from .models import ShipParams


def get_load_factor(speed_kmh: pd.Series, service_speed_kn: float) -> pd.Series:
    """Main-engine cubic load factor.

    ``(speed_km/h / (service_speed_kn * KN_TO_KM)) ** 3``  (spec section 3.6).

    Note: faithful to the reference, the divisor uses ``service_speed * 1.852``
    so the design speed (given in knots) is converted to km/h before the ratio.
    """
    cal = speed_kmh / (service_speed_kn * KN_TO_KM)
    return np.power(cal, 3)


def get_sfoc(main_eng_kw: float) -> int:
    """Main-engine SFOC (g/kWh) by engine power.

    VERIFIED / CORRECT mapping (spec section 2 + section 6):

        main engine kW  > 15000  -> 175
                 5000 .. 15000   -> 185
                       < 5000    -> 195

    The January reimplementation INVERTED this (it returned 195 for >=15000 and
    175 for <5000). Larger engines are more efficient, so a *lower* SFOC for
    high power is the physically correct behavior. This port keeps the verified
    mapping below.
    """
    if main_eng_kw > 15000:
        return 175
    elif 5000 <= main_eng_kw <= 15000:
        return 185
    elif main_eng_kw < 5000:
        return 195
    return 0


def _aux_factor_scalar(speed_kn: float, ship_type: str) -> float:
    """Auxiliary load factor for a single ``speed_kn`` value (spec section 2).

    The input is the position-derived ``speed_kn``, NOT the AIS ``sog`` (see
    :func:`get_aux_load_factor`).
    """
    if speed_kn >= AUX_SPEED_HIGH_KN:
        return AUX_LF_HIGH
    elif STATIONARY_SOG_KN <= speed_kn < AUX_SPEED_HIGH_KN:
        return AUX_LF_MID
    elif speed_kn < STATIONARY_SOG_KN:
        if "Tanker" in ship_type or "Passenger" in ship_type:
            return AUX_LF_LOW_TANKER_PAX
        return AUX_LF_LOW_OTHER
    return 0.0


def get_aux_load_factor(speed_kn: pd.Series, ship_type: str) -> pd.Series:
    """Vectorized auxiliary load factor (faithful to ``get_aux_load_factor``).

    IMPORTANT (spec section 2, code review 2026-05-27): the reference function's
    parameter is misleadingly named ``sog``, but the actual call site passes the
    position-derived ``speed_kn`` (``ais_module.py:113``). This port matches that
    behavior: the load-factor input is ``speed_kn``. ``sog`` is used ONLY for the
    aux zeroing gate in :func:`get_aux_usage`.
    """
    return speed_kn.apply(lambda s: _aux_factor_scalar(s, ship_type))


def get_main_usage(ship: ShipParams, df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with a ``main_usage`` (tonnes) column added.

    Does NOT mutate the caller's DataFrame (copies at the top).

    main_usage = total_kw_main_eng * load_factor(speed_km/h) * time_diff_hours
                 * SFOC(total_kw_main_eng) * 1e-6
    Zeroed when ``speed_kn <= 0.3`` OR ``time_diff_hours >= 1`` (spec section 3.6).

    Internal helper; not part of the public API.
    """
    df = df.copy()
    df["main_usage"] = np.where(
        (df["speed_kn"] <= STATIONARY_SPEED_KN) | (df["time_diff_hours"] >= LARGE_GAP_HOURS),
        0,
        ship.total_kw_main_eng
        * get_load_factor(df["speed_km/h"], ship.service_speed)
        * df["time_diff_hours"]
        * get_sfoc(ship.total_kw_main_eng)
        * SFOC_MULTIPLIER,
    )
    return df


def get_aux_usage(ship: ShipParams, df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with an ``aux_usage`` (tonnes) column added.

    Does NOT mutate the caller's DataFrame (copies at the top).

    aux_usage = aux_engine_total_kw * aux_load_factor(speed_kn, ship_type)
                * time_diff_hours * 185 * 1e-6
    Zeroed when ``sog > 0.3`` AND ``time_diff_hours >= 1`` (spec section 3.7).

    Faithful to ``ais_module.py``: the load factor uses the position-derived
    ``speed_kn`` (``ais_module.py:113``); ``sog`` is used ONLY for the zeroing
    gate (``ais_module.py:111``).

    Internal helper; not part of the public API.
    """
    df = df.copy()
    df["aux_usage"] = np.where(
        (df["sog"] > STATIONARY_SOG_KN) & (df["time_diff_hours"] >= LARGE_GAP_HOURS),
        0,
        ship.aux_engine_total_kw
        * get_aux_load_factor(df["speed_kn"], ship.ship_type)
        * df["time_diff_hours"]
        * AUX_USAGE_FACTOR,
    )
    return df


def calculate_distance(lat1, lon1, lat2, lon2) -> float:
    """Geodesic distance in km between two points; 0 if any coord is None."""
    if None in (lat1, lon1, lat2, lon2):
        return 0.0
    return geodesic((lat1, lon1), (lat2, lon2)).kilometers


def _distance_for_row(row: pd.Series, df: pd.DataFrame) -> float:
    """Distance (km) from the previous row; 0 for the first row.

    Faithful to ``distance_wrapper``: uses positional index so consecutive
    points are measured even after a reset_index.
    """
    index = df.index.get_loc(row.name)
    if index == 0:
        return 0.0
    prev_row = df.iloc[index - 1]
    return calculate_distance(
        prev_row["latitude"], prev_row["longitude"], row["latitude"], row["longitude"]
    )


def get_pollution_data(df: pd.DataFrame, ship: ShipParams) -> pd.DataFrame:
    """Point-by-point pipeline (faithful to ``getPollutionData``).

    Expects a track DataFrame with columns ``latitude``, ``longitude``, ``sog``
    and ``time_diff_second`` (seconds since the previous point). Returns a new
    DataFrame with ``time_diff_hours``, ``distance_km``, ``speed_km/h``,
    ``speed_kn``, ``main_usage`` and ``aux_usage`` columns.

    Steps (spec section 3):
      2. time_diff_hours = time_diff_second / 3600
      3. distance_km = point-to-point geodesic (first = 0)
      4. speed_km/h = distance_km / time_diff_hours ; speed_kn = * KM_TO_KN
      4b. robustness guard: replace non-finite speeds with 0 (see below)
      5. remove speed_kn > 30 outliers, then drop the first remaining row
      6-7. main_usage + aux_usage

    Robustness guard (review HIGH, 2026-05-27): a duplicate / same-timestamp
    point yields ``distance_km == 0`` and ``time_diff_hours == 0``, so
    ``0 / 0 == NaN`` (and a zero-distance/zero-time edge can produce ``inf``).
    Because ``NaN > 30`` is ``False`` such a row would bypass the outlier filter
    and NaN-poison the entire grid. We replace non-finite (NaN/inf) speeds with 0
    BEFORE the outlier mask. The rest of the algorithm is unchanged: a 0-speed
    row is treated as stationary (main usage zeroed via the ``speed_kn <= 0.3``
    gate) and never marked an outlier.
    """
    df = df.copy()
    if df.empty:
        # Empty in -> empty out (the empty-result contract). Guard the row-wise
        # ``apply`` below, which on a zero-row frame returns an empty *DataFrame*
        # (not a Series) and cannot be assigned to a single column.
        for col in ("time_diff_hours", "distance_km", "speed_km/h", "speed_kn",
                    "main_usage", "aux_usage"):
            df[col] = pd.Series(dtype=float)
        return df
    df["time_diff_hours"] = df["time_diff_second"] / 3600
    df["distance_km"] = df.apply(lambda row: _distance_for_row(row, df), axis=1).round(10)
    df["speed_km/h"] = df["distance_km"] / df["time_diff_hours"]
    df["speed_kn"] = df["speed_km/h"] * KM_TO_KN

    # Robustness guard: 0/0 -> NaN (and 0-time edges -> inf) must not bypass the
    # outlier filter and poison the grid. Replace non-finite speeds with 0.
    df["speed_km/h"] = df["speed_km/h"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["speed_kn"] = df["speed_kn"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # Noise removal & first-row drop (spec section 3.5).
    df["is_outlier"] = df["speed_kn"] > MAX_SPEED_LIMIT_KN
    filtered = df[~df["is_outlier"]].reset_index(drop=True)
    filtered = filtered.iloc[1:].reset_index(drop=True)

    filtered = get_main_usage(ship, filtered)
    filtered = get_aux_usage(ship, filtered)
    filtered.drop(columns=["is_outlier"], inplace=True)
    return filtered


@dataclass(frozen=True)
class SegmentUsage:
    """One segment's per-point usage (the building block for streaming).

    The fields mirror the per-row columns :func:`get_pollution_data` produces
    for the *current* point of a consecutive pair (the value is attributed to
    the second/arrival point, exactly as in the track pipeline).
    """

    distance_km: float
    speed_kmh: float
    speed_kn: float
    time_diff_hours: float
    main_usage: float
    aux_usage: float
    total_usage: float


def compute_segment(prev_point: dict, curr_point: dict, ship: ShipParams) -> SegmentUsage:
    """Compute ONE segment's main/aux fuel from two consecutive points.

    This is the stateless, pure building block for phase-2 stateful streaming
    (ADR-0002): given the previous and current AIS points plus the ship
    particulars, it reproduces the EXACT per-segment math used by the whole-track
    pipeline (:func:`get_pollution_data`):

      1. ``distance_km`` = geodesic(prev, curr), rounded to 10 dp (faithful)
      2. ``time_diff_hours`` = ``curr.time_diff_second`` / 3600 — i.e. the time
         from the previous point to the current one
      3. ``speed_km/h`` = distance_km / time_diff_hours ; ``speed_kn`` = * KM_TO_KN
         (non-finite results from a 0s / 0-distance gap are replaced with 0, same
         robustness guard as the track pipeline)
      4. ``main_usage`` (cubic load factor; zeroed when ``speed_kn <= 0.3`` OR
         ``time_diff_hours >= 1``)
      5. ``aux_usage`` (aux load factor keyed on ``speed_kn``; zeroed when
         ``curr.sog > 0.3`` AND ``time_diff_hours >= 1``)

    Each point is a mapping with ``latitude``, ``longitude`` and ``sog``. The
    current point must also provide ``time_diff_second`` (seconds since the
    previous point); if omitted it is derived from ``reg_date`` deltas when both
    points carry a ``reg_date``.

    Scope (caller's responsibility, NOT done here): whole-track concerns —
    ``speed_kn > 30`` outlier removal, the mandatory first-row drop, and linear
    interpolation — belong to the track/stream pipeline, not to this per-segment
    primitive. ``compute_segment`` computes a segment exactly as the pipeline
    would for that same consecutive pair on a clean track.
    """
    time_diff_second = curr_point.get("time_diff_second")
    if time_diff_second is None:
        prev_t = prev_point.get("reg_date")
        curr_t = curr_point.get("reg_date")
        if prev_t is None or curr_t is None:
            raise ValueError(
                "compute_segment needs curr_point['time_diff_second'] or a "
                "'reg_date' on both points to derive it."
            )
        time_diff_second = (pd.Timestamp(curr_t) - pd.Timestamp(prev_t)).total_seconds()

    time_diff_hours = float(time_diff_second) / 3600

    distance_km = round(
        calculate_distance(
            prev_point["latitude"],
            prev_point["longitude"],
            curr_point["latitude"],
            curr_point["longitude"],
        ),
        10,
    )

    # speed_km/h = distance / time; guard the 0/0 (and 0-time) edge exactly like
    # get_pollution_data (non-finite -> 0).
    if time_diff_hours == 0 or not np.isfinite(time_diff_hours):
        speed_kmh = 0.0
    else:
        speed_kmh = distance_km / time_diff_hours
    if not np.isfinite(speed_kmh):
        speed_kmh = 0.0
    speed_kn = speed_kmh * KM_TO_KN
    if not np.isfinite(speed_kn):
        speed_kn = 0.0

    # Main usage (spec 3.6): cubic load factor, zeroed when stationary or large gap.
    if speed_kn <= STATIONARY_SPEED_KN or time_diff_hours >= LARGE_GAP_HOURS:
        main_usage = 0.0
    else:
        load_factor = (speed_kmh / (ship.service_speed * KN_TO_KM)) ** 3
        main_usage = (
            ship.total_kw_main_eng
            * load_factor
            * time_diff_hours
            * get_sfoc(ship.total_kw_main_eng)
            * SFOC_MULTIPLIER
        )

    # Aux usage (spec 3.7): load factor keyed on speed_kn; zeroed only when
    # moving (sog>0.3) AND large gap. sog is used ONLY for the zeroing gate.
    sog = curr_point["sog"]
    if sog > STATIONARY_SOG_KN and time_diff_hours >= LARGE_GAP_HOURS:
        aux_usage = 0.0
    else:
        aux_usage = (
            ship.aux_engine_total_kw
            * _aux_factor_scalar(speed_kn, ship.ship_type)
            * time_diff_hours
            * AUX_USAGE_FACTOR
        )

    return SegmentUsage(
        distance_km=distance_km,
        speed_kmh=speed_kmh,
        speed_kn=speed_kn,
        time_diff_hours=time_diff_hours,
        main_usage=main_usage,
        aux_usage=aux_usage,
        total_usage=main_usage + aux_usage,
    )
