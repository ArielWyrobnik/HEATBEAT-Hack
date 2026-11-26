"""DSX evaluator v3.3: 8760 h physics, 13 knock-out gates, viability 0 to 5 and eco grade A to F.

Port of the DSX engine used in the Heat Beat DSX frontend (frontend PRs #52 to #63), with two
changes so it runs on the database inputs:

* Climate: the real hourly dry bulb temperature of the site (8760 values, heatbeat_ranking.climate)
  instead of a cosine built from daily minimum and maximum.
* Heat prices and fuel carbon are on a heat basis (USD and g CO2 per kWh of heat from a gas boiler),
  as heatbeat_data.market provides them. The JS engine took fuel prices and divided by a 0.90
  boiler; here that division is already inside the input (market uses a 0.85 boiler, EPA factors).
* DAC is paid the 45Q credit (p_dac_credit_usd_ton) instead of the general carbon price.

v3.4 calibration against real deployments (frontend reference pins, docs/DSX.md), same in both engines:
* BTES / ATES is charged only with surplus heat in the warm part of the year (demand ramps from 0 at
  10 C to full at 20 C) instead of a flat 70 % all year, since a seasonal store takes summer heat and
  gives it back in winter.
* BTES / ATES needs a heat user to discharge to (existing heat network or one within 3 km).
* Fish farm and digester zoning: industrial zoning OR at least 2 ha of farmland within 1 km. The
  database ind_zoning is an OSM proxy that only sees industrial land use, so rural sites on farmland
  were wrongly treated as urban.

Every constant below is a planning assumption of the DSX evaluator (not a site fact).
"""
from __future__ import annotations

import math

import numpy as np

VERSION = "3.4.0-db"
HOURS = 8760

C = {
    "carnot_eta": 0.50, "approach_k": 5.0, "cop_cap": 8.0, "air_offset_c": 12.0,
    "orc_eta_frac": 0.45, "orc_cond_offset_c": 10.0, "hp_capex_usd_kw": 600.0, "opex_frac": 0.02,
    "payback_best_yr": 3.0, "payback_worst_yr": 15.0, "availability": 0.998,
    "weights": {"thermo": 0.30, "climate": 0.30, "econ": 0.25, "util": 0.15},
    "eco_weights": {"ghg": 0.40, "water": 0.30, "local": 0.30},
    "absorption_cop": 0.70, "chiller_cop": 5.0, "med_kwh_th_m3": 60.0, "ro_kwh_e_m3": 3.5,
    "dac_mwh_th_t": 1.8, "btes_round_trip": 0.75, "market_ref_m": 100000.0,
    "mit_mult": {"low": 1.0, "med": 0.70, "high": 0.35},
}
GRADE_BANDS = [(4.20, "A"), (3.40, "B"), (2.60, "C"), (1.80, "D"), (-math.inf, "F")]


def _clip(x, lo, hi):
    return min(hi, max(lo, x))


def _lin(x, x0, x1):
    return _clip((x - x0) / (x1 - x0), 0.0, 1.0)


def _km(m):
    return f"{m / 1000:.1f}"


def _n0(x):
    return f"{round(x):,}"


def grade(e: float) -> str:
    return next(g for lo, g in GRADE_BANDS if e >= lo)


# ---------------------------------------------------------------- knock-out gates
# Each returns the list of failed checks; every message states the site value and the limit.

def _gf(s, f):
    if s["is_greenfield"] != 1:
        f.append("only possible when designed in with a new build; this is an existing site")


def _chk(cond, msg, f):
    if not cond:
        f.append(msg)


def g_fish(s, h):
    f = []
    _chk(h["mean_amb"] <= 26, f"mean ambient {h['mean_amb']:.1f} C is above the 26 C limit for fish tanks", f)
    _chk(h["gt30"] < 1500, f"{_n0(h['gt30'])} h above 30 C (limit under 1,500 h)", f)
    _chk(s["slope_deg"] <= 8, f"slope {s['slope_deg']:g} deg (limit 8 deg)", f)
    _chk(s["flat_land_m2"] >= 10000, f"flat land {_n0(s['flat_land_m2'])} m2, needs 10,000 m2 for RAS tanks", f)
    _chk(s["d_water_m"] <= 3000, f"water intake {_km(s['d_water_m'])} km away (limit 3 km)", f)
    _chk(s["wsi_index"] < 4.0, f"water stress {s['wsi_index']:g} (must be under 4.0)", f)
    _chk(s["q_dc_mw"] >= 0.5, f"heat source {s['q_dc_mw']:g} MW (needs 0.5 MW)", f)
    _chk(s["ind_zoning"] == 1 or s["agri_land_m2"] >= 20000,
         "needs industrial or agricultural land: no industrial zoning and under 2 ha of farmland within 1 km", f)
    return f


