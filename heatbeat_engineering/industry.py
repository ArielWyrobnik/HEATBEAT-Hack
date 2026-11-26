"""Neighbour sinks that take heat at fixed conditions: boiler feedwater preheat, desalination, ORC.

Boiler feedwater (power plant at d_pp_m, EIA-860): DC heat preheats condensate / makeup water to
fw_target_c, replacing low pressure extraction steam, so the turbine produces more electricity
(fw_kwh_e_per_kwh_th). Demand = q_fw_mw x capacity factor.

Desalination (coast within desal_max_coast_km):
  MED: number of effects n = floor((T_steam - T_cond) / dT_effect), T_steam = source - approach,
       T_cond = seawater + 5 K. GOR = 0.85 n. Thermal energy = 2330 kJ/kg / GOR.
       With a 55 C source and 20 C sea only about 7 effects are possible; at 35 C almost none.
  MD:  GOR 1 to 5, works from about 50 C but needs much more heat per m3.
  Counterfactual: seawater RO at 3.5 kWh_e/m3.

ORC: efficiency = carnot_fraction x (1 - T_cond / T_hot), T_cond = dry bulb + 10 K.
     At a 55 C source this is about 3 to 5 %, which is the honest answer the model shows.
"""
from __future__ import annotations

import numpy as np

from .sinks import H, SinkPlan, ko_plan, pipe

LATENT_KWH_M3 = 2330 / 3.6  # kWh_th per m3 distillate at GOR 1


def feedwater_plan(site, P: dict) -> SinkPlan:
    label = f"Boiler feedwater preheat ({site.x.get('pp_name') or 'power plant'}, {site.x['d_pp_m'] / 1000:.1f} km)"
    d, q = site.x["d_pp_m"], site.x["q_fw_mw"]
    if d > P["fw_max_km"] * 1000:
        return ko_plan("feedwater", label, f"thermal power plant {d / 1000:.0f} km away (> {P['fw_max_km']:.0f} km)")
    if q <= 0:
        return ko_plan("feedwater", label, "no steam plant feedwater demand")
    dem = np.full(H, q * P["fw_capacity_factor"])
    t_s = P["fw_target_c"] + 5
    pp = pipe(d, q, t_s, P["fw_target_c"] - 15, float(np.clip(site.t_mean, 5, 20)), P)
    p_wh = site.x.get("p_wholesale_usd_mwh", site.x["p_elec_usd_mwh"] * 0.6) * P["p_wholesale_share"]

    def settle(qd):
        e = float(np.sum(qd))
        mwh_e = e * P["fw_kwh_e_per_kwh_th"]
        return {"revenue_usd": mwh_e * p_wh, "co2_avoided_t": mwh_e * site.x["ci_grid_kg_mwh"] / 1000,
                "capex_usd": pp["capex_usd"] + P["capex_hx_usd_kw"] * q * 1000 * P["capex_factor"],
                "elec_exported_mwh": mwh_e,
                "detail": {"extra_turbine_mwh_e": round(mwh_e), "dn_mm": round(pp["dn_mm"]),
                           "wholesale_usd_mwh": round(p_wh, 1)}}

    return SinkPlan("feedwater", label, t_s, dem, pp["loss_mw"], pp["pump_design_mw"], settle=settle)


def _sea_c(site, P):
    return site.t_mean + P["sea_above_air_k"]


def med_effects(t_source_c: float, site, P: dict) -> int:
    t_steam = t_source_c - P["hx_approach_k"]
    return int(max(np.floor((t_steam - (_sea_c(site, P) + 5)) / P["med_dt_per_effect_k"]), 0))


