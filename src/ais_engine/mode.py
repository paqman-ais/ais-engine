"""Operational mode classification from instantaneous speed.

Spec: legacy ``pipeline/pollution_engine/ALGORITHM.md`` section 2.3. Same
speed thresholds that drive the auxiliary load-factor branch in
:func:`ais_engine.fuel._aux_factor_scalar`, exported as a separate string
label so silver / reports / scenario adapters can group on activity mode
without re-deriving the branch:

  - cruising      — speed_kn >= 10
  - slow_steaming — 0.3 <= speed_kn < 10
  - hoteling      — speed_kn < 0.3   (covers NaN/None too)

Two entry points, mirroring the emission module:

  - :func:`classify_mode` for a scalar speed.
  - :func:`add_mode_column` for a pandas frame, vectorized via np.select
    so a multi-thousand-row silver batch stays cheap.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .constants import AUX_SPEED_HIGH_KN, STATIONARY_SOG_KN

# Keep the legacy ALGORITHM.md spelling ("Hoteling" with one l) so any
# downstream consumer that already groups on these strings doesn't break.
MODE_CRUISING: str = "cruising"
MODE_SLOW_STEAMING: str = "slow_steaming"
MODE_HOTELING: str = "hoteling"

MODES: tuple[str, ...] = (MODE_CRUISING, MODE_SLOW_STEAMING, MODE_HOTELING)


def classify_mode(speed_kn: float | None) -> str:
    """Scalar speed (kn) → operational mode label.

    None/NaN maps to ``hoteling`` — the conservative default for a missing
    speed reading is "not under way".
    """
    if speed_kn is None or (isinstance(speed_kn, float) and math.isnan(speed_kn)):
        return MODE_HOTELING
    if speed_kn >= AUX_SPEED_HIGH_KN:
        return MODE_CRUISING
    if speed_kn >= STATIONARY_SOG_KN:
        return MODE_SLOW_STEAMING
    return MODE_HOTELING


def add_mode_column(
    df: pd.DataFrame,
    *,
    speed_col: str = "speed_kn",
    mode_col: str = "mode",
) -> pd.DataFrame:
    """Return a copy of ``df`` with a string ``mode_col`` column appended.

    NaN speeds fall through to the default branch (``hoteling``) because
    ``NaN >= x`` is False in numpy — consistent with :func:`classify_mode`.
    Does NOT mutate the input (copies at the top).
    """
    out = df.copy()
    spd = out[speed_col]
    conditions = [
        spd >= AUX_SPEED_HIGH_KN,
        spd >= STATIONARY_SOG_KN,
    ]
    choices = [MODE_CRUISING, MODE_SLOW_STEAMING]
    out[mode_col] = np.select(conditions, choices, default=MODE_HOTELING)
    return out