def g_dh(s, h):
    f = []
    _chk(h["lt15"] >= 2000, f"only {_n0(h['lt15'])} h below 15 C (needs 2,000 h of heating demand)", f)
    if s["is_greenfield"] == 1:
        _chk(s["d_dh_m"] <= 3000, f"heat network {_km(s['d_dh_m'])} km away (limit 3 km for a new build)", f)
        _chk(s["rho_heat_mwh_m"] >= 1.5, f"heat density {s['rho_heat_mwh_m']:g} MWh/m/yr (needs 1.5 for a new build)", f)
    else:
        _chk(s["has_existing_dh"] == 1, "no existing district heating network to connect to (existing site)", f)
        _chk(s["d_dh_m"] <= 800, f"heat network {_n0(s['d_dh_m'])} m away (limit 800 m for an existing site)", f)
        _chk(s["rho_heat_mwh_m"] >= 2.5, f"heat density {s['rho_heat_mwh_m']:g} MWh/m/yr (needs 2.5 for an existing site)", f)
    return f


def g_biogas(s, h):
    f = []
    _chk(h["lt25"] >= 2500, f"only {_n0(h['lt25'])} h below 25 C (needs 2,500 h)", f)
    _chk(s["d_bio_m"] <= 25000, f"feedstock {_km(s['d_bio_m'])} km away (limit 25 km)", f)
    _chk(s["slope_deg"] <= 10, f"slope {s['slope_deg']:g} deg (limit 10 deg)", f)
    _chk(s["ind_zoning"] == 1 or s["agri_land_m2"] >= 20000,
         "needs industrial or agricultural land: no industrial zoning and under 2 ha of farmland within 1 km", f)
    return f


def g_absorption(s, h):
    f = []
    _chk(h["max_tdc"] >= 65, f"coolant peaks at {h['max_tdc']:.1f} C; absorption chillers need 65 C", f)
    _chk(h["gt24"] >= 1500, f"only {_n0(h['gt24'])} h above 24 C (needs 1,500 h of cooling demand)", f)
    _chk(s["wsi_index"] < 3.8, f"water stress {s['wsi_index']:g} (must be under 3.8)", f)
    return f


def g_orc(s, h):
    f = []
    _chk(h["min_tdc"] >= 80, f"coolant drops to {h['min_tdc']:.1f} C; ORC power needs 80 C all year", f)
    _chk(h["lt30"] >= 5000, f"only {_n0(h['lt30'])} h below 30 C (needs 5,000 h for condenser cooling)", f)
    return f


def g_dac(s, h):
    f = []
    _chk(s["d_co2_m"] <= 50000, f"CO2 storage or user {_km(s['d_co2_m'])} km away (limit 50 km)", f)
    _chk(h["gt35"] < 1500, f"{_n0(h['gt35'])} h above 35 C (limit under 1,500 h)", f)
    return f


def g_btes(s, h):
    f = []
    _gf(s, f)
    _chk(s["geo_storage_score"] >= 3, f"ground storage score {s['geo_storage_score']:g} of 5 (needs 3)", f)
    _chk(h["lt15"] >= 2500, f"only {_n0(h['lt15'])} h below 15 C (needs 2,500 h)", f)
    _chk(h["gt20"] >= 1000, f"only {_n0(h['gt20'])} h above 20 C (needs 1,000 h to charge the store)", f)
    _chk(s["has_existing_dh"] == 1 or s["d_dh_m"] <= 3000,
         f"no heat user to discharge the store to: heat network {_km(s['d_dh_m'])} km away (limit 3 km)", f)
    return f


def g_feedwater(s, h):
    f = []
    _gf(s, f)
    _chk(s["d_pp_m"] <= 1500, f"power plant {_km(s['d_pp_m'])} km away (limit 1.5 km)", f)
    _chk(s["q_fw_mw"] >= 2.0, f"feedwater heat demand {s['q_fw_mw']:g} MW (needs 2 MW)", f)
    return f


