"""Unit tests for grid construction and aggregation (spec section 4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ais_engine.grid import GridAggregator, aggregate_to_grid


def test_grid_range_includes_center_and_is_sorted():
    gr = GridAggregator(center_lat=35.0, center_lon=129.0, radius=2000, grid_size=500).calculate_grid_range()
    # center is always present in both axes.
    assert any(abs(lat - 35.0) < 1e-9 for lat in gr.lats)
    assert any(abs(lon - 129.0) < 1e-9 for lon in gr.lons)
    # axes sorted ascending.
    assert gr.lats == sorted(gr.lats)
    assert gr.lons == sorted(gr.lons)
    # bins have one more edge than labels (faithful linspace construction).
    assert len(gr.lats_bins) == len(gr.lats) + 1
    assert len(gr.lons_bins) == len(gr.lons) + 1
    # grid starts all-zero.
    assert (gr.grid.values == 0).all()


def test_radius_controls_grid_extent():
    small = GridAggregator(35.0, 129.0, 1000, 500).calculate_grid_range()
    large = GridAggregator(35.0, 129.0, 5000, 500).calculate_grid_range()
    assert len(large.lats) > len(small.lats)
    assert len(large.lons) > len(small.lons)


def test_aggregate_sums_usage_into_cells():
    gr = GridAggregator(35.0, 129.0, 2000, 500).calculate_grid_range()
    # Two points near the center; total usage should land in the grid.
    pollution = pd.DataFrame(
        {
            "latitude": [35.0, 35.0],
            "longitude": [129.0, 129.0],
            "main_usage": [1.0, 2.0],
            "aux_usage": [0.5, 0.5],
        }
    )
    out = aggregate_to_grid(pollution, gr)
    assert out.values.sum() == pytest.approx(4.0)  # (1+0.5)+(2+0.5)


def test_aggregate_does_not_mutate_source_grid():
    gr = GridAggregator(35.0, 129.0, 1500, 500).calculate_grid_range()
    pollution = pd.DataFrame(
        {"latitude": [35.0], "longitude": [129.0], "main_usage": [3.0], "aux_usage": [1.0]}
    )
    _ = aggregate_to_grid(pollution, gr)
    assert (gr.grid.values == 0).all()  # original grid untouched


def test_bins_are_even_linspace_not_geodesic_stepped():
    """PIN the known reference quirk (spec/README): the pd.cut bin EDGES are an
    even ``np.linspace`` over [min, max] with ``len(labels)+1`` points, NOT the
    geodesic-stepped lat/lon values used as the cell-center labels.

    This is faithful to the reference (``grid.py``) even though it means the bin
    boundaries do not coincide with the stepped centers. The test guards against
    "fixing" it to stepped edges, which would silently change aggregation.
    """
    gr = GridAggregator(35.0, 129.0, 3000, 500).calculate_grid_range()
    expected_lat_bins = np.linspace(min(gr.lats), max(gr.lats), len(gr.lats) + 1)
    expected_lon_bins = np.linspace(min(gr.lons), max(gr.lons), len(gr.lons) + 1)
    assert np.allclose(gr.lats_bins, expected_lat_bins)
    assert np.allclose(gr.lons_bins, expected_lon_bins)
    # Even spacing: every adjacent edge gap is identical (linspace property).
    lat_gaps = np.diff(gr.lats_bins)
    assert np.allclose(lat_gaps, lat_gaps[0])
    # The stepped centers are NOT evenly spaced like the linspace edges would be
    # at the same count, so edges != centers (this is the quirk being pinned).
    assert not np.allclose(gr.lats_bins[:-1], gr.lats)


def test_points_outside_grid_are_ignored():
    gr = GridAggregator(35.0, 129.0, 1000, 500).calculate_grid_range()
    pollution = pd.DataFrame(
        {"latitude": [10.0], "longitude": [10.0], "main_usage": [5.0], "aux_usage": [5.0]}
    )
    out = aggregate_to_grid(pollution, gr)
    assert out.values.sum() == pytest.approx(0.0)
