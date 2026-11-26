"""Heat chain simulator and optimizer.

A chain = one heat rejection technology + up to two heat uses (+ optional storage for district
heating), e.g. "dry cooler + heat pump + district heating 20 km + ATES". For every hour of the year:

1. Heat sources are the site's cooling loops (liquid loop 42 to 55 C, air side loop 13 to 35 C),
   hottest first.
2. Each heat use takes heat from the hottest loop that can serve it: directly through a heat
   exchanger when hot enough, else through a heat pump (COP from `heat_pump.cop`). Uses with a
   fixed demand go first; uses that take whatever is left (desalination, ORC) go last.
3. Adsorption chilling is special: it is driven by the liquid loop and replaces trim chiller load
   of the air loop, and its recooler rejects drive heat + cold through the same technology.
4. Storage shifts heat-pump output from hours with spare source heat into hours with unmet district
   heating demand (daily tank, or seasonal ATES/BTES).
5. Whatever heat is left in each loop goes to the heat rejection plant (`heat_rejection.reject`),
   which is always sized for the full loop load (it is the backup when the heat user is off).

The energy balance is closed every run: IT heat + heat pump work + chiller work = heat rejected +
heat delivered + pipe and storage losses + adsorption recooling. `balance_residual_mwh` must be ~0.

The baseline (counterfactual without reuse) is the same simulator with the site's existing heat
rejection technology and no heat uses. Every chain is reported as a difference to it.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from . import biogas, district_heating as dh, heat_pump as hp, industry
from .heat_rejection import TECHS, capex_usd as rej_capex, reject, wind_panel_capex_usd
from .params import defaults
from .sinks import H, SinkPlan, annuity

TECH_LABEL = {"dry": "Dry cooler", "adiabatic": "Adiabatic cooler", "tower": "Cooling tower",
              "wind": "Wind radiator (passive) + dry cooler backup"}
DH_NETWORK_KM = (5.0, 20.0, 60.0)
DH_PEAK_SHARES = (35, 65)
DH_FULL_PLANS = tuple(f"dh_{km:.0f}km" for km in DH_NETWORK_KM)
DH_SIZED_PLANS = {f"dh_{km:.0f}km_peak{share}": (km, share)
                  for km in DH_NETWORK_KM for share in DH_PEAK_SHARES}
STORAGE_KINDS = ("tank", "ates", "btes")


# ---- plans -------------------------------------------------------------------------------------

def build_plans(site, P: dict) -> dict[str, SinkPlan]:
    t_hot = max(l.t_return_c for l in site.loops)
    plans = {
        "biogas_meso": biogas.plan(site, P, "meso"),
        "biogas_thermo": biogas.plan(site, P, "thermo"),
        "feedwater": industry.feedwater_plan(site, P),
        "desal_med": industry.desal_plan(site, P, "med", t_hot),
        "desal_md": industry.desal_plan(site, P, "md", t_hot),
        "orc": industry.orc_plan(site, P, t_hot),
        "adsorption": _adsorption_plan(site, P),
    }
    for km in DH_NETWORK_KM:
        plans[f"dh_{km:.0f}km"] = dh.plan(site, P, km)
    for key, (km, share) in DH_SIZED_PLANS.items():
        plans[key] = dh.plan(site, P, km, peak_share=share)
    return plans


def _adsorption_plan(site, P: dict) -> SinkPlan:
    label = "Adsorption chiller (liquid loop heat cools the air side)"
    liq = [l for l in site.loops if l.name == "liquid"]
    air = [l for l in site.loops if l.name == "air"]
    if not liq or not air:
        return SinkPlan("adsorption", label, 0, np.zeros(H), ko="needs both a liquid loop (drive) and an air side load", kind="cold")
    t_drive = liq[0].t_return_c - P["hx_approach_k"]
    if t_drive < P["ads_min_drive_c"]:
        # LiBr would need a heat pump: effective electric COP = Q_cold / W_hp = abs_cop * COP_hp
        c_hp = float(hp.cop(liq[0].t_return_c, P["abs_min_drive_c"], P))
        return SinkPlan("adsorption", label, 0, np.zeros(H), kind="cold",
                        ko=f"liquid loop {liq[0].t_return_c:.0f} C < {P['ads_min_drive_c'] + P['hx_approach_k']:.0f} C drive; "
                           f"LiBr via heat pump would give only {P['abs_cop'] * c_hp:.1f} kW cold per kW_e, an electric chiller is better")
    return SinkPlan("adsorption", label, t_drive, None, kind="cold", direct_only=True)


GROUPS = {
    "biogas": ("biogas_meso", "biogas_thermo"),
    "feedwater": ("feedwater",),
    "adsorption": ("adsorption",),
    "dh": (*DH_FULL_PLANS, *DH_SIZED_PLANS),
    "desal": ("desal_med", "desal_md"),
    "orc": ("orc",),
}
ORDER = ["adsorption", "biogas", "feedwater", "dh", "desal", "orc"]  # fixed demands first, take-all last


def site_techs(site) -> tuple:
    """Heat rejection technologies a site can use: the wind radiator needs hourly wind data."""
    return tuple(t for t in TECHS if t != "wind" or getattr(site, "wind", None) is not None)


def enumerate_chains(plans: dict[str, SinkPlan], max_uses: int = 2, techs: tuple = TECHS):
    """All feasible (tech, uses, storage) combinations. KO uses are left out."""
    ok = {g: [n for n in names if n in plans and plans[n].ko is None] for g, names in GROUPS.items()}
    groups = [g for g in ORDER if ok[g]]
    combos = [()]
    for k in range(1, max_uses + 1):
        for gs in itertools.combinations(groups, k):
            if sum(g in ("desal", "orc") for g in gs) > 1:
                continue  # two take-all uses never share the same heat
            combos += list(itertools.product(*[ok[g] for g in gs]))
    out = []
    for tech in techs:
        for uses in combos:
            stores = [None]
            if any(u in DH_FULL_PLANS for u in uses):
                stores += list(STORAGE_KINDS)
            for st in stores:
                out.append((tech, tuple(uses), st))
    return out


# ---- simulation --------------------------------------------------------------------------------

def simulate(site, P: dict, tech: str, uses: tuple = (), storage: str | None = None,
             plans: dict | None = None, baseline: dict | None = None) -> dict:
    plans = plans or build_plans(site, P)
    loops = sorted(site.loops, key=lambda l: -l.t_return_c)
    rem = {l.name: np.full(H, float(l.q_mw)) for l in loops}
    heat_to_uses = {l.name: {} for l in loops}
    e_it = site.it_mw * H
    res = {"tech": tech, "uses": uses, "storage": storage, "ko": None}
    wind = getattr(site, "wind", None)
    if tech == "wind" and wind is None:
        res["ko"] = "wind radiator: no hourly wind data for this site"
        return res
    hp_work = np.zeros(H)
    hp_out_peak = 0.0
    hp_cops = []
    delivered, losses, aux = {}, {}, {}
    hx_peak = 0.0
    capex = {}
    ads_rej = None
    air_offload = np.zeros(H)
    useful_dh = None
    flows = []  # (source, target, MWh/yr, kind) for the energy balance / Sankey

    def flow(a, b, e, kind="heat"):
        if e > 1e-6:
            flows.append({"source": a, "target": b, "mwh_yr": float(e), "kind": kind})

    for u in uses:
        pl = plans[u]
        if pl.ko:
            res["ko"] = f"{u}: {pl.ko}"
            return res
        if pl.kind == "cold":  # adsorption chiller
            liq = loops[0]
            air = [l for l in loops if l.name == "air"][0]
            pre = reject(tech, rem["air"], air.t_supply_c, air.t_return_c, site.t_db, site.t_wb, P, q_design_mw=air.q_mw, wind_ms=wind)
            rec_ok = reject(tech, 1.0, 27.0, P["ads_max_cond_c"], site.t_db, site.t_wb, P, wind_ms=wind)["t_leave_c"] <= P["ads_max_cond_c"] - 3
            cold = np.where(rec_ok, np.minimum(pre["chiller_load_full_mw"], P["ads_cop"] * rem[liq.name]), 0.0)
            drive = cold / P["ads_cop"]
            rem[liq.name] = rem[liq.name] - drive
            heat_to_uses[liq.name][u] = float(drive.sum())
            flow(f"{liq.name} loop", "adsorption chiller", float(drive.sum()))
            flow("air loop", "adsorption chiller", float(cold.sum()), "cooling")
            flow("adsorption chiller", "adsorber recooler", float((cold + drive).sum()))
            air_offload = cold
            ads_rej = reject(tech, cold + drive, 27.0, P["ads_max_cond_c"], site.t_db, site.t_wb, P, wind_ms=wind)
            capex["adsorption"] = P["capex_ads_usd_kw"] * float(cold.max()) * 1000 * P["capex_factor"] + \
                rej_capex(tech, float((cold + drive).max()), P)
            delivered[u] = cold
            losses[u] = np.zeros(H)
            res.setdefault("details", {})[u] = {"cold_mwh": round(float(cold.sum())), "drive_mwh": round(float(drive.sum())),
                                                 "hours_running": int((cold > 0).sum()),
                                                 "chiller_load_air_mwh": round(float(pre["chiller_load_full_mw"].sum()))}
            continue
        need = None if pl.demand_mw is None else pl.demand_mw + np.broadcast_to(pl.loss_mw, (H,))
        got = np.zeros(H)
        for l in loops:
            direct = not hp.needs_hp(l.t_return_c, pl.t_req_c, P)
            if pl.direct_only and not direct:
                continue
            c = None if direct else float(hp.cop(l.t_return_c, pl.t_req_c, P))
            frac = 1.0 if direct else (1 - 1 / c)  # source heat per unit delivered
            if need is None:
                take = rem[l.name].copy()
            else:
                take = np.minimum(rem[l.name], np.clip(need - got, 0, None) * frac)
            taken = float(take.sum())
            if taken <= 0:
                continue
            out = take / frac
            rem[l.name] = rem[l.name] - take
            heat_to_uses[l.name][u] = taken
            node = "heat exchanger" if direct else f"heat pump ({u})"
            flow(f"{l.name} loop", node, taken)
            if not direct:
                flow("grid electricity", node, float((out / c).sum()), "electricity")
            flow(node, pl.label, float(out.sum()))
            got = got + out
            if direct:
                hx_peak += float(out.max())
            else:
                w = out / c
                hp_work += w
                hp_out_peak += float(out.max())
                hp_cops.append((c, float(out.sum())))
        if need is None:
            useful, loss = got, np.zeros(H)
        else:
            dem = pl.demand_mw
            tot = np.maximum(need, 1e-12)
            useful, loss = got * dem / tot, got * (need - dem) / tot
        delivered[u], losses[u] = useful, loss
        if u == "orc":
            useful, loss = got, np.zeros(H)
            delivered[u], losses[u] = useful, loss
        if pl.demand_mw is not None and np.max(pl.demand_mw) > 0 and u != "orc":
            aux[u] = np.broadcast_to(pl.aux_mw, (H,)) * np.clip(useful / np.maximum(pl.demand_mw, 1e-12), 0, 1)
        if u.startswith("dh_"):
            useful_dh = u

    # storage: heat pump output in hours with spare source heat -> hours with unmet DH demand
    store_loss = np.zeros(H)
    if storage:
        if not useful_dh:
            res["ko"] = "storage without district heating"
            return res
        ko = dh.storage_ko(storage, site, P)
        if ko:
            res["ko"] = f"{storage}: {ko}"
            return res
        pl = plans[useful_dh]
        deficit = np.clip(pl.demand_mw - delivered[useful_dh], 0, None)
        l = loops[0]
        direct = not hp.needs_hp(l.t_return_c, pl.t_req_c, P)
        c = None if direct else float(hp.cop(l.t_return_c, pl.t_req_c, P))
        frac = 1.0 if direct else 1 - 1 / c
        cap_out = max(hp_out_peak if not direct else hx_peak, 1e-9)
        cur_out = delivered[useful_dh] + losses[useful_dh]
        spare_out = np.clip(np.minimum(rem[l.name] / frac, cap_out - cur_out), 0, None)
        take_out, give, cap_mwh, cst = dh.apply_storage(storage, spare_out, deficit, P)
        rem[l.name] = rem[l.name] - take_out * frac
        stored_heat = float((take_out * frac).sum())
        heat_to_uses[l.name][useful_dh] = heat_to_uses[l.name].get(useful_dh, 0.0) + stored_heat
        flow(f"{l.name} loop", f"storage ({storage})", stored_heat)
        if not direct:
            flow("grid electricity", f"storage ({storage})", float((take_out / c).sum()), "electricity")
        flow(f"storage ({storage})", pl.label, float(give.sum()))
        flow(f"storage ({storage})", "losses", float((take_out - give).sum()), "loss")
        if not direct:
            hp_work += take_out / c
            hp_cops.append((c, float(take_out.sum())))
        if give.sum() < max(P["storage_min_shift_share"] * float(pl.demand_mw.sum()), 1.0):
            res["ko"] = f"{storage}: no unmet demand to shift (source covers the community all year)"
            return res
        store_loss = take_out - give
        delivered[useful_dh] = delivered[useful_dh] + give
        capex["storage"] = cst
        res.setdefault("details", {})["storage"] = {"kind": storage, "capacity_mwh": round(cap_mwh),
                                                    "shifted_mwh": round(float(give.sum())),
                                                    "loss_mwh": round(float(store_loss.sum()))}

    # heat rejection of what is left (always sized for the full loop load)
    rej = {}
    for l in loops:
        off = air_offload if l.name == "air" else 0.0
        rej[l.name] = reject(tech, rem[l.name], l.t_supply_c, l.t_return_c, site.t_db, site.t_wb, P,
                             q_design_mw=l.q_mw, chiller_offload_mw=off, wind_ms=wind)
    for l in loops:
        flow(f"{l.name} loop", TECH_LABEL[tech], float(rej[l.name]["q_rejected_mwh"] - rej[l.name]["chiller_mwh"]))
        flow("grid electricity", TECH_LABEL[tech] + " (chiller)", rej[l.name]["chiller_mwh"], "electricity")
    for l in loops:
        flow("IT load", f"{l.name} loop", l.q_mw * H)
    # Trace only heat from the servers. The full energy balance also includes electricity,
    # conversion outputs and losses, which must not be added to this source heat budget.
    heat_loops = []
    for l in loops:
        offload = float(air_offload.sum()) if l.name == "air" else 0.0
        routes = [{"name": plans[u].label, "mwh_yr": amount, "kind": "reuse"}
                  for u, amount in heat_to_uses[l.name].items() if amount > 0]
        if offload > 0:
            routes.append({"name": "Adsorption chiller (air-side cooling)", "mwh_yr": offload, "kind": "cooling"})
        remainder = float(rem[l.name].sum()) - offload
        if remainder > 0:
            routes.append({"name": TECH_LABEL[tech], "mwh_yr": remainder, "kind": "cooling"})
        heat_loops.append({"name": l.name, "mwh_yr": l.q_mw * H, "return_c": l.t_return_c, "routes": routes})
    parts = list(rej.values()) + ([ads_rej] if ads_rej else [])
    if tech == "wind":
        pas = sum(r.get("passive_mwh", 0.0) for r in parts)
        res.setdefault("details", {})["wind_radiator"] = {
            "passive_mwh": round(pas), "passive_share": round(pas / max(sum(r["q_rejected_mwh"] for r in parts), 1e-9), 3),
            "face_area_m2": round(sum(r.get("wind_area_m2", 0.0) for r in parts)),
            "hours_fully_passive": int(min((r["passive_mw"] >= np.asarray(r["q_rejected_mw"]) - 1e-9).sum()
                                           for r in parts if "passive_mw" in r))}
    fan = sum(r["fan_mwh"] for r in parts)
    pump = sum(r["pump_mwh"] for r in parts)
    chill = sum(r["chiller_mwh"] for r in parts)
    water = sum(r["water_m3"] for r in parts)
    q_rej = sum(r["q_rejected_mwh"] for r in rej.values())
    cooling = fan + pump + chill
    air_q = sum(l.q_mw for l in loops if l.name == "air") * H
    hall_fans = P["hall_fan_kw_kw"] * air_q  # CRAH / fan wall air movement, same in every chain
    other = P["other_overhead_share"] * e_it + hall_fans
    plant = float(hp_work.sum()) + sum(float(a.sum()) for a in aux.values())

    # value of each use
    rev = co2_av = water_prod = gen = exported = orc_cond = orc_aux = 0.0
    det = res.setdefault("details", {})
    for u in uses:
        pl = plans[u]
        if pl.kind == "cold":
            continue
        s = pl.settle(delivered[u]) if pl.settle else {}
        rev += s.get("revenue_usd", 0.0)
        co2_av += s.get("co2_avoided_t", 0.0)
        water_prod += s.get("water_produced_m3", 0.0)
        gen += s.get("elec_generated_mwh", 0.0)
        exported += s.get("elec_exported_mwh", 0.0)
        orc_cond += s.get("orc_condenser_mwh", 0.0)
        orc_aux += s.get("aux_extra_mwh", 0.0)
        capex[u] = s.get("capex_usd", 0.0)
        flow(pl.label, "losses", float(losses[u].sum()), "loss")
        flow(pl.label, "useful " + ("electricity" if u == "orc" else "heat"), float(delivered[u].sum()) if u != "orc"
             else s.get("elec_generated_mwh", 0.0), "electricity" if u == "orc" else "heat")
        if u == "orc":
            flow(pl.label, "ORC condenser", s.get("orc_condenser_mwh", 0.0))
        det[u] = {"delivered_mwh": round(float(delivered[u].sum())), "losses_mwh": round(float(losses[u].sum())),
                  **s.get("detail", {})}

    # CAPEX: new rejection plant only if it differs from the existing one (or greenfield)
    if tech == "wind" and site.baseline_rejection == "dry" and not site.x.get("is_greenfield"):
        capex["heat_rejection"] = sum(wind_panel_capex_usd(l.q_mw, P) for l in loops)  # dry cooler exists as backup
    elif site.x.get("is_greenfield") or tech != site.baseline_rejection:
        capex["heat_rejection"] = sum(rej_capex(tech, l.q_mw, P) for l in loops)
    capex["heat_pump"] = P["capex_hp_usd_kw"] * hp_out_peak * 1000 * P["capex_factor"]
    capex["heat_exchangers"] = P["capex_hx_usd_kw"] * hx_peak * 1000 * P["capex_factor"]
    capex_total = sum(capex.values())

    x = site.x
    p_w = x["p_water_usd_m3"] + x["wsi"] * P["water_scarcity_usd_m3_per_wsi"]
    elec = cooling + plant
    cost = {
        "electricity_usd": elec * x["p_elec_usd_mwh"],
        "water_usd": water * x["p_water_usd_m3"],
        "water_scarcity_usd": water * x["wsi"] * P["water_scarcity_usd_m3_per_wsi"],
        "carbon_usd": elec * x["ci_grid_kg_mwh"] / 1000 * x["p_co2_usd_t"],
        "opex_usd": P["opex_share"] * capex_total,
        "revenue_usd": -rev,
    }
    net_cost = sum(cost.values())
    # ORC input is not delivered heat: it leaves as electricity (gen) and condenser heat (orc_cond)
    useful_heat = sum(float(delivered[u].sum()) for u in uses if plans[u].kind == "heat" and u != "orc")
    orc_in = float(delivered["orc"].sum()) if "orc" in uses else 0.0
    # ERE counts energy reused outside the data center: delivered heat, but for ORC its electricity
    reused = sum(float(delivered[u].sum()) for u in uses if plans[u].kind == "heat" and u != "orc") + gen
    total_fac = e_it + cooling + other
    co2 = elec * x["ci_grid_kg_mwh"] / 1000 - co2_av

    # energy balance (MWh/yr)
    w_chill = chill
    e_in = e_it + float(hp_work.sum()) + w_chill
    ads_out = ads_rej["q_rejected_mwh"] if ads_rej else 0.0
    e_out = q_rej + useful_heat + orc_in + sum(float(v.sum()) for v in losses.values()) + float(store_loss.sum()) + ads_out
    # adsorption: the cold removed from the air loop leaves through the adsorber recooler (in ads_out)
    res.update({
        "label": chain_label(site, tech, uses, storage, plans, P),
        "components": components(tech, uses, storage, plans, site, P),
        "it_mwh": e_it, "cooling_mwh": cooling, "fan_mwh": fan, "pump_mwh": pump, "chiller_mwh": chill,
        "other_mwh": other, "plant_mwh": plant, "hp_work_mwh": float(hp_work.sum()),
        "elec_generated_mwh": gen, "elec_exported_mwh": exported, "orc_condenser_mwh": orc_cond,
        "heat_rejected_mwh": q_rej + ads_out + orc_cond, "water_m3": water, "water_produced_m3": water_prod,
        "heat_delivered_mwh": useful_heat,
        "cold_delivered_mwh": float(sum(delivered[u].sum() for u in uses if plans[u].kind == "cold")),
        "heat_recovered_mwh": sum(sum(uses.values()) for uses in heat_to_uses.values()),
        "heat_loops": heat_loops,
        "losses_mwh": sum(float(v.sum()) for v in losses.values()) + float(store_loss.sum()),
        "pue": total_fac / e_it, "wue_l_kwh": water * 1000 / (e_it * 1000),
        "ere": (total_fac + plant - reused) / e_it,
        "co2_t": co2, "cost": cost, "net_cost_usd": net_cost, "capex": capex, "capex_usd": capex_total,
        "cop_hp": (sum(c * e for c, e in hp_cops) / sum(e for _, e in hp_cops)) if hp_cops else None,
        "hp_peak_mw": hp_out_peak, "balance_in_mwh": e_in, "balance_out_mwh": e_out,
        "balance_residual_mwh": e_in - e_out, "flows": flows,
        "chiller_hours": max(r["chiller_hours"] for r in rej.values()),
        "wet_hours": max(r["wet_hours"] for r in rej.values()),
    })
    if baseline is not None:
        add_deltas(res, baseline, P)
    return res


def add_deltas(r: dict, b: dict, P: dict) -> None:
    benefit = b["net_cost_usd"] - r["net_cost_usd"]
    dcap = r["capex_usd"] - b["capex_usd"]
    a = annuity(P)
    r["net_value_usd_yr"] = benefit
    # split: the water scarcity charge is a shadow price, not cash
    r["water_value_usd_yr"] = b["cost"]["water_scarcity_usd"] - r["cost"]["water_scarcity_usd"]
    r["cash_value_usd_yr"] = benefit - r["water_value_usd_yr"]
    r["delta_capex_usd"] = dcap
    r["npv_usd"] = benefit / a - dcap
    r["payback_yr"] = (dcap / benefit) if benefit > 0 and dcap > 0 else (0.0 if benefit > 0 else None)
    r["co2_avoided_t_yr"] = b["co2_t"] - r["co2_t"]
    r["water_saved_m3_yr"] = b["water_m3"] - r["water_m3"]
    r["electricity_saved_mwh_yr"] = (b["cooling_mwh"] + b["plant_mwh"]) - (r["cooling_mwh"] + r["plant_mwh"]) + r["elec_generated_mwh"]


def chain_label(site, tech, uses, storage, plans, P: dict | None = None) -> str:
    P = P or defaults()
    parts = [TECH_LABEL[tech]]
    t_hot = max(l.t_return_c for l in site.loops)
    for u in uses:
        pl = plans[u]
        if pl.kind == "heat" and not pl.direct_only and hp.needs_hp(t_hot, pl.t_req_c, P) and "heat pump" not in parts:
            parts.append("heat pump")
        parts.append(pl.label)
    if storage:
        parts.append({"tank": "daily tank", "ates": "ATES seasonal storage", "btes": "BTES seasonal storage"}[storage])
    return " + ".join(parts)


def components(tech, uses, storage, plans, site, P) -> list[str]:
    out = {"dry": ["dry_cooler"], "adiabatic": ["adiabatic_cooler"], "tower": ["cooling_tower"],
           "wind": ["wind_radiator", "dry_cooler"]}[tech][:]
    t_hot = max(l.t_return_c for l in site.loops)
    for u in uses:
        pl = plans[u]
        if pl.kind == "heat" and not pl.direct_only and hp.needs_hp(t_hot, pl.t_req_c, P):
            out.append("heat_pump")
        out.append("district_heating" if u.startswith("dh_") else u)
    if storage:
        out.append(storage)
    return out


# ---- optimizer ---------------------------------------------------------------------------------

def baseline(site, P: dict | None = None, plans=None) -> dict:
    P = P or defaults()
    return simulate(site, P, site.baseline_rejection, (), None, plans=plans)


def evaluate_site(site, P: dict | None = None, max_uses: int = 2) -> tuple[pd.DataFrame, dict, dict]:
    """All chains for a site, best first. Returns (table, baseline result, results by chain id)."""
    P = {**defaults(), **(P or {})}
    plans = build_plans(site, P)
    base = baseline(site, P, plans)
    add_deltas(base, base, P)
    results = {}
    for tech, uses, st in enumerate_chains(plans, max_uses, site_techs(site)):
        r = simulate(site, P, tech, uses, st, plans=plans, baseline=base)
        if r.get("ko"):
            continue
        cid = chain_id(tech, uses, st)
        r["chain_id"] = cid
        results[cid] = r
    rows = [{
        "chain_id": cid, "chain": r["label"], "tech": r["tech"], "uses": "+".join(r["uses"]) or "none",
        "storage": r["storage"] or "", "npv_usd": r["npv_usd"], "net_value_usd_yr": r["net_value_usd_yr"],
        "delta_capex_usd": r["delta_capex_usd"], "payback_yr": r["payback_yr"],
        "cash_value_usd_yr": r["cash_value_usd_yr"], "water_value_usd_yr": r["water_value_usd_yr"],
        "heat_delivered_mwh": r["heat_delivered_mwh"], "cold_delivered_mwh": r["cold_delivered_mwh"],
        "co2_avoided_t_yr": r["co2_avoided_t_yr"], "water_saved_m3_yr": r["water_saved_m3_yr"],
        "water_produced_m3": r["water_produced_m3"], "pue": r["pue"], "wue_l_kwh": r["wue_l_kwh"], "ere": r["ere"],
        "cop_hp": r["cop_hp"], "balance_residual_mwh": r["balance_residual_mwh"],
    } for cid, r in results.items()]
    df = pd.DataFrame(rows).sort_values("npv_usd", ascending=False).reset_index(drop=True)
    # value of the heat use itself: chain NPV minus the same heat rejection without any use
    alone = df[df["uses"] == "none"].set_index("tech")["npv_usd"]
    df["reuse_npv_usd"] = df["npv_usd"] - df["tech"].map(alone)
    for cid, v in zip(df["chain_id"], df["reuse_npv_usd"]):
        results[cid]["reuse_npv_usd"] = v
    df.insert(0, "rank", np.arange(1, len(df) + 1))
    ko = {n: p.ko for n, p in plans.items() if p.ko and n not in DH_SIZED_PLANS}
    df.attrs.update(site_id=site.site_id, ko=ko)
    return df, base, results


def chain_id(tech, uses, storage) -> str:
    return "|".join([tech, *uses] + ([storage] if storage else []))


def best_per_use(df: pd.DataFrame) -> pd.DataFrame:
    """Best chain for each heat use family (plus heat rejection only), for presentation."""
    fam = df["uses"].str.split("+").str[0].str.replace(r"_(meso|thermo|med|md|\d+km(?:_peak\d+)?)$", "", regex=True)
    return df.assign(family=fam).sort_values("npv_usd", ascending=False).drop_duplicates("family")