def g_desal(s, h):
    f = []
    _gf(s, f)
    _chk(s["d_coast_m"] <= 5000, f"coast {_km(s['d_coast_m'])} km away (limit 5 km)", f)
    _chk(s["dz_m"] <= 50, f"site {s['dz_m']:g} m above the sea (limit 50 m pumping head)", f)
    _chk(s["wsi_index"] >= 2.0, f"water stress {s['wsi_index']:g}; under 2.0 there is no need for desalinated water", f)
    return f


def g_biomass(s, h):
    f = []
    _gf(s, f)
    _chk(s["d_bio_m"] <= 25000, f"feedstock {_km(s['d_bio_m'])} km away (limit 25 km)", f)
    _chk(s["ind_zoning"] == 1, "needs industrial zoning", f)
    _chk(s["slope_deg"] <= 10, f"slope {s['slope_deg']:g} deg (limit 10 deg)", f)
    return f


def g_drying(s, h):
    f = []
    _gf(s, f)
    _chk(s["ind_zoning"] == 1, "needs industrial zoning", f)
    _chk(s["q_dc_mw"] >= 5.0, f"heat source {s['q_dc_mw']:g} MW (needs 5 MW)", f)
    _chk(s["slope_deg"] <= 8, f"slope {s['slope_deg']:g} deg (limit 8 deg)", f)
    return f


def g_snowmelt(s, h):
    f = []
    _gf(s, f)
    _chk(s["campus_area_m2"] >= 20000, f"paved area {_n0(s['campus_area_m2'])} m2 (needs 20,000 m2)", f)
    _chk(h["le2"] >= 800, f"only {_n0(h['le2'])} h at or below 2 C (needs 800 h)", f)
    return f


def g_greenhouse(s, h):
    f = []
    _gf(s, f)
    _chk(s["agri_land_m2"] >= 20000, f"farm land {_n0(s['agri_land_m2'])} m2 (needs 20,000 m2)", f)
    _chk(s["slope_deg"] <= 6, f"slope {s['slope_deg']:g} deg (limit 6 deg)", f)
    _chk(s["wsi_index"] < 4.0, f"water stress {s['wsi_index']:g} (must be under 4.0)", f)
    _chk(h["lt18"] >= 2000, f"only {_n0(h['lt18'])} h below 18 C (needs 2,000 h)", f)
    return f


def _area_cap(key, w_m2):
    return lambda s: min(1.0, s[key] * w_m2 / 1e6 / s["q_dc_mw"])


def _o(id_, key, name, mode, t_sink, demand, product, capex, pipe, dist_key, dist_max, market, wf, li, cap, gate):
    return dict(id=id_, key=key, name=name, mode=mode, t_sink=t_sink, demand=demand, product=product,
                capex_usd_kw=capex, pipe_usd_m=pipe, dist_key=dist_key, dist_max_m=dist_max,
                market_sensitive=market, water_factor=wf, local_impact=li, cap=cap, gate=gate)


