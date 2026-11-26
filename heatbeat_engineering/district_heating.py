"""District heating to the nearest community, with optional seasonal or daily storage.

Demand (hourly, MW): annual community demand E = linear heat density rho_heat (MWh per m of street
and year, site_gis.csv) x network length. Split into space heating, distributed over heating degree
hours HDH(h) = max(T_base - T_db(h), 0), and a flat hot water share.

Transmission line DC -> community over d_dh_m: `sinks.pipe` (losses W/m, pump power, DN sizing).
Distribution network losses: a share of delivered heat. Supply/return 70/40 C (4GDH), so a heat
pump is needed unless the source is above 73 C.

Value: delivered heat x customers' avoided gas heat cost x price share. Avoided CO2: delivered heat
from gas boilers (90 %) at 181 kg/MWh fuel.
"""
from __future__ import annotations

import numpy as np

from .sinks import H, SinkPlan, annuity, ko_plan, pipe


def demand_profile(site, P: dict, network_km: float) -> np.ndarray:
    e_year = site.x["rho_heat_mwh_m"] * network_km * 1000.0
    hdh = np.clip(P["dh_hdh_base_c"] - site.t_db, 0, None)
    sh = (1 - P["dh_dhw_share"]) * e_year * (hdh / hdh.sum() if hdh.sum() > 0 else np.zeros(H))
    dhw = P["dh_dhw_share"] * e_year / H
    return sh + dhw


def plan(site, P: dict, network_km: float | None = None, peak_share: int = 100) -> SinkPlan:
    km = network_km if network_km is not None else P["dh_network_km"]
    distance = site.x["d_dh_m"] / 1000
    distance_prov = site.prov.get("d_dh_m", {})
    if distance_prov.get("lower_bound"):
        line = f"{distance:.1f} km line lower bound"
    elif distance_prov.get("status") == "user":
        line = f"{distance:.1f} km specified line"
    else:
        line = f"{distance:.1f} km estimated line"
    label = f"District heating ({km:.0f} km modeled network, {line})"
    if peak_share < 100:
        label += f" at {peak_share}% peak demand"
    L = max(site.x["d_dh_m"], 300.0)
    if L > P["dh_max_transmission_km"] * 1000:
        return ko_plan("district_heating", label, f"community {L / 1000:.0f} km away (> {P['dh_max_transmission_km']:.0f} km)")
    network_demand = demand_profile(site, P, km)
    dem = np.minimum(network_demand, network_demand.max() * peak_share / 100)
    peak = float(dem.max() * (1 + P["dh_dist_loss_share"]))
    tg = float(np.clip(site.t_mean, 5, 20))
    pp = pipe(L, peak, P["dh_supply_c"], P["dh_return_c"], tg, P)
    loss = pp["loss_mw"] + dem * P["dh_dist_loss_share"]
    aux = pp["pump_design_mw"] * (dem / max(dem.max(), 1e-9)) ** 3
    gas_ef = P["ng_kg_co2_per_mwh_fuel"] / 0.9 / 1000  # t CO2 per MWh heat from a gas boiler

    def settle(q):
        e = float(np.sum(q))
        capex = pp["capex_usd"] + P["capex_dist_network_usd_m"] * km * 1000 * P["capex_factor"]
        return {"revenue_usd": e * site.x["p_heat_usd_mwh"] * P["dh_heat_price_share"],
                "co2_avoided_t": e * gas_ef, "capex_usd": capex,
                "detail": {"dn_mm": round(pp["dn_mm"]), "pipe_loss_mw": round(pp["loss_mw"], 3),
                           "pipe_u_w_mk": round(pp["u_w_mk"], 3), "pump_design_kw": round(pp["pump_design_mw"] * 1000, 1),
                           "community_demand_mwh": round(float(network_demand.sum())),
                           "peak_share": peak_share, "peak_mw": round(peak, 2),
                           "served_share": round(e / max(float(network_demand.sum()), 1e-9), 3)}}

    return SinkPlan("district_heating", label, P["dh_supply_c"], dem, loss, aux, settle=settle,
                    notes=[f"transmission DN{pp['dn_mm']:.0f}, U' {pp['u_w_mk']:.2f} W/mK, "
                           f"loss {pp['loss_mw'] * 1000:.0f} kW continuous"])


# ---- storage: shift surplus source heat into hours of unmet demand -----------------------------

def shift(surplus_mw: np.ndarray, deficit_mw: np.ndarray, window_h: int, eta: float) -> tuple[np.ndarray, np.ndarray, float]:
    """Per window: charge surplus, discharge into deficits with round trip efficiency eta.

    Returns (heat taken from the surplus per hour, heat delivered per hour, storage capacity in MWh).
    Charge happens before discharge inside a window (seasonal: window = year, summer charges first
    because the year is rolled to start in April).
    """
    n = len(surplus_mw)
    take, give = np.zeros(n), np.zeros(n)
    cap = 0.0
    for s in range(0, n, window_h):
        sl = slice(s, min(s + window_h, n))
        su, de = surplus_mw[sl].sum(), deficit_mw[sl].sum()
        stored = min(su, de / eta)
        if stored <= 0:
            continue
        take[sl] = surplus_mw[sl] * stored / su
        give[sl] = deficit_mw[sl] * stored * eta / de
        cap = max(cap, stored)
    return take, give, cap


STORAGE = {
    # name: (window hours, efficiency key or value, capex key, geology needed)
    "tank": (24, 0.95, "capex_tank_usd_kwh", False),
    "ates": (H, "ates_recovery", "capex_ates_usd_kwh", True),
    "btes": (H, "btes_recovery", "capex_btes_usd_kwh", True),
}


def storage_ko(kind: str, site, P: dict) -> str | None:
    if STORAGE[kind][3] and site.x["geo_storage_score"] < P["storage_min_geo_score"]:
        return f"geo_storage_score {site.x['geo_storage_score']:.0f} < {P['storage_min_geo_score']:.0f}"
    return None


def apply_storage(kind: str, surplus_mw, deficit_mw, P: dict):
    window, eff, capex_key, _ = STORAGE[kind]
    eta = P[eff] if isinstance(eff, str) else eff
    if window == H:  # seasonal: start the year in April so summer surplus is charged before winter
        roll = 90 * 24
        t, g, cap = shift(np.roll(surplus_mw, -roll), np.roll(deficit_mw, -roll), window, eta)
        t, g = np.roll(t, roll), np.roll(g, roll)
    else:
        t, g, cap = shift(surplus_mw, deficit_mw, window, eta)
    return t, g, cap, cap * 1000 * P[capex_key] * P["capex_factor"]
