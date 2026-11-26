"""Heat rejection ("radiator") models, hourly: dry cooler, adiabatic cooler, cooling tower.

All three cool a loop from its return temperature T_ret back to its supply temperature T_sup.
Each technology has an effective air side temperature it can approach:

    dry cooler        T_air = T_db                                   leaving fluid >= T_db + dry_approach
    adiabatic cooler  T_air = T_db - eff (T_db - T_wb) when wetted   leaving fluid >= T_air + dry_approach
                      (runs dry whenever dry operation reaches T_sup, so water is used only in hot hours)
    cooling tower     T_air = T_wb                                   leaving fluid >= T_wb + tower + HX approach

Series economizer logic: the cooler pre-cools as far as it can; if its leaving temperature T_lv is
above T_sup a trim chiller removes the rest. Chiller share of the load = (T_lv - T_sup)/(T_ret - T_sup),
clipped to 0..1. Chiller COP = carnot_fraction x T_evap / (T_cond - T_evap).

Fan power follows the fan affinity law. Required air flow scales with Q / (T_ret - T_air); power with
flow cubed, normalised to the design point (full load at the hottest hour), capped at design power.

Water: tower evaporation = Q x latent_share / h_fg, plus blowdown = evaporation / (cycles - 1).
Adiabatic spray = air mass flow x evaporative cooling / h_fg = Q x eff (T_db - T_wb) / (air_range x h_fg),
only in wetted hours. Dry cooler: no water.
"""
from __future__ import annotations

import numpy as np

TECHS = ("dry", "adiabatic", "tower")


def chiller_cop(t_evap_c, t_cond_c, P):
    te = np.asarray(t_evap_c, float) + 273.15
    tc = np.asarray(t_cond_c, float) + 273.15
    lift = np.maximum(tc - te, 1.0)
    return np.clip(P["chiller_carnot_fraction"] * te / lift, 2.0, P["chiller_cop_max"])


def reject(tech: str, q_mw, t_sup_c: float, t_ret_c: float, t_db, t_wb, P: dict,
           q_design_mw: float | None = None, chiller_offload_mw=0.0) -> dict:
    """Hourly results for rejecting q_mw (array or scalar) from a loop T_ret -> T_sup.

    Returns arrays (MW or m3/h): fan_mw, pump_mw, chiller_mw, chiller_load_mw, water_m3h, t_leave_c,
    and annual sums in MWh / m3. The chiller condenser heat (load + work) is rejected by the same plant.
    chiller_offload_mw: cold supplied by another machine (adsorption chiller) that replaces part of the
    trim chiller load; that heat leaves through the other machine, not through this cooler.
    """
    t_db, t_wb = np.asarray(t_db, float), np.asarray(t_wb, float)
    q = np.broadcast_to(np.asarray(q_mw, float), t_db.shape).astype(float)
    app_dry = P["dry_approach_k"]
    if tech == "dry":
        t_air = t_db.copy()
        t_lv = t_air + app_dry
        wet = np.zeros_like(t_db, bool)
        sfp = P["sfp_dry_kw_kw"]
    elif tech == "adiabatic":
        dry_ok = t_db + app_dry <= t_sup_c
        t_pre = t_db - P["adiabatic_eff"] * (t_db - t_wb)
        wet = ~dry_ok
        t_air = np.where(wet, t_pre, t_db)
        t_lv = t_air + app_dry
        sfp = P["sfp_adiabatic_kw_kw"]
    elif tech == "tower":
        t_air = t_wb.copy()
        t_lv = t_wb + P["tower_approach_k"] + P["tower_hx_approach_k"]
        wet = np.ones_like(t_db, bool)
        sfp = P["sfp_tower_kw_kw"]
    else:
        raise ValueError(f"tech must be one of {TECHS}")

    rng = max(t_ret_c - t_sup_c, 0.5)
    ch_share = np.clip((t_lv - t_sup_c) / rng, 0.0, 1.0)
    ch_load_full = q * ch_share
    offload = np.minimum(np.broadcast_to(np.asarray(chiller_offload_mw, float), q.shape), ch_load_full)
    ch_load = ch_load_full - offload
    cop = chiller_cop(t_sup_c - P["chiller_lift_extra_k"] / 2, t_lv + P["chiller_lift_extra_k"] / 2, P)
    ch_mw = np.where(ch_load > 0, ch_load / cop, 0.0)
    q_rej = q - offload + ch_mw  # heat leaving through the cooler (loop heat + chiller work - offload)

    # fan affinity law: flow ~ Q / (T_ret - T_air); design = max load at the hottest hour
    dt = np.maximum(t_ret_c - t_air, 2.0)
    flow = q_rej / dt
    qd = q_design_mw if q_design_mw is not None else max(float(np.max(q_rej)), 1e-6)
    flow_d = qd / float(np.min(dt))
    fan = sfp * qd * np.clip(flow / flow_d, 0, 1) ** 3
    pump = P["pump_kw_kw"] * q_rej

    h_fg = P["h_fg_mj_kg"] * 1000.0  # MJ/t -> per m3 at ~1 t/m3
    if tech == "tower":
        evap = q_rej * 3600.0 * P["tower_latent_share"] / h_fg  # m3/h (MW * 3600 MJ/MWh / MJ/m3)
        water = evap * P["tower_cycles"] / (P["tower_cycles"] - 1.0)
    elif tech == "adiabatic":
        dtev = np.clip(t_db - t_air, 0, None)
        water = np.where(wet, q_rej * 3600.0 * dtev / (P["adiabatic_air_range_k"] * h_fg), 0.0)
    else:
        water = np.zeros_like(q)
    return {
        "chiller_load_full_mw": ch_load_full, "offload_mw": offload, "fan_mw": fan, "pump_mw": pump, "chiller_mw": ch_mw, "chiller_load_mw": ch_load,
        "water_m3h": water, "t_leave_c": t_lv, "q_rejected_mw": q_rej,
        "fan_mwh": float(fan.sum()), "pump_mwh": float(pump.sum()), "chiller_mwh": float(ch_mw.sum()),
        "water_m3": float(water.sum()), "q_rejected_mwh": float(q_rej.sum()),
        "wet_hours": int(wet.sum()) if tech != "dry" else 0,
        "chiller_hours": int((ch_share > 0).sum()),
        "q_design_mw": qd,
    }


def capex_usd(tech: str, q_design_mw: float, P: dict) -> float:
    key = {"dry": "capex_dry_usd_kw", "adiabatic": "capex_adiabatic_usd_kw", "tower": "capex_tower_usd_kw"}[tech]
    return P[key] * q_design_mw * 1000.0 * P["capex_factor"]