OPTIONS = [
    _o(1, "fish_farm_ras", "Fish Farm (RAS)", "both", 28, ("heating", 28, 20, 0.2), "heat", 900, 600, "d_water_m", 3000, True, 0.6, 0.8, _area_cap("flat_land_m2", 250), g_fish),
    _o(2, "district_heating", "District Heating", "adaptive", 65, ("heating", 15, 20, 0.15), "heat", 250, 1500, "d_dh_m", 3000, False, 0.1, 0.2, lambda s: min(1.0, s["rho_heat_mwh_m"] / 3.0), g_dh),
    _o(3, "biogas", "Biogas Generator", "both", 38, ("heating", 25, 25, 0.3), "heat", 700, 300, "d_bio_m", 25000, False, 0.3, 0.5, lambda s: 0.3, g_biogas),
    _o(4, "absorption_cooling", "Absorption Cooling", "both", 85, ("cooling", 24, 10), "cooling", 450, 0, None, 1, False, 0.8, 0.4, lambda s: 1.0, g_absorption),
    _o(5, "orc", "Organic Rankine Cycle", "both", 100, ("constant", 0.9), "power", 2500, 0, None, 1, False, 0.5, 0.3, lambda s: 1.0, g_orc),
    _o(6, "dac", "Carbon Capture / DAC", "both", 90, ("constant", 0.85), "co2", 1500, 400, "d_co2_m", 50000, False, 0.2, 0.2, lambda s: 1.0, g_dac),
    _o(7, "btes_ates", "BTES / ATES Storage", "greenfield", 55, ("cooling", 10, 10), "stored_heat", 600, 0, None, 1, False, 0.3, 0.6, lambda s: 1.0, g_btes),
    _o(8, "feedwater_preheat", "Boiler Feedwater Preheat", "greenfield", 55, ("constant", 0.85), "steam", 200, 800, "d_pp_m", 1500, False, 0.2, 0.3, lambda s: min(1.0, s["q_fw_mw"] / s["q_dc_mw"]), g_feedwater),
    _o(9, "desalination", "Desalination (MED/MD)", "greenfield", 70, ("constant", 0.9), "water", 1200, 900, "d_coast_m", 5000, False, -1.0, 1.0, lambda s: 1.0, g_desal),
    _o(10, "biomass_processing", "Biomass Processing", "greenfield", 65, ("constant", 0.7), "heat", 500, 0, "d_bio_m", 25000, True, 0.3, 0.5, lambda s: 0.6, g_biomass),
    _o(11, "industrial_drying", "Industrial Drying", "greenfield", 75, ("constant", 0.8), "heat", 450, 0, None, 1, False, 0.4, 0.4, lambda s: 1.0, g_drying),
    _o(12, "snow_melt", "Radiant / Snow-Melt", "greenfield", 35, ("heating", 2, 10, 0.0), "heat", 350, 0, None, 1, False, 0.1, 0.2, _area_cap("campus_area_m2", 400), g_snowmelt),
    _o(13, "greenhouse", "Co-Designed Greenhouse", "greenfield", 40, ("heating", 18, 25, 0.1), "heat", 400, 0, None, 1, True, 0.7, 0.4, _area_cap("agri_land_m2", 300), g_greenhouse),
]


# ---------------------------------------------------------------- physics

def coolant(s: dict, tamb: np.ndarray) -> np.ndarray:
    if s["cooling_type"] == "liquid":
        return np.full(HOURS, float(s["t_dc_base_c"]))
    return np.maximum(float(s["t_dc_base_c"]), tamb + C["air_offset_c"])


def heat_pump(tdc: np.ndarray, tsink: float):
    a = C["approach_k"]
    thot = tsink + a
    direct = tdc >= tsink + a
    lift = np.maximum(thot - (tdc - a), 1e-6)
    cop = np.clip(C["carnot_eta"] * (thot + 273.15) / lift, 1.05, C["cop_cap"])
    cop = np.where(direct, np.inf, cop)
    return cop, direct


def demand(o: dict, tamb: np.ndarray) -> np.ndarray:
    d = o["demand"]
    if d[0] == "heating":
        return np.clip((d[1] - tamb) / d[2], d[3], 1.0)
    if d[0] == "cooling":
        return np.clip((tamb - d[1]) / d[2], 0.0, 1.0)
    return np.full(HOURS, float(d[1]))


def climate_stats(tamb: np.ndarray, tdc: np.ndarray) -> dict:
    n = lambda m: int(np.count_nonzero(m))  # noqa: E731
    return {"mean_amb": float(tamb.mean()), "gt20": n(tamb > 20), "gt24": n(tamb > 24), "gt30": n(tamb > 30),
            "gt35": n(tamb > 35), "lt15": n(tamb < 15), "lt18": n(tamb < 18), "lt25": n(tamb < 25),
            "lt30": n(tamb < 30), "le2": n(tamb <= 2), "min_tdc": float(tdc.min()), "max_tdc": float(tdc.max())}


def _r(x, d=2):
    return None if x is None or not math.isfinite(x) else round(float(x), d)


