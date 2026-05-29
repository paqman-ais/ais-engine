"""Pollutant emissions from fuel consumption.

Multiplies fuel mass (tonnes) by per-pollutant kg/ton factors (IMO defaults,
1% sulfur fuel). All outputs are in kilograms. Reference: legacy
``pipeline/pollution_engine/ALGORITHM.md`` section 3.

Two entry points:

  - :func:`compute_emissions_kg` for a scalar fuel mass — returns an
    :class:`EmissionKg` namedtuple. Use in tight loops or one-shot reports.
  - :func:`add_emission_columns` for a pandas frame already carrying a fuel
    column — returns a copy with ``nox_kg``/``sox_kg``/``pm_kg``/``co2_kg``
    appended. Use in the silver job to extend ``fuel_points`` rows.

Both functions are pure: NaN/None fuel propagates as NaN emissions; the
caller decides what to write (NULL in SQL, skip in reports, etc.).
"""

from __future__ import annotations

from typing import NamedTuple

import pandas as pd

from .constants import (
    EMISSION_FACTOR_CO2_KG_PER_TON,
    EMISSION_FACTOR_NOX_KG_PER_TON,
    EMISSION_FACTOR_PM_KG_PER_TON,
    EMISSION_FACTOR_SOX_KG_PER_TON,
)

POLLUTANTS: tuple[str, ...] = ("nox", "sox", "pm", "co2")


class EmissionKg(NamedTuple):
    """Per-pollutant emissions in kilograms for one fuel mass."""

    nox: float
    sox: float
    pm: float
    co2: float


def compute_emissions_kg(fuel_tonnes: float) -> EmissionKg:
    """Scalar fuel (tonnes) → per-pollutant emissions (kg)."""
    return EmissionKg(
        nox=fuel_tonnes * EMISSION_FACTOR_NOX_KG_PER_TON,
        sox=fuel_tonnes * EMISSION_FACTOR_SOX_KG_PER_TON,
        pm=fuel_tonnes * EMISSION_FACTOR_PM_KG_PER_TON,
        co2=fuel_tonnes * EMISSION_FACTOR_CO2_KG_PER_TON,
    )


def add_emission_columns(
    df: pd.DataFrame,
    *,
    fuel_col: str = "total_usage",
) -> pd.DataFrame:
    """Return a copy of ``df`` with ``nox_kg``/``sox_kg``/``pm_kg``/``co2_kg`` added.

    The fuel column is expected in tonnes (matching ``fuel_points.total_usage``
    written by the silver job, which uses :data:`SFOC_MULTIPLIER = 1e-6` to
    convert g → tonnes). NaN fuel produces NaN emissions; the caller chooses
    how to persist (NULL, drop, etc.).

    Does NOT mutate the input (copies at the top).
    """
    out = df.copy()
    fuel = out[fuel_col]
    out["nox_kg"] = fuel * EMISSION_FACTOR_NOX_KG_PER_TON
    out["sox_kg"] = fuel * EMISSION_FACTOR_SOX_KG_PER_TON
    out["pm_kg"] = fuel * EMISSION_FACTOR_PM_KG_PER_TON
    out["co2_kg"] = fuel * EMISSION_FACTOR_CO2_KG_PER_TON
    return out
