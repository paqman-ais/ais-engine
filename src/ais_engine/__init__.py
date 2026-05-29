"""ais_engine — faithful, DB-free port of the verified AIS fuel-usage grid.

See ``README.md`` for the mapping to ``logic-spec/01-core-emission-grid-logic.md``,
the SFOC-threshold fix (spec section 6), and the aux load-factor = ``speed_kn``
clarification (spec section 2, review 2026-05-27).

Public API
----------
The supported, stable surface is exactly the names in :data:`__all__`. The
v0.3.0 additions map onto the ADR-0002 layered data architecture:

- :func:`compute_pollution` — Bronze track -> per-point fuel/emission rows
  (the **Silver** layer the platform stores once per point).
- :func:`rebin_cells_to_grid` — already-summed cells -> a target grid (the
  **Gold** re-bin; generalizes the per-point grid aggregation).
- :func:`compute_segment` (+ :class:`SegmentUsage`) — one consecutive-pair
  segment's main/aux fuel; the pure building block for phase-2 streaming.

``run_grid`` (whole track -> grid) is unchanged in signature and is now a thin
composition of ``compute_pollution`` + grid aggregation, so all paths share one
set of frozen formulas.

Internal helpers (``get_main_usage``, ``get_aux_usage``, ``get_pollution_data``,
``get_sfoc``, ``get_load_factor``, ``get_aux_load_factor``, ``calculate_distance``,
``GridAggregator``, ``aggregate_to_grid``, ``aggregate_value_to_grid``,
``build_interpolated_track``, ``resample_and_interpolate_fast_sog``) remain
importable from their submodules but are NOT part of the locked public API and
may change without notice. Output adapters live in the separate
:mod:`ais_engine.export` module (also outside the core public API).
"""

from __future__ import annotations

from .constants import (
    AUX_USAGE_FACTOR,
    EMISSION_FACTOR_CO2_KG_PER_TON,
    EMISSION_FACTOR_NOX_KG_PER_TON,
    EMISSION_FACTOR_PM_KG_PER_TON,
    EMISSION_FACTOR_SOX_KG_PER_TON,
    KM_TO_KN,
    KN_TO_KM,
    SFOC_MULTIPLIER,
)
from .emission import POLLUTANTS, EmissionKg, add_emission_columns, compute_emissions_kg
from .fuel import SegmentUsage, compute_segment
from .mode import (
    MODE_CRUISING,
    MODE_HOTELING,
    MODE_SLOW_STEAMING,
    MODES,
    add_mode_column,
    classify_mode,
)
from .grid import GridRange, rebin_cells_to_grid
from .models import ShipParams
from .pipeline import GridInfo, QueryParams, compute_pollution, run_grid
from .repository import AISRepository, CSVRepository, InMemoryRepository

__all__ = [
    # v0.2 surface (unchanged)
    "run_grid",
    "GridInfo",
    "QueryParams",
    "AISRepository",
    "InMemoryRepository",
    "CSVRepository",
    "ShipParams",
    "GridRange",
    "KN_TO_KM",
    "KM_TO_KN",
    "SFOC_MULTIPLIER",
    "AUX_USAGE_FACTOR",
    # v0.3 additions (ADR-0002 layered data architecture)
    "compute_pollution",   # Silver: track -> per-point rows
    "rebin_cells_to_grid",  # Gold: pre-summed cells -> target grid
    "compute_segment",     # streaming primitive: one segment's fuel
    "SegmentUsage",
    # v0.5 additions (Phase 1.1 — fuel -> pollutant emissions in kg, IMO defaults)
    "compute_emissions_kg",
    "add_emission_columns",
    "EmissionKg",
    "POLLUTANTS",
    "EMISSION_FACTOR_NOX_KG_PER_TON",
    "EMISSION_FACTOR_SOX_KG_PER_TON",
    "EMISSION_FACTOR_PM_KG_PER_TON",
    "EMISSION_FACTOR_CO2_KG_PER_TON",
    # v0.6 additions (Phase 2 — speed → operational mode label)
    "classify_mode",
    "add_mode_column",
    "MODES",
    "MODE_CRUISING",
    "MODE_SLOW_STEAMING",
    "MODE_HOTELING",
]

__version__ = "0.6.0"