def evaluate_option(o: dict, s: dict, tamb: np.ndarray, tdc: np.ndarray, h: dict, hp_capex: float | None = None) -> dict:
    fails = o["gate"](s, h)
    gate = 0 if fails else 1
    q = float(s["q_dc_mw"])
    cap = _clip(o["cap"](s), 0.0, 1.0)
    raw = demand(o, tamb)
    qsrc = q * raw * cap * C["availability"]
    cop = direct = None
    mean_eta = None
    if o["key"] == "orc":
        carnot = np.maximum(1 - (tamb + C["orc_cond_offset_c"] + 273.15) / (tdc + 273.15), 0.0)
        qdel = qsrc * C["orc_eta_frac"] * carnot
        whp = np.zeros(HOURS)
        qs0 = qsrc.sum()
        mean_eta = float(qdel.sum() / qs0) if qs0 > 0 else 0.0
        p_thermo = 5 * _lin(mean_eta, 0, 0.12)
    else:
        cop, direct = heat_pump(tdc, o["t_sink"])
        with np.errstate(divide="ignore", invalid="ignore"):
            whp = np.where(direct, 0.0, qsrc / (cop - 1))
        qdel = qsrc + whp
        qd0 = qdel.sum()
        free = 1 - whp.sum() / qd0 if qd0 > 0 else 0.0
        p_thermo = 5 * _lin(free, 0.0, 1.0)
    Qs, Qd, W = float(qsrc.sum()), float(qdel.sum()), float(whp.sum())

    active = int(np.count_nonzero(raw >= 0.2))
    hot = int(np.count_nonzero(tamb > 35))
    p_climate = 5 * min(1.0, (active / HOURS) / 0.6) * (1 - 0.5 * hot / HOURS)
    util = Qs / (q * HOURS) if q > 0 else 0.0
    dist_pen = 1 - 0.5 * min(1.0, s[o["dist_key"]] / o["dist_max_m"]) if o["dist_key"] else 1.0
    p_util = 5 * util * dist_pen

    # prices: heat basis (USD and g CO2 per kWh of heat a gas boiler would have made)
    p_heat, ci_heat = s["p_fuel_usd_kwh"] * 1000, s["ci_fuel_g_kwh"]
    pe, ci_grid = s["p_elec_usd_kwh"] * 1000, s["ci_grid_g_kwh"]
    qty, unit = Qd, "MWh_th"
    prod = o["product"]
    if prod == "heat":
        value, abated = Qd * p_heat, Qd * ci_heat
    elif prod == "stored_heat":
        qty = Qd * C["btes_round_trip"]
        value, abated = qty * p_heat, qty * ci_heat
    elif prod == "steam":
        value, abated = Qd * s["p_steam_usd_mwh"], Qd * ci_heat
    elif prod == "cooling":
        qty = Qd * C["absorption_cop"]
        es = qty / C["chiller_cop"]
        value, abated, unit = es * pe, es * ci_grid, "MWh_cool"
    elif prod == "power":
        value, abated, unit = Qd * pe, Qd * ci_grid, "MWh_e"
    elif prod == "water":
        qty = Qd * 1000 / C["med_kwh_th_m3"]
        value, abated, unit = qty * s["p_water_usd_m3"], qty * C["ro_kwh_e_m3"] / 1000 * ci_grid, "m3"
    elif prod == "co2":
        qty = Qd / C["dac_mwh_th_t"]
        value, abated, unit = qty * s.get("p_dac_credit_usd_ton", s["p_co2_usd_ton"]), qty * 1000, "tCO2"
    else:
        raise ValueError(prod)
    if o["market_sensitive"]:
        value *= 1 - 0.3 * min(1.0, s["d_market_m"] / C["market_ref_m"])
    net_abated = (abated - W * ci_grid) / 1000
    carbon_rev = 0.0 if prod == "co2" else max(net_abated, 0.0) * s["p_co2_usd_ton"]
    hp_cost = W * pe
    peak_src_kw = q * cap * 1000
    peak_hp_kw = float(qdel.max()) * 1000 if W > 0 else 0.0
    dist = float(s[o["dist_key"]]) if o["dist_key"] else 0.0
    if o.get("capex_usd_kwe") is not None:  # power cycle priced per kW of electric output
        capex_plant = float(qdel.max()) * 1000 * o["capex_usd_kwe"]
    else:
        capex_plant = peak_src_kw * o["capex_usd_kw"]
    capex_pipe = dist * o["pipe_usd_m"]
    capex_hp = peak_hp_kw * (hp_capex or C["hp_capex_usd_kw"]) if W > 0 else 0.0
    capex = capex_plant + capex_pipe + capex_hp
    net_annual = value + carbon_rev - hp_cost - C["opex_frac"] * capex
    payback = capex / net_annual if net_annual > 0 else math.inf
    p_econ = 0.0 if net_annual <= 0 else 5 * _lin(payback, C["payback_worst_yr"], C["payback_best_yr"])
    w = C["weights"]
    raw_v = w["thermo"] * p_thermo + w["climate"] * p_climate + w["econ"] * p_econ + w["util"] * p_util
    viability = round(gate * raw_v, 2)

    intensity = net_abated * 1000 / Qd if Qd > 0 else 0.0
    e_ghg = 1.0 if intensity <= 0 or ci_heat <= 0 else 1 + 4 * _lin(intensity, 0, ci_heat)
    mit = C["mit_mult"][s["mit_tier"]]
    water_credit = 0.8 * s["wsi_index"] * min(util, 1.0) * (1 if s.get("baseline_evaporative") else 0)
    e_water = _clip(5 - 0.8 * s["wsi_index"] * o["water_factor"] * mit + water_credit, 1, 5)
    e_local = _clip(5 - o["local_impact"] * (s["eco_sens_index"] - 1) * mit, 1, 5)
    ew = C["eco_weights"]
    eco = round(ew["ghg"] * e_ghg + ew["water"] * e_water + ew["local"] * e_local, 2)

    mean_cop, direct_hours = None, 0
    if cop is not None:
        on = qsrc > 0
        fin = on & np.isfinite(cop)
        direct_hours = int(np.count_nonzero(on & ~np.isfinite(cop)))
        wsum = qsrc[fin].sum()
        mean_cop = float((cop[fin] * qsrc[fin]).sum() / wsum) if wsum > 0 else None
    return {
        "id": o["id"], "key": o["key"], "name": o["name"], "mode": o["mode"], "t_sink_c": o["t_sink"],
        "ko_pass": bool(gate), "ko_failures": fails, "viability": viability, "viability_ungated": round(raw_v, 2),
        "subscores": {"p_thermo": _r(p_thermo), "p_climate": _r(p_climate), "p_econ": _r(p_econ), "p_util": _r(p_util)},
        "eco_score": eco, "eco_grade": grade(eco),
        "eco_subscores": {"e_ghg": _r(e_ghg), "e_water": _r(e_water), "e_local": _r(e_local)},
        "annual": {
            "q_src_mwh": round(Qs, 1), "q_del_mwh": round(Qd, 1), "w_hp_mwh": round(W, 1),
            "product_qty": round(qty, 1), "product_unit": unit, "direct_hx_hours": direct_hours,
            "mean_cop": _r(mean_cop), "orc_mean_eta": _r(mean_eta), "net_abated_tco2": round(net_abated, 1),
            "value_usd": round(value), "carbon_rev_usd": round(carbon_rev), "revenue_usd": round(value + carbon_rev),
            "hp_elec_cost_usd": round(hp_cost), "om_usd": round(C["opex_frac"] * capex),
            "capex_usd": round(capex), "capex_plant_usd": round(capex_plant), "capex_pipe_usd": round(capex_pipe),
            "capex_hp_usd": round(capex_hp), "net_annual_usd": round(net_annual), "payback_yr": _r(payback),
            "utilisation": round(util, 4), "cap_fraction": round(cap, 4), "peak_del_mw": round(float(qdel.max()), 3),
        },
    }