def desal_plan(site, P: dict, tech: str, t_source_c: float) -> SinkPlan:
    name, label = f"desal_{tech}", f"Desalination ({tech.upper()}, coast {site.x['d_coast_m'] / 1000:.1f} km)"
    if site.x["d_coast_m"] > P["desal_max_coast_km"] * 1000:
        return ko_plan(name, label, f"coast {site.x['d_coast_m'] / 1000:.0f} km away (> {P['desal_max_coast_km']:.0f} km)")
    if tech == "med":
        n = med_effects(t_source_c, site, P)
        if n < 2:
            return ko_plan(name, label, f"source {t_source_c:.0f} C allows only {n} MED effect(s)")
        gor, kwh_e = P["med_gor_per_effect"] * n, P["med_kwh_e_m3"]
    else:
        if t_source_c - P["hx_approach_k"] < 45:
            return ko_plan(name, label, f"source {t_source_c:.0f} C too cold for membrane distillation")
        gor, kwh_e, n = P["md_gor"], P["md_kwh_e_m3"], 0
    kwh_th = LATENT_KWH_M3 / gor
    p_w = site.x["p_water_usd_m3"] * P["desal_water_value_share"]
    capex_key = "capex_med_usd_m3d" if tech == "med" else "capex_md_usd_m3d"

    def settle(q):
        m3 = float(np.sum(q)) * 1000 / kwh_th
        m3d_peak = float(np.max(q)) * 1000 / kwh_th * 24
        intake = pipe(site.x["d_coast_m"], 0.0, 30, 25, 15, P)  # nominal DN for intake + outfall cost
        capex = P[capex_key] * m3d_peak * P["capex_factor"] + 2 * intake["capex_usd"]
        e_net = m3 * (kwh_e - P["ro_kwh_e_m3"]) / 1000  # vs RO counterfactual (negative = saving)
        return {"revenue_usd": m3 * p_w - m3 * kwh_e / 1000 * site.x["p_elec_usd_mwh"],
                "co2_avoided_t": -e_net * site.x["ci_grid_kg_mwh"] / 1000, "water_produced_m3": m3,
                "capex_usd": capex,
                "detail": {"effects": n, "gor": round(gor, 2), "kwh_th_m3": round(kwh_th, 1),
                           "m3_day_peak": round(m3d_peak)}}

    return SinkPlan(name, label, t_source_c - P["hx_approach_k"], None, settle=settle, direct_only=True,
                    notes=[f"GOR {gor:.1f}, {kwh_th:.0f} kWh_th/m3"])


def orc_efficiency(t_source_c: float, t_db, P: dict):
    th = t_source_c - P["hx_approach_k"] + 273.15
    tc = np.asarray(t_db, float) + P["orc_cond_above_air_k"] + 273.15
    eta = P["orc_carnot_fraction"] * (1 - tc / th)
    return np.where(th - tc >= P["orc_min_dt_k"], np.clip(eta, 0, None), 0.0)


def orc_plan(site, P: dict, t_source_c: float) -> SinkPlan:
    label = "ORC power generation"
    eta = orc_efficiency(t_source_c, site.t_db, P)
    if eta.max() <= 0:
        return ko_plan("orc", label, f"source {t_source_c:.0f} C is less than {P['orc_min_dt_k']:.0f} K above the condenser")

    def settle(q):
        w = q * eta
        mwh = float(w.sum())
        cond = float((q - w).sum())
        fans = cond * P["sfp_dry_kw_kw"]
        return {"revenue_usd": (mwh - fans) * site.x["p_elec_usd_mwh"],
                "co2_avoided_t": (mwh - fans) * site.x["ci_grid_kg_mwh"] / 1000,
                "capex_usd": P["capex_orc_usd_kwe"] * float(w.max()) * 1000 * P["capex_factor"],
                "elec_generated_mwh": mwh, "orc_condenser_mwh": cond, "aux_extra_mwh": fans,
                "detail": {"eta_mean": round(mwh / max(float(q.sum()), 1e-9), 4), "eta_max": round(float(eta.max()), 4)}}

    # the ORC runs only in hours where it can produce power; otherwise the heat goes to the cooler
    dem = np.where(eta > 0, 1e9, 0.0)
    return SinkPlan("orc", label, t_source_c - P["hx_approach_k"], dem, settle=settle, direct_only=True,
                    notes=[f"mean efficiency {float(eta.mean()) * 100:.1f} %"])
