"""Heat cascade: use as much server heat as possible, hottest user first (heat waste perspective).

The cooling perspective asks which heat rejection saves the most money. This module asks the other
question: how much of the heat can be put to use, and how much water does that save? A heat use loop
runs through several users in series, hottest requirement first, for example

    45 C -> digester heating 45->41 C -> greenhouse 41->35 C -> fish farm 35->32 C -> back to the DC

Per hour: use loop flow C2 (MW/K) = peak demand / (T_top - T_low). Each user takes
q = min(demand, C2 (T - T_floor)), T_floor = its return temperature + approach, and the water leaves at
T - q / C2. The returning water is reheated to T_top directly from the DC loops where they are hot
enough, and by a booster heat pump otherwise. All DC heat that goes this way is not cooled away: the
existing heat rejection needs less fan power and less water (that saving is the point of this view).

Users (all hourly, sized large on purpose, every size an assumption flagged in params.py):
  biogas      digester heating of the sized biogas plant (biogas.py), heating water 45/35 C
  greenhouse  glass greenhouse at 18 C, U = 4 W/m2K, area = min(50 ha, half the nearby flat land), 40/30 C
  fish        warm water RAS fish farm (28 C tanks): make up water from 12 C plus hall losses, 33/29 C
  ambient     5th generation heat network to nearby buildings at 20/10 C, building heat pumps do the rest

Value: heat sold at the displaced gas heat cost (biogas: freed biogas as RNG, see biogas.py), plus
the cooling electricity and water the heat rejection no longer needs. CAPEX: heat exchangers, pipes
to the hosts, the ambient network and the biogas upgrading. The host businesses themselves
(greenhouse, fish farm, digester) are NOT in the CAPEX: they are separate businesses that buy the heat.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from . import biogas
from .heat_rejection import reject
from .sinks import H, annuity, pipe


@dataclass
class User:
    key: str
    label: str
    size: str
    t_supply: float
    t_return: float
    demand: np.ndarray          # MW per hour
    value_usd_mwh: float        # what a MWh of delivered heat is worth to the host
    capex_fixed: float          # pipes / network, USD
    co2_t_mwh: float            # avoided CO2 per MWh delivered
    settle: object = None       # biogas: use the biogas plan for value and CAPEX


def users(site, P: dict) -> list[User]:
    out = []
    gas_ef = P["ng_kg_co2_per_mwh_fuel"] / 0.9 / 1000
    p_heat = site.x["p_heat_usd_mwh"]
    tg = float(np.clip(site.t_mean, 5, 20))
    host = P["casc_host_pipe_m"]
    # 1. biogas (sized plant from biogas.py, mesophilic, heating water 45/35 C)
    bp = biogas.plan(site, P, "meso")
    if bp.ko is None:
        out.append(User("biogas", "Biogas digester", bp.label.split(", ", 1)[-1], bp.t_req_c, bp.t_req_c - 10,
                        np.asarray(bp.demand_mw, float), 0.0, 0.0, 0.0, settle=bp.settle))
    # 2. greenhouse
    area = min(P["gh_max_ha"] * 1e4, P["gh_land_share"] * float(site.x.get("flat_land_m2") or 0))
    if area >= 1e4:
        dem = area * P["gh_u_w_m2k"] * np.clip(P["gh_t_set_c"] - site.t_db, 0, None) / 1e6
        if dem.sum() > 0:
            pp = pipe(host, float(dem.max()), P["gh_supply_c"], P["gh_return_c"], tg, P)
            out.append(User("greenhouse", "Greenhouse", f"{area / 1e4:,.0f} ha", P["gh_supply_c"], P["gh_return_c"],
                            dem, p_heat, pp["capex_usd"], gas_ef))
    # 3. warm water fish farm (RAS)
    vol = P["aq_prod_t_yr"] * P["aq_m3_per_t_yr"]
    makeup = vol * P["aq_exchange_share"] * 1000 / 86400 * P["cp_water_kj_kgk"] * (P["aq_tank_c"] - P["aq_ground_c"]) / 1000
    hall = vol * P["aq_building_w_m3k"] * np.clip(P["aq_tank_c"] - site.t_db, 0, None) / 1e6
    dem = makeup + hall
    pp = pipe(host, float(dem.max()), P["aq_supply_c"], P["aq_return_c"], tg, P)
    out.append(User("fish", "Fish farm", f"{P['aq_prod_t_yr']:,.0f} t fish/yr", P["aq_supply_c"], P["aq_return_c"],
                    dem, p_heat, pp["capex_usd"], gas_ef))
    # 4. ambient (5th generation) network to nearby buildings
    if site.x["d_dh_m"] <= P["dh_max_transmission_km"] * 1000:
        from .district_heating import demand_profile
        dem = demand_profile(site, P, P["amb_network_km"]) * P["amb_source_share"]
        if dem.sum() > 0:
            line = pipe(max(site.x["d_dh_m"], 300.0), float(dem.max()), P["amb_supply_c"], P["amb_return_c"], tg, P)
            net = P["capex_dist_network_usd_m"] * P["amb_network_km"] * 1000 * P["capex_factor"]
            out.append(User("ambient", "Heat network (buildings)", f"{P['amb_network_km']:,.0f} km",
                            P["amb_supply_c"], P["amb_return_c"], dem, p_heat * P["amb_value_share"],
                            line["capex_usd"] + net, gas_ef))
    return out


def run(site, P: dict, chosen: list[User], base: dict) -> dict:
    """Hourly cascade for one set of users. Returns stages, totals and value vs the baseline.

    A heat use loop runs from T_top (hottest user supply) through the users in series, hottest first,
    and comes back at T_r. It is reheated to T_top first directly from the DC loops (hottest loop first,
    up to the loop return minus the approach), and a booster heat pump lifts the rest from the DC loop
    (COP from heat_pump.cop). Flow of the use loop C2 = peak demand / (T_top - T_low).
    """
    from . import heat_pump as hp
    app = P["hx_approach_k"]
    order = sorted(chosen, key=lambda u: -u.t_supply)
    t_top = order[0].t_supply
    t_low = min(u.t_return for u in order) + app
    peak = float(np.max(sum(u.demand for u in order)))
    c2 = peak / max(t_top - t_low, 1.0)
    t = np.full(H, t_top)
    got = {}
    for u in order:
        floor = max(u.t_return + app, t_low)
        q = np.minimum(u.demand, c2 * np.clip(t - floor, 0, None))
        t_out = t - q / c2
        got[u.key] = q
        t = t_out
    t_back = t
    # temperatures shown per user: the design hour (largest total delivery), so the chain is continuous
    h_d = int(np.argmax(sum(got.values())))
    t_d = t_top
    t_design = {}
    for u in order:
        t_design[u.key] = (t_d, t_d - float(got[u.key][h_d]) / c2)
        t_d = t_design[u.key][1]
    # reheat: direct from the DC loops, then booster heat pump
    rem = {l.name: np.full(H, float(l.q_mw)) for l in site.loops}
    cur = t_back.copy()
    direct = np.zeros(H)
    for l in sorted(site.loops, key=lambda l: -l.t_return_c):
        reach = min(t_top, l.t_return_c - app)
        q = np.minimum(rem[l.name], c2 * np.clip(reach - cur, 0, None))
        rem[l.name] -= q
        direct += q
        cur = cur + q / c2
    boost = c2 * np.clip(t_top - cur, 0, None)
    hot = max(site.loops, key=lambda l: l.t_return_c)
    cop = float(hp.cop(hot.t_return_c, t_top, P)) if boost.sum() > 0 else None
    hp_work = boost / cop if cop else np.zeros(H)
    evap = boost - hp_work
    for l in sorted(site.loops, key=lambda l: -l.t_return_c):
        q = np.minimum(rem[l.name], evap)
        rem[l.name] -= q
        evap = evap - q
    # heat rejection of what is left, same technology as today
    tech = site.baseline_rejection
    rej = [reject(tech, rem[l.name], l.t_supply_c, l.t_return_c, site.t_db, site.t_wb, P, q_design_mw=l.q_mw)
           for l in site.loops]
    elec = sum(r["fan_mwh"] + r["pump_mwh"] + r["chiller_mwh"] for r in rej) + float(hp_work.sum())
    water = sum(r["water_m3"] for r in rej)
    total_heat = sum(l.q_mw for l in site.loops) * H
    used = total_heat - sum(float(v.sum()) for v in rem.values())  # server heat that is not cooled away
    x = site.x
    stages, revenue, capex, co2 = [], 0.0, 0.0, 0.0
    delivered = sum(float(v.sum()) for v in got.values())
    for u in order:
        e = float(got[u.key].sum())
        if e <= 0:
            continue
        if u.settle is not None:
            st = u.settle(got[u.key])
            rev, cap, c_av = st["revenue_usd"], st["capex_usd"], st["co2_avoided_t"]
        else:
            rev, cap, c_av = e * u.value_usd_mwh, u.capex_fixed, e * u.co2_t_mwh
        cap += P["capex_hx_usd_kw"] * float(got[u.key].max()) * 1000 * P["capex_factor"]
        revenue, capex, co2 = revenue + rev, capex + cap, co2 + c_av
        stages.append({"key": u.key, "label": u.label, "size": u.size, "mwh_yr": e,
                       "share": used * e / delivered / total_heat,  # share of server heat behind this user
                       "t_in_c": t_design[u.key][0], "t_out_c": t_design[u.key][1], "peak_mw": float(got[u.key].max()),
                       "demand_mwh_yr": float(u.demand.sum()), "value_usd_yr": rev, "capex_usd": cap})
    capex += P["capex_hx_usd_kw"] * float(direct.max()) * 1000 * P["capex_factor"]
    capex += P["capex_hp_usd_kw"] * float(boost.max()) * 1000 * P["capex_factor"]
    p_w = x["p_water_usd_m3"] + x["wsi"] * P["water_scarcity_usd_m3_per_wsi"]
    d_elec = base["cooling_mwh"] - elec
    d_water = base["water_m3"] - water
    net = revenue + d_elec * x["p_elec_usd_mwh"] + d_water * p_w - P["opex_share"] * capex
    co2 += d_elec * x["ci_grid_kg_mwh"] / 1000
    return {"stages": stages, "heat_used_mwh_yr": used, "heat_used_share": used / total_heat,
            "heat_rejected_mwh_yr": total_heat - used, "water_saved_m3_yr": d_water, "electricity_saved_mwh_yr": d_elec,
            "co2_avoided_t_yr": co2, "capex_usd": capex, "net_value_usd_yr": net, "npv_usd": net / annuity(P) - capex,
            "rejection": tech, "t_top_c": t_top, "t_back_c": float(t_back[h_d]),
            "direct_mwh_yr": float(direct.sum()), "heat_pump_mwh_yr": float(boost.sum()),
            "heat_pump_cop": cop, "heat_pump_elec_mwh_yr": float(hp_work.sum()),
            "loops": [{"name": l.name, "t_return_c": l.t_return_c, "t_supply_c": l.t_supply_c, "mwh_yr": l.q_mw * H}
                      for l in site.loops]}


def designs(site, P: dict, base: dict, n: int = 2) -> list[dict]:
    """The top cascades: most heat used, then most heat used among cascades that pay off (NPV > 0).

    Every subset of the feasible users is simulated; the list is short (at most 4 users, 15 subsets).
    """
    us = users(site, P)
    runs = []
    for k in range(1, len(us) + 1):
        for combo in itertools.combinations(us, k):
            r = run(site, P, list(combo), base)
            if r["heat_used_mwh_yr"] > 0:
                r["users"] = [u.key for u in combo]
                runs.append(r)
    if not runs:
        return []
    by_heat = sorted(runs, key=lambda r: (-r["heat_used_mwh_yr"], -r["npv_usd"]))
    out = [{**by_heat[0], "title": "Most heat used"}]
    pays = [r for r in by_heat if r["npv_usd"] > 0 and r is not by_heat[0]]
    if by_heat[0]["npv_usd"] > 0:
        out[0]["title"] = "Most heat used, pays off"
    if pays:
        out.append({**pays[0], "title": "Most heat used that pays off"})
    elif len(by_heat) > 1:
        out.append({**max(by_heat[1:], key=lambda r: r["npv_usd"]), "title": "Lowest cost alternative"})
    return out[:n]
