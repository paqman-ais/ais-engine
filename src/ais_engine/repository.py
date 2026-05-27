"""Data-access layer: abstract repository + offline implementations.

The verified reference imported a live SQLAlchemy engine/session at module load
time (``ais_module.py``: ``engine = create_engine_instance()`` at import). That
is an anti-pattern that couples the pure logic to a real MySQL connection.

Here the data source is abstracted behind :class:`AISRepository`. Two offline
implementations are provided (in-memory and CSV); NEITHER opens a real database
connection. A real MySQL/TimescaleDB implementation can be added later by
subclassing :class:`AISRepository` without touching the pure calculation layer.

Spec reference: ``logic-spec/01-core-emission-grid-logic.md`` section 1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import pandas as pd

from .models import ShipParams


class AISRepository(ABC):
    """Abstract source of AIS tracks and ship particulars.

    The reference queried ``ais_new2`` (tracks) and ``ship_info`` (ships). This
    interface mirrors those two accessors plus a distinct-MMSI helper, all DB
    agnostic.
    """

    @abstractmethod
    def get_ais_track(
        self, region: int, mmsi: int, start_date: datetime, end_date: datetime
    ) -> pd.DataFrame:
        """Return a track ordered by ``reg_date`` asc, de-duplicated on
        ``reg_date``, with a ``time_diff_second`` column (faithful to
        ``get_ais_data``)."""

    @abstractmethod
    def get_ship_params(self, mmsi: int) -> ShipParams | None:
        """Return ship particulars for ``mmsi`` or ``None`` if unknown."""

    @abstractmethod
    def get_mmsis(self, region: int, start_date: datetime, end_date: datetime) -> list[int]:
        """Distinct MMSIs active in the region/time window (faithful to
        ``get_user_ids``)."""


def _prepare_track(df: pd.DataFrame) -> pd.DataFrame:
    """Order, de-duplicate, and compute ``time_diff_second`` (faithful to
    ``get_ais_data``)."""
    df = df.copy()
    df["reg_date"] = pd.to_datetime(df["reg_date"])
    df = df.sort_values("reg_date")
    df = df.drop_duplicates(subset="reg_date", keep="first").reset_index(drop=True)
    df["time_diff_second"] = df["reg_date"].diff().dt.total_seconds()
    return df


class InMemoryRepository(AISRepository):
    """In-memory repository backed by plain DataFrames / dicts.

    ``tracks`` is a single DataFrame containing at least the columns
    ``region``, ``user_id`` (=MMSI), ``reg_date``, ``latitude``, ``longitude``,
    ``sog`` (matching the ``ais_new2`` schema). ``ships`` maps MMSI ->
    :class:`ShipParams`.
    """

    def __init__(self, tracks: pd.DataFrame, ships: dict[int, ShipParams]):
        self._tracks = tracks.copy()
        self._ships = dict(ships)

    def get_ais_track(self, region, mmsi, start_date, end_date) -> pd.DataFrame:
        df = self._tracks
        mask = (
            (df["region"] == region)
            & (df["user_id"] == mmsi)
            & (pd.to_datetime(df["reg_date"]) >= pd.to_datetime(start_date))
            & (pd.to_datetime(df["reg_date"]) <= pd.to_datetime(end_date))
        )
        return _prepare_track(df[mask])

    def get_ship_params(self, mmsi) -> ShipParams | None:
        return self._ships.get(mmsi)

    def get_mmsis(self, region, start_date, end_date) -> list[int]:
        df = self._tracks
        mask = (
            (df["region"] == region)
            & (pd.to_datetime(df["reg_date"]) >= pd.to_datetime(start_date))
            & (pd.to_datetime(df["reg_date"]) <= pd.to_datetime(end_date))
        )
        return sorted(df[mask]["user_id"].unique().tolist())


class CSVRepository(AISRepository):
    """CSV-backed repository for offline runs / fixtures.

    ``tracks_csv`` columns match ``ais_new2``; ``ships_csv`` columns match the
    :class:`ShipParams` fields (``mmsi``, ``total_kw_main_eng``,
    ``aux_engine_total_kw``, ``service_speed``, ``ship_type`` and optional
    ``name_of_ship``). No database connection is opened.
    """

    def __init__(self, tracks_csv: str | Path, ships_csv: str | Path):
        tracks = pd.read_csv(tracks_csv)
        ships_df = pd.read_csv(ships_csv)
        ships: dict[int, ShipParams] = {}
        for _, r in ships_df.iterrows():
            ships[int(r["mmsi"])] = ShipParams(
                mmsi=int(r["mmsi"]),
                total_kw_main_eng=float(r["total_kw_main_eng"]),
                aux_engine_total_kw=float(r["aux_engine_total_kw"]),
                service_speed=float(r["service_speed"]),
                ship_type=str(r["ship_type"]),
                name_of_ship=str(r.get("name_of_ship", "")),
            )
        self._delegate = InMemoryRepository(tracks, ships)

    def get_ais_track(self, region, mmsi, start_date, end_date) -> pd.DataFrame:
        return self._delegate.get_ais_track(region, mmsi, start_date, end_date)

    def get_ship_params(self, mmsi) -> ShipParams | None:
        return self._delegate.get_ship_params(mmsi)

    def get_mmsis(self, region, start_date, end_date) -> list[int]:
        return self._delegate.get_mmsis(region, start_date, end_date)