def evaluate(site: dict, t_amb: np.ndarray, costs: dict | None = None) -> dict:
    """Run all 13 pathways for one site. `site` holds the 31 inputs (heat basis prices, see module
    doc) plus optional baseline_evaporative and p_dac_credit_usd_ton; `t_amb` is 8760 hourly C.
    `costs` replaces the DSX planning costs: {option_key: {capex_usd_kw | capex_usd_kwe | pipe_usd_m},
    "hp_capex_usd_kw": value} (see api_model.COSTS for the sourced values)."""
    tamb = np.asarray(t_amb, dtype=float)
    if tamb.shape != (HOURS,):
        raise ValueError(f"need {HOURS} hourly temperatures, got {tamb.shape}")
    s = dict(site)
    s["q_dc_mw"] = max(float(s["q_dc_mw"]), 1e-6)  # caps divide by the heat source
    if s.get("mit_tier") not in C["mit_mult"]:
        s["mit_tier"] = "med"
    for k in ("is_greenfield", "has_existing_dh", "ind_zoning"):
        s[k] = int(bool(int(float(s[k]))))
    tdc = coolant(s, tamb)
    h = climate_stats(tamb, tdc)
    costs = costs or {}
    opts = [{**o, **costs.get(o["key"], {})} for o in OPTIONS]
    res = [evaluate_option(o, s, tamb, tdc, h, costs.get("hp_capex_usd_kw")) for o in opts]
    res.sort(key=lambda x: (-x["viability"], -x["eco_score"], x["id"]))
    for i, x in enumerate(res):
        x["rank"] = i + 1
    return {"version": VERSION, "climate_summary": h, "options": res}
