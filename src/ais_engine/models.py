"""Plain data models for the pure calculation layer.

The original reference used a SQLAlchemy ORM model (``ShipInfo``) bound to the
``ship_info`` MySQL table. For the pure (DB-free) layer we use a frozen
dataclass that carries only the fields the fuel formulas actually read:

- ``total_kw_main_eng``  (main engine kW)         -> main usage + SFOC lookup
- ``aux_engine_total_kw`` (auxiliary engine kW)   -> aux usage
- ``service_speed``       (design speed, kn)      -> main load factor
- ``ship_type``           (e.g. "Tanker")         -> aux load factor branch

Spec reference: ``logic-spec/01-core-emission-grid-logic.md`` section 1.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShipParams:
    """Ship particulars required by the fuel-usage formulas.

    Field names mirror the verified ``ship_info`` columns so the port stays
    faithful to the reference (see spec section 6 column-mapping note).
    """

    mmsi: int
    total_kw_main_eng: float
    aux_engine_total_kw: float
    service_speed: float
    ship_type: str
    name_of_ship: str = ""
