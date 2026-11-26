"""Typed schema and validation for catalogue.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CATALOGUE_PATH = Path(__file__).with_name("catalogue.yaml")

CATEGORIES = {"waste_heat", "stranded_power", "water", "enabler"}
DEMAND_DRIVERS = {"heating_degree", "cooling_degree", "constant", "price_volatility", "water_stress"}
SEASONALITY = {"year_round", "heating_season", "cooling_season"}
WATER_ROLES = {"consumer", "producer", "saver", "neutral"}
CONFIDENCE = {"literature", "estimate", "unverified"}
RATINGS = {"high", "medium", "low"}

Range = Optional[tuple[float, float]]


def _range(v, name: str) -> Range:
    if v is None:
        return None
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)):
        raise ValueError(f"{name}: expected [low, high], got {v!r}")
    lo, hi = float(v[0]), float(v[1])
    if lo > hi:
        raise ValueError(f"{name}: low {lo} > high {hi}")
    return (lo, hi)


@dataclass(frozen=True)
class Quantity:
    value: tuple[float, float]
    unit: str

    @staticmethod
    def parse(d, name: str) -> Optional["Quantity"]:
        if d is None:
            return None
        return Quantity(_range(d["value"], name + ".value"), str(d["unit"]))


@dataclass(frozen=True)
class Heat:
    source_t_min_c: Range
    source_t_ideal_c: Range
    process_t_c: Range
    heat_pump_boost_ok: bool
    demand: Optional[Quantity]

    @property
    def needs_heat(self) -> bool:
        return self.source_t_min_c is not None


@dataclass(frozen=True)
class Ambient:
    t_db_ideal_c: Range
    t_db_tolerable_c: Range
    note: str = ""
    supply_approach_k: Optional[float] = None


@dataclass(frozen=True)
class Solution:
    id: str
    name: str
    category: str
    description: str
    heat: Heat
    ambient: Ambient
    demand_driver: str
    seasonality: str
    water_role: str
    water_need: Optional[Quantity]
    output_product: str
    output_unit: str
    capex: Optional[Quantity]
    opex: Optional[Quantity]
    trl: tuple[float, float]
    israel_fit: str
    israel_note: str
    confidence: str
    unverified_fields: tuple[str, ...] = field(default_factory=tuple)
    source_ids: tuple[str, ...] = field(default_factory=tuple)
    requires: tuple[str, ...] = field(default_factory=tuple)


def _parse_solution(d: dict) -> Solution:
    sid = d["id"]
    h, a, w, e = d["heat"], d["ambient"], d["water"], d["economics"]
    s = Solution(
        id=sid,
        name=d["name"],
        category=d["category"],
        description=" ".join(str(d.get("description", "")).split()),
        heat=Heat(
            source_t_min_c=_range(h.get("source_t_min_c"), f"{sid}.heat.source_t_min_c"),
            source_t_ideal_c=_range(h.get("source_t_ideal_c"), f"{sid}.heat.source_t_ideal_c"),
            process_t_c=_range(h.get("process_t_c"), f"{sid}.heat.process_t_c"),
            heat_pump_boost_ok=bool(h.get("heat_pump_boost_ok", False)),
            demand=Quantity.parse(h.get("demand"), f"{sid}.heat.demand"),
        ),
        ambient=Ambient(
            t_db_ideal_c=_range(a.get("t_db_ideal_c"), f"{sid}.ambient.t_db_ideal_c"),
            t_db_tolerable_c=_range(a.get("t_db_tolerable_c"), f"{sid}.ambient.t_db_tolerable_c"),
            note=a.get("note", ""),
            supply_approach_k=None if a.get("supply_approach_k") is None else float(a["supply_approach_k"]),
        ),
        demand_driver=d["demand_driver"],
        seasonality=d["seasonality"],
        water_role=w["role"],
        water_need=Quantity.parse(w.get("need"), f"{sid}.water.need"),
        output_product=d["output"]["product"],
        output_unit=d["output"]["unit"],
        capex=Quantity.parse(e.get("capex"), f"{sid}.economics.capex"),
        opex=Quantity.parse(e.get("opex"), f"{sid}.economics.opex"),
        trl=_range(d["trl"], f"{sid}.trl"),
        israel_fit=d["israel_fit"]["rating"],
        israel_note=d["israel_fit"].get("note", ""),
        confidence=d["confidence"],
        unverified_fields=tuple(d.get("unverified_fields", [])),
        source_ids=tuple(d.get("source_ids", [])),
        requires=tuple(d.get("requires", [])),
    )
    checks = [
        (s.category in CATEGORIES, "category"), (s.demand_driver in DEMAND_DRIVERS, "demand_driver"),
        (s.seasonality in SEASONALITY, "seasonality"), (s.water_role in WATER_ROLES, "water.role"),
        (s.confidence in CONFIDENCE, "confidence"), (s.israel_fit in RATINGS, "israel_fit.rating"),
        (1 <= s.trl[0] <= s.trl[1] <= 9, "trl"), (len(s.source_ids) > 0, "source_ids"),
    ]
    for ok, what in checks:
        if not ok:
            raise ValueError(f"{sid}: invalid {what}")
    hh = s.heat
    if hh.needs_heat and (hh.source_t_ideal_c is None or hh.source_t_min_c[0] > hh.source_t_ideal_c[1]):
        raise ValueError(f"{sid}: source_t_ideal_c missing or below source_t_min_c")
    return s


def load_catalogue(path: Path | str | None = None) -> dict[str, Solution]:
    """Load and validate the catalogue. Returns {solution_id: Solution} in file order."""
    raw = yaml.safe_load(Path(path or CATALOGUE_PATH).read_text(encoding="utf-8"))
    source_ids = {s["id"] for s in raw["sources"]}
    out: dict[str, Solution] = {}
    for d in raw["solutions"]:
        s = _parse_solution(d)
        if s.id in out:
            raise ValueError(f"duplicate solution id {s.id}")
        missing = set(s.source_ids) - source_ids
        if missing:
            raise ValueError(f"{s.id}: unknown source_ids {sorted(missing)}")
        out[s.id] = s
    return out


def load_sources(path: Path | str | None = None) -> dict[str, dict]:
    raw = yaml.safe_load(Path(path or CATALOGUE_PATH).read_text(encoding="utf-8"))
    return {s["id"]: s for s in raw["sources"]}
