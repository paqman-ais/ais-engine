# ais-engine

A clean, tested, **DB-free** Python port of the verified AIS **fuel-usage emission grid** logic.

This is **P0** of a fresh rebuild. Faithfulness to the verified Jupyter logic is the #1 priority.

> **v0.3.0** evolves the public API surface to serve the ADR-0002 layered data
> architecture (Bronze/Silver/Gold). The calculation **formulas are unchanged**
> — this release exposes the intermediate stages as stable public APIs
> (`compute_pollution`, `rebin_cells_to_grid`, `compute_segment`); `run_grid` is
> unchanged in signature. See "ADR-0002 layered APIs" below.

- **Spec (authoritative):** `ais-docs/logic-spec/01-core-emission-grid-logic.md`
- **Reference code (faithful source):** `ais-docs/reference/legacy-jupyter/ais_modules/`

## What it does

Given a sea area (center + radius) and a time window, it walks each ship's AIS
track, computes **main + auxiliary engine fuel usage (tonnes)** at each point,
and **sums it per grid cell** to produce a lat/lon grid of total fuel usage.

```
AIS track + ship params -> per-point speed/distance -> fuel usage (main + aux) -> grid-cell sum
```

## Structure

```
engine/
├── pyproject.toml                  core deps: pandas, numpy, geopy; extras: [excel]=openpyxl, [dev]=pytest
├── LICENSE                         proprietary placeholder (replace before distribution)
├── README.md
├── src/ais_engine/
│   ├── __init__.py                 LOCKED public API (see __all__)
│   ├── py.typed                    PEP 561 typing marker (fully typed)
│   ├── constants.py                spec §2 constants (KN_TO_KM, SFOC factors, thresholds)
│   ├── models.py                   ShipParams dataclass (replaces SQLAlchemy ShipInfo)
│   ├── fuel.py                     PURE calc: SFOC, load factors, distance/speed, main/aux usage, point pipeline, compute_segment
│   ├── grid.py                     PURE: GridAggregator + aggregate_value_to_grid / rebin_cells_to_grid / aggregate_to_grid
│   ├── interpolation.py            PURE: moving/stationary split + 1s resample + linear interpolate
│   ├── repository.py               data access: AISRepository ABC + InMemory/CSV impls (NO real DB)
│   ├── pipeline.py                 orchestration: compute_pollution (Silver) + run_grid(repo, params, grid_info, interpolate=)
│   └── export.py                   OUTPUT ADAPTER (separate surface): grid_to_excel / grid_to_csv
└── tests/
    ├── test_fuel.py                SFOC, aux LF=speed_kn pin, cubic LF, zeroing, dt=0 guard, degenerate tracks
    ├── test_grid.py                grid build + aggregation + linspace-bin quirk pin
    ├── test_interpolation.py       1s resample + gap-break (no bridging) + value-pinned interpolation
    ├── test_export.py              grid_to_excel / grid_to_csv adapters + not-in-core-__all__
    ├── test_regression.py          SELF-CONSISTENCY (not a verified golden) + real-golden harness/TODO
    ├── test_v3_consistency.py      v0.3 APIs numerically consistent with run_grid (Silver/Gold/segment)
    └── fixtures/
        ├── synthetic_track.csv     6-point deterministic track (ais_new2 schema)
        └── synthetic_ships.csv     one ship (ship_info schema)
```

### Pure vs. data-access separation (anti-pattern fix)

The original `ais_module.py` opened a live SQLAlchemy engine/session **at module
import time** and the fuel formulas read straight from the DB-bound ORM object.
Here:

- **Pure layer** (`fuel.py`, `grid.py`, `interpolation.py`) takes only pandas
  DataFrames + a `ShipParams` dataclass. No DB, no I/O, no globals — fully
  unit-testable offline.
- **Data access** (`repository.py`) is an abstract `AISRepository`. The provided
  `InMemoryRepository` / `CSVRepository` implementations **never open a real
  database connection**. A real MySQL/TimescaleDB repo can be added later
  without touching the pure layer.
- **No module-import-time engine/session.**

## How it maps to the spec

