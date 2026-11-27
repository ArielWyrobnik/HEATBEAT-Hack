"""Heat cascade: use as much server heat as possible, hottest user first (heat waste perspective).

The cooling perspective asks which heat rejection saves the most money. This module asks the other
question: how much of the heat can be put to use, and how much water does that save? A heat use loop
runs through several users in series, hottest requirement first, for example

    50 C -> greenhouse 50->48 C -> fish farm 48->46 C -> homes 46->45 C -> back to the servers at 45 C

The users sit on the hottest DC loop itself, in series: the loop leaves the servers at its return
temperature (Vera Rubin DLC: 45 C in, about 55 C at the chip outlet, NVIDIA 2026; facility loop 50 C in
cooling_profiles.csv), passes the users, and only has to come back to its supply temperature (45 C).
A user whose supply temperature is above the loop temperature minus the approach gets a heat pump that
draws its evaporator heat from the loop; every other user takes heat through a plain heat exchanger.
All DC heat that goes this way is not cooled away: the existing heat rejection trims only the rest and
needs less fan power and less water (that saving is the point of this view).

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
from .site import Loop


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
    loss_mw: float = 0.0        # connection line heat loss (drawn from the loop, not delivered)
    pump_mw: float = 0.0        # connection line pump power at design flow


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
                            dem + pp["loss_mw"], p_heat, pp["capex_usd"], gas_ef,
                            loss_mw=pp["loss_mw"], pump_mw=pp["pump_design_mw"]))
    # 3. warm water fish farm (RAS)
    vol = P["aq_prod_t_yr"] * P["aq_m3_per_t_yr"]
    makeup = vol * P["aq_exchange_share"] * 1000 / 86400 * P["cp_water_kj_kgk"] * (P["aq_tank_c"] - P["aq_ground_c"]) / 1000
    hall = vol * P["aq_building_w_m3k"] * np.clip(P["aq_tank_c"] - site.t_db, 0, None) / 1e6
    dem = makeup + hall
    pp = pipe(host, float(dem.max()), P["aq_supply_c"], P["aq_return_c"], tg, P)
    out.append(User("fish", "Fish farm", f"{P['aq_prod_t_yr']:,.0f} t fish/yr", P["aq_supply_c"], P["aq_return_c"],
                    dem + pp["loss_mw"], p_heat, pp["capex_usd"], gas_ef,
                    loss_mw=pp["loss_mw"], pump_mw=pp["pump_design_mw"]))
    # 4. ambient (5th generation) network to nearby buildings
    if site.x["d_dh_m"] <= P["dh_max_transmission_km"] * 1000:
        from .district_heating import demand_profile
        # three network sizes: a neighbourhood, the default town network, and the upper end of dh_network_km
        for km in sorted({P["amb_network_km"], P["dh_network_km"], 3 * P["dh_network_km"]}):
            dem = demand_profile(site, P, km) * P["amb_source_share"]
            if dem.sum() <= 0:
                continue
            line = pipe(max(site.x["d_dh_m"], 300.0), float(dem.max()), P["amb_supply_c"], P["amb_return_c"], tg, P)
            net = P["capex_dist_network_usd_m"] * km * 1000 * P["capex_factor"]
            homes = dem.sum() / P["amb_source_share"] / P["casc_home_mwh_yr"]
            out.append(User("ambient", "Heat network (homes)", f"{km:,.0f} km, about {homes:,.0f} homes",
                            P["amb_supply_c"], P["amb_return_c"], dem, p_heat * P["amb_value_share"],
                            line["capex_usd"] + net, gas_ef, loss_mw=line["loss_mw"], pump_mw=line["pump_design_mw"]))
    return out


def run(site, P: dict, chosen: list[User], base: dict) -> dict:
    """Hourly cascade for one set of users. Returns stages, totals and value vs the baseline.

    The users sit in series on the hottest DC loop itself: the water leaves the servers at the loop
    return temperature (Vera Rubin DLC about 50 to 55 C), passes the users hottest requirement first,
    and only has to come back down to the loop supply temperature (about 45 C). Whatever the users do
    not take is trimmed by the existing heat rejection. Loop flow C = q_loop / (T_return - T_supply).

    Per hour and user: if the loop is hot enough (T - approach >= user supply) a heat exchanger takes
    q = min(demand, C (T - T_supply)) directly. Otherwise a heat pump lifts it: its evaporator draws
    q (1 - 1/COP) from the loop, COP from heat_pump.cop at the loop temperature. The loop leaves each
    user at T - drawn / C, never below the loop supply temperature.
    """
    from . import heat_pump as hp
    app = P["hx_approach_k"]
    order = sorted(chosen, key=lambda u: -u.t_supply)
    src = max((l for l in site.loops if l.name == "liquid"), key=lambda l: l.t_return_c)
    t_ret, t_sup = float(src.t_return_c), float(src.t_supply_c)
    c = float(src.q_mw) / max(t_ret - t_sup, 1.0)   # MW per K of the DC loop
    t = np.full(H, t_ret)
    got, drawn_by, t_path, hp_by = {}, {}, {}, {}
    direct = np.zeros(H)
    boost = np.zeros(H)
    hp_work = np.zeros(H)
    for u in order:
        avail = c * np.clip(t - t_sup, 0, None)                 # heat still in the loop above its supply temp
        ok = t - app >= u.t_supply                               # direct heat exchanger is enough
        cop = np.where(ok, np.inf, hp.cop(t, u.t_supply, P))
        frac = np.where(ok, 1.0, 1.0 - 1.0 / cop)               # loop heat per MWh delivered
        q = np.minimum(u.demand, avail / np.maximum(frac, 1e-6))
        draw = q * frac
        got[u.key], drawn_by[u.key] = q, draw
        direct += np.where(ok, q, 0.0)
        b_u = np.where(ok, 0.0, q)
        boost += b_u
        hp_work += b_u - np.where(ok, 0.0, draw)
        hp_by[u.key] = (b_u, b_u - np.where(ok, 0.0, draw))   # (delivered by heat pump, its electricity)
        t_path[u.key] = (t.copy(), t - draw / c)
        t = t - draw / c
    t_after = t
    # temperatures shown per user: the design hour (largest total delivery), so the chain is continuous
    # temperatures shown per user: the yearly mean temperature drop each user causes (mean heat drawn / C),
    # in series from the loop return, so every user that takes heat shows a real drop
    t_design, t_d = {}, t_ret
    for u in order:
        drop = float(np.mean(drawn_by[u.key])) / c
        t_design[u.key] = (t_d, t_d - drop)
        t_d -= drop
    t_after_mean = t_d
    cop_all = float(boost.sum() / hp_work.sum()) if hp_work.sum() > 0 else None
    rem = {l.name: np.full(H, float(l.q_mw)) for l in site.loops}
    rem[src.name] = rem[src.name] - sum(drawn_by.values())
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
    elec += sum(u.pump_mw * float(got[u.key].sum()) / float(u.demand.max())
                for u in order if u.pump_mw > 0 and float(u.demand.max()) > 0)
    line_loss, line_pump = 0.0, 0.0
    for u in order:
        drawn = got[u.key]
        if float(drawn.sum()) <= 0:
            continue
        # connection lines: the loss is drawn from the loop but never reaches the host; pumps run with the flow
        line_loss += float(np.minimum(drawn, u.loss_mw).sum())
        peak_u = float(u.demand.max())
        line_pump += u.pump_mw * float(drawn.sum()) / peak_u if peak_u > 0 else 0.0
        e = float(np.clip(drawn - u.loss_mw, 0, None).sum())
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
                       "demand_mwh_yr": float(u.demand.sum()), "value_usd_yr": rev, "capex_usd": cap,
                       "heat_pump_mwh_yr": float(hp_by[u.key][0].sum()), "t_user_c": u.t_supply,
                       "heat_pump_cop": (float(hp_by[u.key][0].sum() / hp_by[u.key][1].sum())
                                         if hp_by[u.key][1].sum() > 0 else None)})
    capex += P["capex_hp_usd_kw"] * float(boost.max()) * 1000 * P["capex_factor"]
    p_w = x["p_water_usd_m3"] + x["wsi"] * P["water_scarcity_usd_m3_per_wsi"]
    d_elec = base["cooling_mwh"] - elec
    d_water = base["water_m3"] - water
    net = revenue + d_elec * x["p_elec_usd_mwh"] + d_water * p_w - P["opex_share"] * capex
    co2 += d_elec * x["ci_grid_kg_mwh"] / 1000
    used -= line_loss  # lost to the ground on the way, not used
    tot_del = sum(s_["mwh_yr"] for s_ in stages)
    for s_ in stages:  # share of server heat behind each user (heat pump work counted pro rata)
        s_["share"] = used * s_["mwh_yr"] / tot_del / total_heat if tot_del > 0 else 0.0
    # heat budget per DC loop for the "Where the server heat goes" diagram
    rej_label = {"dry": "Dry cooler", "adiabatic": "Adiabatic cooler", "tower": "Cooling tower"}.get(tech, tech)
    heat_loops = []
    for l in site.loops:
        routes = []
        if l is src:
            routes = [{"name": u.label, "mwh_yr": float(drawn_by[u.key].sum()), "kind": "reuse"}
                      for u in order if float(drawn_by[u.key].sum()) > 0]
        routes.append({"name": rej_label, "mwh_yr": float(rem[l.name].sum()), "kind": "cooling"})
        heat_loops.append({"name": l.name, "mwh_yr": float(l.q_mw) * H, "return_c": float(l.t_return_c), "routes": routes})
    return {"stages": stages, "heat_used_mwh_yr": used, "heat_loops": heat_loops, "heat_used_share": used / total_heat,
            "heat_rejected_mwh_yr": total_heat - used, "line_loss_mwh_yr": line_loss,
            "line_pump_mwh_yr": line_pump, "water_saved_m3_yr": d_water, "electricity_saved_mwh_yr": d_elec,
            "co2_avoided_t_yr": co2, "capex_usd": capex, "net_value_usd_yr": net, "npv_usd": net / annuity(P) - capex,
            "rejection": tech, "t_top_c": t_ret, "t_back_c": t_sup, "t_after_users_c": t_after_mean,
            "direct_mwh_yr": float(direct.sum()), "heat_pump_mwh_yr": float(boost.sum()),
            "heat_pump_cop": cop_all, "heat_pump_elec_mwh_yr": float(hp_work.sum()),
            "loops": [{"name": l.name, "t_return_c": l.t_return_c, "t_supply_c": l.t_supply_c, "mwh_yr": l.q_mw * H}
                      for l in site.loops]}


def designs(site, P: dict, base: dict, n: int = 2) -> list[dict]:
    """The top cascades: most heat used, then most heat used among cascades that pay off (NPV > 0).

    Every subset of the feasible users is simulated; the list is short (at most 4 users, 15 subsets).
    """
    # heat reuse only straight from the GPU liquid loop (never from chilled water, air or rear door loops).
    # A site without one is shown as a direct liquid cooling retrofit: a new GPU loop takes
    # casc_retrofit_share of the IT heat at casc_retrofit_sup_c / _ret_c, the old loops keep the rest, and the
    # retrofit CAPEX is charged to the cascade. The baseline stays today's setup, so the cascade also gets
    # credit for the chiller and tower load the retrofit removes.
    retrofit_capex = 0.0
    if not any(l.name == "liquid" and l.t_return_c >= P["casc_min_source_c"] for l in site.loops):
        import copy
        import dataclasses
        share = P["casc_retrofit_share"]
        site = copy.copy(site)
        old_loops = site.loops
        site.loops = [Loop("liquid", site.it_mw * share, P["casc_retrofit_sup_c"], P["casc_retrofit_ret_c"])]
        site.loops += [dataclasses.replace(l, name=l.name if l.name == "air" else "facility", q_mw=l.q_mw * (1 - share))
                       for l in old_loops]
        retrofit_capex = P["casc_retrofit_capex_usd_kw"] * site.it_mw * share * 1000 * P["capex_factor"]
    us = users(site, P)
    runs = []
    for k in range(1, len(us) + 1):
        for combo in itertools.combinations(us, k):
            if len({u.key for u in combo}) < len(combo):  # one size per user type
                continue
            r = run(site, P, list(combo), base)
            if retrofit_capex:
                r["capex_usd"] += retrofit_capex
                r["npv_usd"] -= retrofit_capex
                r["retrofit_capex_usd"] = retrofit_capex
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
