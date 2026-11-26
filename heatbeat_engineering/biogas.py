"""Anaerobic digester heating with data center heat (mesophilic 38 C or thermophilic 55 C).

Digester heat demand per hour:
    feed heating   Q_f = m_feed cp (T_dig - T_feed),   T_feed = daily mean air, clipped 2..25 C
    wall losses    Q_w = U A (T_dig - T_air),          A = 1.5 pi D^2 for a cylinder with H = D (wall + roof)
                                                       V = feed volume per day x retention time
This is why biogas is site specific: the same plant needs much more heat in Iowa than in Arizona.

Baseline (counterfactual without the data center): the digester burns part of its own biogas in a
boiler. With DC heat that biogas is upgraded and sold as RNG: gas value + D3 RIN + LCFS credit
(CA, OR, WA only). Thermophilic operation also raises the methane yield (bio_thermo_yield_gain).

Logistics: either a heat line to the feedstock site (d_bio_m) or the feedstock is trucked to a
digester next to the data center; the cheaper of the two is taken.
Feedstock quantity per site is NOT in the data: a reference plant (bio_feed_t_day) is used, flagged.

CAPEX: heat exchanger, heat line (if used), an upgrading unit that turns the freed biogas into RNG
(sized for the freed raw biogas flow, plus its electricity), and a new digester when feedstock is
trucked to the data center (the heat line case heats the existing digester of the baseline).
"""
from __future__ import annotations

import numpy as np

from .sinks import H, SinkPlan, annuity, ko_plan, pipe


def heat_demand(site, P: dict, t_dig_c: float) -> tuple[np.ndarray, dict]:
    feed = P["bio_feed_t_day"]  # t/day ~ m3/day
    m = feed * 1000 / 86400  # kg/s
    t_day = site.t_db.reshape(365, 24).mean(axis=1).repeat(24)
    t_feed = np.clip(t_day, 2, 25)
    q_feed = m * P["cp_water_kj_kgk"] * (t_dig_c - t_feed) / 1000  # MW
    vol = feed * P["bio_hrt_days"]
    d = (4 * vol / np.pi) ** (1 / 3)
    area = 1.5 * np.pi * d ** 2
    q_wall = P["bio_wall_u_w_m2k"] * area * np.clip(t_dig_c - site.t_db, 0, None) / 1e6
    return np.clip(q_feed, 0, None) + q_wall, {"volume_m3": round(vol), "diameter_m": round(d, 1),
                                               "wall_mwh": round(float(q_wall.sum())),
                                               "feed_mwh": round(float(np.clip(q_feed, 0, None).sum()))}