| Spec | Implementation |
|---|---|
| §2 constants (`KN_TO_KM=1.852`, `KM_TO_KN=0.539957`, `SFOC_MULTIPLIER=1e-6`, `AUX_USAGE_FACTOR=185×1e-6`) | `constants.py` |
| §3.3–3.4 geodesic distance → speed_km/h → speed_kn | `fuel.calculate_distance`, `fuel.get_pollution_data` |
| §3.5 outlier removal (`speed_kn>30`) + drop first row | `fuel.get_pollution_data` |
| §3.6 main engine fuel + cubic load factor + zeroing (`speed_kn≤0.3` OR `time_diff_hours≥1`) | `fuel.get_main_usage`, `fuel.get_load_factor` |
| §3.7 aux engine fuel + zeroing (`sog>0.3` AND `time_diff_hours≥1`) | `fuel.get_aux_usage` |
| §2 aux load factor keyed on **`speed_kn`** (≥10→0.3; 0.3–10→0.5; <0.3→0.6 Tanker/Passenger else 0.4) | `fuel.get_aux_load_factor` |
| §4 grid build (center+radius+grid_size geodesic stepping) + `pd.cut` binning + per-cell sum | `grid.GridAggregator`, `grid.aggregate_to_grid` |
| §5 no-interp `create()` vs linear-interp `create_linear()` | `pipeline.run_grid(..., interpolate=False/True)`, `interpolation.build_interpolated_track` |

## ADR-0002 layered APIs (v0.3.0 — formulas unchanged)

ADR-0002 splits the platform into layers so the heavy, sequential per-point
calculation runs **once** (not on every analysis): compute per-point fuel once
(Silver, stored), pre-aggregate to a fine grid (Gold), and re-bin to the user's
grid on demand. v0.3.0 exposes those intermediate stages as stable public APIs.
**No math changed** — these are restructurings/exposures of existing logic, and
the consistency tests prove they produce the same numbers as `run_grid`.

| ADR-0002 layer | Public API (v0.3) | What it does |
|---|---|---|
| **Bronze** (raw points) | — (your repository) | append-only AIS position points; `AISRepository.get_ais_track` returns them ordered + de-duped with `time_diff_second` |
| **Silver** (per-point fuel) | **`compute_pollution(track, ship, *, interpolate=False)`** | track → per-point fuel/emission **rows** (NOT a grid). Columns include `reg_date`, `mmsi`/`user_id` (if present), `latitude`, `longitude`, `speed_kn`, `main_usage`, `aux_usage`, `total_usage` (= main+aux). This is what you store as Silver. |
| **Gold** (pre-summed roll-up) | **`rebin_cells_to_grid(cells_df, grid_range, value_col="total_usage")`** | already-summed cells (each row = lat, lon, pre-computed value) → a target `GridRange`. Re-binning pre-summed fine cells, NOT raw points. Works with any lat/lon cell representation. |
| streaming primitive (phase-2) | **`compute_segment(prev_point, curr_point, ship) -> SegmentUsage`** | ONE segment's main/aux fuel from two consecutive points + ship params; the pure building block for stateful streaming. Same per-segment math as the track pipeline. |
| whole track → grid (v0.2) | `run_grid(repo, params, grid_info, interpolate=)` | unchanged signature; now a thin composition of `compute_pollution` + grid aggregation, so all paths share one set of frozen formulas. |

`aggregate_to_grid` (per-point `main_usage + aux_usage` → grid) and
`rebin_cells_to_grid` (pre-summed cells → grid) are both thin wrappers over a
single shared internal primitive, `grid.aggregate_value_to_grid(cells_df,
grid_range, value_col)`, which sums an arbitrary `value_col` over `(latitude,
longitude)` into the target grid. One code path handles both per-point usage
aggregation and Gold re-binning, so behavior for existing `aggregate_to_grid`
callers is unchanged.

```python
from ais_engine import compute_pollution, rebin_cells_to_grid, compute_segment

# Silver: compute per-point rows ONCE, store them.
silver = compute_pollution(track, ship)            # track -> per-point rows
silver_linear = compute_pollution(track, ship, interpolate=True)

# Gold re-bin: already-summed fine cells -> a user's target grid on demand.
target_grid = rebin_cells_to_grid(fine_cells, target_grid_range)  # value_col="total_usage"

# Streaming primitive (phase-2): one consecutive pair -> one segment's fuel.
seg = compute_segment(prev_point, curr_point, ship)  # -> SegmentUsage(main_usage, aux_usage, total_usage, ...)
```

