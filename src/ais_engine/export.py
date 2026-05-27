"""Output adapters for a computed fuel-usage grid (separate from the core).

The verified reference wrote the final grid to disk inside the pipeline
(``grid.to_excel(...)`` / commented-out ``grid.to_csv(...)`` in
``ais_grid_module.create`` / ``create_linear``). In this port the core
:func:`ais_engine.pipeline.run_grid` is deliberately **format-agnostic** — it
returns the grid DataFrame and never touches the filesystem.

This module is the *export adapter*: a small, separately documented surface that
serializes a grid DataFrame to the legacy on-disk shapes. It is intentionally
NOT part of the core public ``__all__`` (importers must reach for it explicitly,
e.g. ``from ais_engine.export import grid_to_excel``).

``openpyxl`` is an OPTIONAL dependency (the ``[excel]`` extra) and is imported
lazily so the core engine has no hard dependency on it.

Spec reference: ``logic-spec/01-core-emission-grid-logic.md`` section 4
("격자형 엑셀" output, row=lat, col=lon, value=총 연료사용량).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def grid_to_excel(grid: pd.DataFrame, path: str | Path) -> None:
    """Write a grid DataFrame to the legacy grid ``.xlsx`` shape.

    Row index = latitude band, columns = longitude band, values = total fuel
    usage (tonnes) — i.e. exactly what the reference ``grid.to_excel(...)``
    produced (``ais_grid_module.create`` / ``create_linear``).

    Requires the optional ``openpyxl`` dependency (install the ``[excel]``
    extra: ``pip install ais-engine[excel]``). ``openpyxl`` is imported lazily
    so the core engine does not depend on it.
    """
    try:
        import openpyxl  # noqa: F401  (presence check; pandas uses it as the engine)
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "grid_to_excel requires openpyxl. Install the optional extra: "
            "pip install ais-engine[excel]"
        ) from exc

    grid.to_excel(path, engine="openpyxl")


def grid_to_csv(grid: pd.DataFrame, path: str | Path) -> None:
    """Write a grid DataFrame to CSV (legacy backward-compat).

    .. deprecated::
        The reference kept ``grid.to_csv(...)`` only as a commented-out legacy
        fallback; the ``.xlsx`` grid is the canonical output. This helper exists
        for backward compatibility and is a candidate for removal — prefer
        :func:`grid_to_excel`.
    """
    grid.to_csv(path)