def plan(site, P: dict, mode: str = "meso") -> SinkPlan:
    t_dig = P["bio_meso_c"] if mode == "meso" else P["bio_thermo_c"]
    name = f"biogas_{mode}"
    label = f"Biogas digester heating ({'mesophilic' if mode == 'meso' else 'thermophilic'} {t_dig:.0f} C)"
    d = site.x["d_bio_m"]
    if d > P["bio_max_km"] * 1000:
        return ko_plan(name, label, f"nearest feedstock {d / 1000:.0f} km away (> {P['bio_max_km']:.0f} km)")
    kind = str(site.x.get("bio_kind") or "")
    if kind.startswith("forestry"):
        return ko_plan(name, label, f"nearest feedstock is {kind}, not digestible (lignin): no anaerobic digestion")
    dem, det = heat_demand(site, P, t_dig)
    vol_m3 = P["bio_feed_t_day"] * P["bio_hrt_days"]
    t_supply = t_dig + 7.0  # heating water to the digester coils
    pp = pipe(max(d, 100.0), float(dem.max()), t_supply, t_dig - 3, float(np.clip(site.t_mean, 5, 20)), P)
    a = annuity(P)
    pipe_cost_yr = pp["capex_usd"] * a  # heat line option
    truck_cost_yr = P["bio_feed_t_day"] * 365 * d / 1000 * P["bio_truck_usd_t_km"]
    truck_total_yr = truck_cost_yr + P["capex_digester_usd_m3"] * vol_m3 * P["capex_factor"] * a
    use_pipe = pipe_cost_yr + pp["loss_mw"] * H * site.x["p_heat_usd_mwh"] * 0.3 < truck_total_yr
    loss = pp["loss_mw"] if use_pipe else 0.0
    aux = pp["pump_design_mw"] * (dem / dem.max()) ** 3 if use_pipe else 0.0
    ch4_nm3_day = P["bio_feed_t_day"] * P["bio_biogas_nm3_t"] * P["bio_ch4_share"]
    base_ch4_mwh = ch4_nm3_day * 365 * P["bio_ch4_kwh_nm3"] / 1000
    gain_mwh = base_ch4_mwh * (P["bio_thermo_yield_gain"] if mode == "thermo" else 0.0)
    # RNG value per MWh: wholesale gas + D3 RIN (per MMBtu, 3.412 MMBtu/MWh) + LCFS (t CO2e saved per MWh)
    lcfs_t_mwh = max(P["lcfs_ref_ci_g_mj"] - P["rng_ci_g_mj"], 0) * 3600 / 1e6
    v_rng = site.x["p_gas_usd_mwh"] + site.x["rin_usd_mmbtu"] * 3.412 + site.x["lcfs_usd_t"] * lcfs_t_mwh
    ef = P["ng_kg_co2_per_mwh_fuel"] / 1000

    def settle(q):
        e = float(np.sum(q))
        saved_biogas = e / P["bio_boiler_eff"]
        served = e / max(float(dem.sum()), 1e-9)
        extra = gain_mwh * served
        rng_mwh = saved_biogas + extra
        # freed biogas must be upgraded to RNG before it can be sold: unit sized for the freed raw biogas flow
        raw_nm3 = rng_mwh * 1000 / P["bio_ch4_kwh_nm3"] / P["bio_ch4_share"]
        upgrade_capex = P["bio_upgrade_capex_usd_nm3h"] * raw_nm3 / H * P["capex_factor"]
        upgrade_elec_usd = raw_nm3 * P["bio_upgrade_kwh_nm3"] / 1000 * site.x["p_elec_usd_mwh"]
        # trucking feedstock means a new digester next to the data center
        digester_capex = 0.0 if use_pipe else P["capex_digester_usd_m3"] * vol_m3 * P["capex_factor"]
        capex = ((pp["capex_usd"] if use_pipe else 0.0) + P["capex_hx_usd_kw"] * dem.max() * 1000 * P["capex_factor"]
                 + upgrade_capex + digester_capex)
        opex = (0.0 if use_pipe else truck_cost_yr * served) + upgrade_elec_usd
        return {"revenue_usd": rng_mwh * v_rng - opex, "co2_avoided_t": rng_mwh * ef,
                "capex_usd": capex,
                "detail": {**det, "logistics": "heat line" if use_pipe else "truck feedstock to DC",
                           "upgrade_capex_usd": round(upgrade_capex), "digester_capex_usd": round(digester_capex),
                           "upgrade_nm3_h": round(raw_nm3 / H, 1),
                           "rng_value_usd_mwh": round(v_rng, 1), "rng_freed_mwh": round(saved_biogas + extra),
                           "plant_ch4_mwh": round(base_ch4_mwh), "heat_share_of_ch4": round(dem.sum() / base_ch4_mwh, 3),
                           "feedstock": site.x.get("bio_name")}}

    return SinkPlan(name, label, t_supply, dem, loss, aux, settle=settle,
                    notes=[f"reference plant {P['bio_feed_t_day']:.0f} t/day (ASSUMPTION), "
                           f"{'heat line' if use_pipe else 'feedstock trucked'} {d / 1000:.1f} km"])
