"""First pass feasibility screening of catalogue solutions for one site.

Inputs use the field names of the shared database:
- heat_profile: one row of hd.site_heat_profiles() as dict (cooling_type, chip_family,
  it_load_mw, facility_supply_temp_c, facility_return_temp_c, liquid_heat_share, is_assumed, ...)
- site_summary: hd.get_site(id).summary() (heating_degree_hours_18c, cooling_degree_hours_18c,
  t_db_mean_c, price_mean_usd_mwh, price_p10_usd_mwh, price_p90_usd_mwh, ...)
- weather (optional): hd.get_site(id).weather with column t_db_c (hourly)
- context (optional): {"coastal": bool, "water_stress": 0..1, "country_iso2": "IL"}

Score per solution, each part in 0..1:
    temperature  can the heat source drive the solution (direct, or with a heat pump at a penalty)
    demand       does the local climate or market create demand (driver from the catalogue)
    ambient      share of hours with outdoor temperature in the ideal or tolerable range
    maturity     TRL / 9
    total = temperature * (0.45 demand + 0.30 ambient + 0.25 maturity), 0 if a hard requirement fails

It ranks POTENTIAL. It does not know whether a fish farm or a desalination plant exists next to the site.

Reference scales below are HEATBEAT screening assumptions, not literature values.
"""
from __future__ import annotations

import math
from typing import Optional

from .schema import Solution, load_catalogue

# Screening reference scales (assumptions, tune as a team)
HDH_FULL_SCORE = 80_000.0      # heating degree hours (base 18 C) for a full heating demand score; about Stockholm
CDH_FULL_SCORE = 30_000.0      # cooling degree hours (base 18 C) for a full cooling demand score
AIR_EXHAUST_T_C = 35.0         # assumed hot aisle exhaust temperature when liquid_heat_share is 0
HEAT_PUMP_MAX_LIFT_K = 60.0    # beyond this lift the booster is treated as infeasible
CARNOT_FRACTION = 0.5          # mid value of heat_pump_booster demand range in the catalogue

# Rough water stress by country (0..1). UNVERIFIED placeholder, replace with WRI Aqueduct values.
WATER_STRESS_DEFAULT = {"IL": 0.9, "US": 0.4}

CONSTANT_DEMAND_SCORE = 0.6   # demand not climate driven: neutral, a local offtaker still has to be found
AIR_CAPTURE_FACTOR = 0.7      # penalty for capturing heat from exhaust air instead of a liquid loop

WEIGHTS = {"demand": 0.45, "ambient": 0.30, "maturity": 0.25}


def heat_pump_cop(t_source_c: float, t_sink_c: float, carnot_fraction: float = CARNOT_FRACTION) -> float:
    """Heating COP estimate: carnot_fraction * T_sink / (T_sink - T_source), temperatures in C."""
    lift = t_sink_c - t_source_c
    if lift <= 0:
        return float("inf")
    return carnot_fraction * (t_sink_c + 273.15) / lift


