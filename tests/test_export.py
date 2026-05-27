"""Unit tests for the grid export adapter (ais_engine.export).

These cover the SEPARATE output surface (NOT part of core ``__all__``):
``grid_to_excel`` (legacy grid .xlsx) and ``grid_to_csv`` (legacy backward
compat). ``openpyxl`` is imported lazily by the excel writer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ais_engine.export import grid_to_csv, grid_to_excel


def _sample_grid() -> pd.DataFrame:
    lats = [35.0, 35.005, 35.010]
    lons = [129.0, 129.005]
    return pd.DataFrame(
        np.array([[1.0, 2.0], [0.0, 0.5], [3.0, 0.0]]), index=lats, columns=lons
    )


def test_grid_to_csv_roundtrip(tmp_path):
    grid = _sample_grid()
    out = tmp_path / "grid.csv"
    grid_to_csv(grid, out)
    assert out.exists()
    back = pd.read_csv(out, index_col=0)
    assert back.values.sum() == pytest.approx(grid.values.sum())


def test_grid_to_excel_roundtrip(tmp_path):
    pytest.importorskip("openpyxl")
    grid = _sample_grid()
    out = tmp_path / "grid.xlsx"
    grid_to_excel(grid, out)
    assert out.exists()
    back = pd.read_excel(out, index_col=0)
    assert back.values.sum() == pytest.approx(grid.values.sum())


def test_export_not_in_core_public_api():
    """Export helpers are a separate surface, NOT in core ``__all__``."""
    import ais_engine

    assert "grid_to_excel" not in ais_engine.__all__
    assert "grid_to_csv" not in ais_engine.__all__