**`compute_segment` scope (caller's responsibility):** whole-track concerns —
`speed_kn > 30` outlier removal, the mandatory first-row drop, and linear
interpolation — belong to the track/stream pipeline, NOT to this per-segment
primitive. On a clean track (no outliers) `compute_segment` over each
consecutive pair reproduces `compute_pollution`'s per-row `main_usage` /
`aux_usage` exactly (pinned by `tests/test_v3_consistency.py`).

**Deferred (out of scope now):** a geohash/H3 **base-grid helper** that
*produces* a fixed fine-cell grid is not included. `rebin_cells_to_grid` already
works with any lat/lon cell representation, so the helper can be added later
without touching the engine. **TODO:** add a geohash/H3 fine base-grid builder.

## Aux load factor uses `speed_kn` (faithful)

The reference `get_aux_load_factor`'s parameter is misleadingly named `sog`, but
the **call site passes the position-derived `speed_kn`** (`ais_module.py:113`).
This port matches that behavior: the **auxiliary load factor input is
`speed_kn`**, not the AIS-reported `sog`. `sog` is used **only** for the aux
zeroing gate (`sog > 0.3 AND time_diff_hours ≥ 1 → 0`, `ais_module.py:111`).
`tests/test_fuel.py::test_aux_usage_load_factor_uses_speed_kn_not_sog` pins this
and fails if anyone reverts the load-factor input to `sog`.

## Known reference quirk: grid bin edges are an even `linspace`, not stepped

`GridAggregator.calculate_grid_range` builds the cell-center labels by stepping
`grid_size` meters geodesically from the center, but the `pd.cut` **bin edges**
are an even `np.linspace(min, max, len(labels)+1)` — i.e. evenly spaced
boundaries that do **not** coincide with the geodesic-stepped centers. This is
faithful to the reference (`grid.py`) and is pinned by
`tests/test_grid.py::test_bins_are_even_linspace_not_geodesic_stepped` so it is
not "fixed" by accident.

## Empty-result contract

`get_pollution_data` removes `speed_kn > 30` outliers and then unconditionally
drops the first surviving row. A track with **≤ 1 surviving row** (empty,
single-point, or all-outlier tracks) therefore yields an **empty** result, and
`run_grid` simply contributes nothing for that ship (the grid stays unchanged).
Duplicate / same-timestamp points (`0/0 → NaN`) are guarded: non-finite speeds
are replaced with 0 before the outlier filter, so they can never NaN-poison the
grid.

## Timezone expectation on `reg_date`

`reg_date` is parsed with `pd.to_datetime` and treated as **timezone-naive**
(matching the verified MySQL `ais_new2` data, which is naive local time). Provide
naive timestamps; if your source is tz-aware, normalize/strip the tz before
handing tracks to the repository so diffs and resampling behave as in the
reference.

## ⚠️ The SFOC threshold fix (spec §6)

The January reimplementation **inverted** the main-engine SFOC mapping. This
port implements the **verified / correct** version (larger engines are more
efficient → lower SFOC):

| main engine kW | SFOC (g/kWh) — CORRECT |
|---|---|
| **> 15000** | **175** |
| 5000 – 15000 | 185 |
| **< 5000** | **195** |

`fuel.get_sfoc` implements exactly this, and `tests/test_fuel.py`
(`test_sfoc_corrected_mapping`, `test_sfoc_is_not_inverted`) asserts it and
guards against re-inverting it.

## Usage

```python
from datetime import datetime
from ais_engine import CSVRepository, GridInfo, QueryParams, run_grid

repo = CSVRepository("tracks.csv", "ships.csv")  # ais_new2 + ship_info schemas
params = QueryParams(region=1, start_date=datetime(2026, 1, 1),
                     end_date=datetime(2026, 1, 2), mmsi=0)  # 0 = all ships
grid_info = GridInfo(center_lat=35.0, center_lon=129.0, radius_km=5.0, grid_size_m=500.0)

grid = run_grid(repo, params, grid_info, interpolate=False)  # create()
grid_linear = run_grid(repo, params, grid_info, interpolate=True)  # create_linear()

# Core run_grid is format-agnostic (returns the grid DataFrame). Serialize via
# the separate export adapter (openpyxl is the optional [excel] extra):
from ais_engine.export import grid_to_excel  # not in core __all__ on purpose
grid_to_excel(grid, "region1_grid_선형보간x.xlsx")  # row=lat, col=lon, value=tonnes
```

### Public API (locked)

The stable, supported surface is exactly:

```python
__all__ = [
    # v0.2 surface (unchanged)
    "run_grid", "GridInfo", "QueryParams",
    "AISRepository", "InMemoryRepository", "CSVRepository",
    "ShipParams", "GridRange",
    "KN_TO_KM", "KM_TO_KN", "SFOC_MULTIPLIER", "AUX_USAGE_FACTOR",
    # v0.3 additions (ADR-0002 layered data architecture)
    "compute_pollution",    # Silver: track -> per-point rows
    "rebin_cells_to_grid",  # Gold: pre-summed cells -> target grid
    "compute_segment",      # streaming primitive: one segment's fuel
    "SegmentUsage",
]
```

Internal helpers (`get_main_usage`, `get_aux_usage`, `get_pollution_data`,
`get_sfoc`, `get_load_factor`, `get_aux_load_factor`, `calculate_distance`,
`GridAggregator`, `aggregate_to_grid`, `aggregate_value_to_grid`,
`build_interpolated_track`, `resample_and_interpolate_fast_sog`) remain
importable from their submodules but are **not** part of the locked API. Output
adapters (`grid_to_excel`, `grid_to_csv`) live in `ais_engine.export` and are
likewise outside core `__all__`.

`get_main_usage` / `get_aux_usage` copy their input and never mutate the caller's
DataFrame.

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"   # dev pulls in pytest + openpyxl (for the excel export test)
.venv/bin/pytest
```

Validated against **pandas 3.0.3 / numpy 2.4.6** on Python 3.12 (full suite
green). Dependency upper bounds (`pandas<4`, `numpy<3`, `geopy<3`) cap the next
major; re-validate before lifting them.

### Regression: self-consistency now, real golden later (honest)

`tests/test_regression.py` is a **self-consistency** test, **not** a verified
golden: it re-derives the expected total with the *same* formulas the engine
uses, so it catches algorithm drift (including an accidental revert of the aux
load factor to `sog`) but **cannot** prove faithfulness to the verified server
output. Do not read it as "verified faithful".

The verified server produces real golden outputs at `~/lab/grid_output/*.xlsx`
and `중간계산(보간x).xlsx`. `test_regression.py` carries a documented harness +
TODO (`test_real_golden_regression`, currently skipped) showing exactly where to
drop a captured grid + matching raw `ais_new2`/`ship_info` CSVs to turn it into a
true golden regression — that is the test that would justify a "verified
faithful" claim.

## Deviations from the reference (called out explicitly)

The algorithm is a faithful port of the verified Jupyter logic. The intentional
structural changes are:

1. **No DB at import time / no SQLAlchemy ORM in the calc path.** Replaced with
   `ShipParams` + the `AISRepository` abstraction (anti-pattern fix, per task).
2. **No Excel/CSV file writes inside the pipeline.** `run_grid` is
   format-agnostic and returns the grid DataFrame; serialization lives in the
   separate `ais_engine.export` adapter (`grid_to_excel` / `grid_to_csv`), with
   `openpyxl` as the optional `[excel]` extra.
3. **Per-ship grids summed via `DataFrame.add`** instead of mutating one shared
   grid in place. Mathematically identical (addition is associative) and keeps
   `aggregate_to_grid` pure.
4. **`get_sfoc` keeps the VERIFIED (non-inverted) thresholds** — this is the
   required correction, not a deviation from the source of truth.
5. **Robustness guard (added):** non-finite (`NaN`/`inf`) per-point speeds from
   `0/0` duplicate-timestamp points are replaced with 0 *before* the `>30`
   outlier filter, so a duplicate point can never NaN-poison the grid. This is
   the single explicit robustness deviation; behavior on well-formed tracks is
   unchanged.
6. **`get_main_usage` / `get_aux_usage` copy their input** (no caller-DataFrame
   mutation) and are excluded from the public `__all__`.

Everything else — the formulas, thresholds, the aux load factor keyed on
`speed_kn`, the outlier + first-row drop, the `pd.cut` binning with the even
`np.linspace` edges (see the known quirk above), and the moving/stationary
interpolation split — mirrors the reference. This is a faithful port, **not** a
line-for-line copy (the structure was reorganized for the points above); the
self-consistency tests pin the math, and a real golden regression (TODO in
`test_regression.py`) is required before any "verified faithful" claim.