def _num(v) -> Optional[float]:
    """float or None; NaN (pandas missing value) becomes None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _source_temperature(hp: dict) -> tuple[float, str]:
    share = _num(hp.get("liquid_heat_share")) or 0.0
    t = _num(hp.get("facility_return_temp_c"))
    if share <= 0 or t is None:
        t_air = _num(hp.get("exhaust_air_temp_c")) or AIR_EXHAUST_T_C
        return t_air, f"air side heat, exhaust air {t_air:.0f} C"
    return t, f"liquid return {t:.0f} C ({share:.0%} of IT heat in liquid)"


def _temperature_score(s: Solution, t: float) -> tuple[float, str, Optional[float]]:
    h = s.heat
    if not h.needs_heat:
        return 1.0, "no heat input needed", None
    t_min, t_ideal = h.source_t_min_c[0], h.source_t_ideal_c[0]
    if t >= t_ideal:
        return 1.0, f"source {t:.0f} C >= ideal {t_ideal:.0f} C", None
    if t >= t_min:
        f = 0.5 + 0.5 * (t - t_min) / max(t_ideal - t_min, 1e-9)
        return f, f"source {t:.0f} C between min {t_min:.0f} C and ideal {t_ideal:.0f} C", None
    if h.heat_pump_boost_ok and (t_ideal - t) <= HEAT_PUMP_MAX_LIFT_K:
        cop = heat_pump_cop(t, t_ideal)
        f = 0.4 * min(1.0, cop / 5.0)
        return f, f"needs heat pump {t:.0f} -> {t_ideal:.0f} C (COP about {cop:.1f})", cop
    return 0.0, f"source {t:.0f} C below min {t_min:.0f} C and no heat pump option", None


def _demand_score(s: Solution, summ: dict, ctx: dict) -> tuple[float, str]:
    d = s.demand_driver
    if d == "heating_degree":
        hdh = float(summ.get("heating_degree_hours_18c") or 0)
        return min(1.0, hdh / HDH_FULL_SCORE), f"heating degree hours {hdh:,.0f}"
    if d == "cooling_degree":
        cdh = float(summ.get("cooling_degree_hours_18c") or 0)
        return min(1.0, cdh / CDH_FULL_SCORE), f"cooling degree hours {cdh:,.0f}"
    if d == "water_stress":
        ws = ctx.get("water_stress", WATER_STRESS_DEFAULT.get(ctx.get("country_iso2", ""), 0.5))
        return float(ws), f"water stress {ws:.2f}"
    if d == "price_volatility":
        mean = float(summ.get("price_mean_usd_mwh") or 0)
        if mean <= 0:
            return 0.0, "no price data"
        spread = (float(summ["price_p90_usd_mwh"]) - float(summ["price_p10_usd_mwh"])) / mean
        return min(1.0, spread), f"price spread p90-p10 = {spread:.0%} of mean"
    return CONSTANT_DEMAND_SCORE, "demand not climate driven, offtaker must exist locally"


def _ambient_score(s: Solution, summ: dict, weather) -> tuple[float, str]:
    ideal, tol = s.ambient.t_db_ideal_c, s.ambient.t_db_tolerable_c
    if ideal is None:
        return 1.0, "not climate dependent"
    if weather is not None and "t_db_c" in getattr(weather, "columns", []):
        t = weather["t_db_c"]
        in_ideal = float(((t >= ideal[0]) & (t <= ideal[1])).mean())
        in_tol = float(((t >= tol[0]) & (t <= tol[1])).mean()) if tol else in_ideal
        return in_ideal + 0.5 * (in_tol - in_ideal), f"{in_ideal:.0%} of hours ideal, {in_tol:.0%} tolerable"
    m = summ.get("t_db_mean_c")
    if m is None:
        return 0.5, "no weather, neutral"
    if ideal[0] <= m <= ideal[1]:
        return 1.0, f"mean {m:.1f} C in ideal range"
    if tol and tol[0] <= m <= tol[1]:
        return 0.5, f"mean {m:.1f} C tolerable"
    return 0.0, f"mean {m:.1f} C outside tolerable range"


def screen(heat_profile: dict, site_summary: dict, weather=None, context: Optional[dict] = None,
           catalogue: Optional[dict[str, Solution]] = None, include_enablers: bool = False) -> list[dict]:
    """Rank catalogue solutions for one site. Returns a list of dicts, best first."""
    cat = catalogue or load_catalogue()
    ctx = dict(context or {})
    t_src, src_note = _source_temperature(heat_profile)
    it_mw = _num(heat_profile.get("it_load_mw"))
    share = _num(heat_profile.get("liquid_heat_share")) or 0.0
    if _num(heat_profile.get("facility_return_temp_c")) is None:
        share = 0.0
    rows = []
    for s in cat.values():
        if s.category == "enabler" and not include_enablers:
            continue
        blockers = [r for r in s.requires if not ctx.get(r, False)]
        f_t, why_t, cop = _temperature_score(s, t_src)
        if share <= 0 and s.heat.needs_heat:
            f_t, why_t = f_t * AIR_CAPTURE_FACTOR, why_t + f", x{AIR_CAPTURE_FACTOR} for air side capture"
        f_d, why_d = _demand_score(s, site_summary, ctx)
        f_a, why_a = _ambient_score(s, site_summary, weather)
        f_m = s.trl[1] / 9.0
        total = 0.0 if blockers else f_t * (WEIGHTS["demand"] * f_d + WEIGHTS["ambient"] * f_a + WEIGHTS["maturity"] * f_m)
        rows.append({
            "solution_id": s.id, "name": s.name, "category": s.category,
            "score": round(total, 3),
            "temperature": round(f_t, 3), "demand": round(f_d, 3), "ambient": round(f_a, 3), "maturity": round(f_m, 3),
            "needs_heat_pump": cop is not None, "heat_pump_cop": None if cop is None else round(cop, 2),
            "blocked_by": blockers,
            "reasons": [src_note, why_t, why_d, why_a] + [f"requires {b}" for b in blockers],
            "recoverable_heat_mw": None if it_mw is None or not s.heat.needs_heat else round(it_mw * (share if share > 0 else 1.0), 2),
            "heat_profile_is_assumed": bool(heat_profile.get("is_assumed", True)),
            "catalogue_confidence": s.confidence, "israel_fit": s.israel_fit,
        })
    return sorted(rows, key=lambda r: r["score"], reverse=True)
