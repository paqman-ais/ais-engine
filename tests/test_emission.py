"""Unit tests for the emission-factor conversion module.

Pins the IMO default factors (NOx 57, SOx 20, PM 1.5, CO₂ 3114 kg/ton fuel)
from legacy ``pipeline/pollution_engine/ALGORITHM.md`` section 3.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ais_engine import constants as C
from ais_engine.emission import (
    POLLUTANTS,
    EmissionKg,
    add_emission_columns,
    compute_emissions_kg,
)


# --- Scalar API ---


def test_compute_emissions_kg_two_tons():
    e = compute_emissions_kg(2.0)
    assert isinstance(e, EmissionKg)
    assert e.nox == pytest.approx(2.0 * C.EMISSION_FACTOR_NOX_KG_PER_TON)
    assert e.sox == pytest.approx(2.0 * C.EMISSION_FACTOR_SOX_KG_PER_TON)
    assert e.pm == pytest.approx(2.0 * C.EMISSION_FACTOR_PM_KG_PER_TON)
    assert e.co2 == pytest.approx(2.0 * C.EMISSION_FACTOR_CO2_KG_PER_TON)


@pytest.mark.parametrize(
    "fuel,expected",
    [
        (0.0, EmissionKg(0.0, 0.0, 0.0, 0.0)),
        (1.0, EmissionKg(57.0, 20.0, 1.5, 3114.0)),
        (0.5, EmissionKg(28.5, 10.0, 0.75, 1557.0)),
    ],
)
def test_compute_emissions_kg_known_vectors(fuel, expected):
    assert compute_emissions_kg(fuel) == pytest.approx(expected)


def test_pollutants_constant_matches_namedtuple_fields():
    # Catch drift between POLLUTANTS list and EmissionKg fields.
    assert POLLUTANTS == EmissionKg._fields


# --- DataFrame API ---


def test_add_emission_columns_appends_four_kg_columns():
    df = pd.DataFrame({"total_usage": [1.0, 2.0]})
    out = add_emission_columns(df)
    assert list(out.columns) == [
        "total_usage", "nox_kg", "sox_kg", "pm_kg", "co2_kg",
    ]
    assert out["nox_kg"].iloc[0] == pytest.approx(57.0)
    assert out["co2_kg"].iloc[1] == pytest.approx(6228.0)


def test_add_emission_columns_propagates_nan():
    # NaN fuel must NOT become 0 — silver layer needs to distinguish "no
    # computation yet" from "computed and is exactly 0".
    df = pd.DataFrame({"total_usage": [np.nan, 1.0]})
    out = add_emission_columns(df)
    assert pd.isna(out["nox_kg"].iloc[0])
    assert out["nox_kg"].iloc[1] == pytest.approx(57.0)


def test_add_emission_columns_does_not_mutate_input():
    df = pd.DataFrame({"total_usage": [1.0]})
    cols_before = list(df.columns)
    _ = add_emission_columns(df)
    assert list(df.columns) == cols_before


def test_add_emission_columns_custom_fuel_col():
    df = pd.DataFrame({"my_fuel_t": [1.0]})
    out = add_emission_columns(df, fuel_col="my_fuel_t")
    assert out["nox_kg"].iloc[0] == pytest.approx(57.0)


def test_add_emission_columns_empty_frame():
    df = pd.DataFrame({"total_usage": pd.Series([], dtype="float64")})
    out = add_emission_columns(df)
    assert len(out) == 0
    assert {"nox_kg", "sox_kg", "pm_kg", "co2_kg"}.issubset(out.columns)
