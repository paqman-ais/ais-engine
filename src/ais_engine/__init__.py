"""ais_engine — faithful, DB-free port of the verified AIS fuel-usage grid.

See ``README.md`` for the mapping to ``logic-spec/01-core-emission-grid-logic.md``,
the SFOC-threshold fix (spec section 6), and the aux load-factor = ``speed_kn``
clarification (spec section 2, review 2026-05-27).

Public API
----------
The supported, stable surface is exactly the names in :data:`__all__`. Internal
helpers (``get_main_usage``, ``get_aux_usage``, ``get_pollution_data``,
``get_sfoc``, ``get_load_factor``, ``get_aux_load_factor``, ``calculate_distance``,
``GridAggregator``, ``aggregate_to_grid``, ``build_interpolated_track``,
``resample_and_interpolate_fast_sog``) remain importable from their submodules
but are NOT part of the locked public API and may change without notice. Output
adapters live in the separate :mod:`ais_engine.export` module (also outside the
core public API).
"""

from __future__ import annotations

from .constants import (
    AUX_USAGE_FACTOR,
    KM_TO_KN,
    KN_TO_KM,
    SFOC_MULTIPLIER,
)
from .grid import GridRange
from .models import ShipParams
from .pipeline import GridInfo, QueryParams, run_grid
from .repository import AISRepository, CSVRepository, InMemoryRepository

__all__ = [
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
]

__version__ = "0.2.0"
