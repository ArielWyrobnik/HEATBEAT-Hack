"""Anaerobic digester heating with data center heat (mesophilic 38 C or thermophilic 55 C), sized per site.

Digester heat demand per hour:
    feed heating   Q_f = m_feed cp (T_dig - T_feed),   T_feed = daily mean air, clipped 2..25 C
    wall losses    Q_w = U A (T_dig - T_air),          A = 1.5 pi D^2 for a cylinder with H = D (wall + roof)
                                                       V = feed volume per day x retention time
This is why biogas is site specific: the same plant needs much more heat in Iowa than in Arizona.

Two business cases, picked from the nearest feedstock in site_industry.csv:

1. Existing digester (an EIA-860 digester gas plant, e.g. a wastewater treatment plant): its size is
   known from the EIA electrical capacity (bio_capacity_mw). A heat line from the data center heats it.
   Counterfactual: the plant heats itself with part of its own biogas (boiler). With DC heat that
   biogas is freed, upgraded and sold as RNG. Size is not a choice here.

2. New co-digestion plant (food processing waste, manure, unknown source): the plant does not exist
   today, so it is designed with the data center. Counterfactual: no digester (the waste is landfilled or
   land applied). The chain counts the whole plant: all RNG sold, digester and upgrading CAPEX, feedstock
   trucking, O&M. Its size is optimised per site (`size_new_plant`): bigger plants are cheaper per tonne
   (CAPEX scales with size^exponent, six-tenths rule) but must collect feedstock from a wider radius,
   so trucking grows with size. The DC heat replaces the 10 to 20 % of the gas a plant would otherwise
   burn to heat itself; `detail` reports this share (dc_heat_value_usd_yr) and the NPV the same plant
   would have without the data center (standalone_npv_usd), so the DC contribution stays visible.

RNG value per MWh: wholesale gas + D3 RIN + LCFS credit (CA, OR, WA only). Thermophilic operation also
raises the methane yield (bio_thermo_yield_gain).
Logistics: a heat line to the digester (d_bio_m) or (new plant only) the feedstock is trucked to a
digester next to the data center; the cheaper of the two is taken.
Feedstock quantity per site is NOT in the data: the nearest source supplies bio_feed_t_day (anchor),
more comes from the region at bio_feed_density_t_day_km2. Both are flagged assumptions.
"""
from __future__ import annotations

import numpy as np

from . import heat_pump as hp
from .sinks import H, SinkPlan, annuity, ko_plan, pipe

# candidate feed rates of a new plant, t/day (wet). 300 t/day was the old fixed reference plant.
FEED_SIZES = (50.0, 100.0, 200.0, 300.0, 500.0, 800.0, 1200.0, 2000.0, 3000.0)
REF_FEED = 300.0  # t/day at which the specific CAPEX parameters are quoted


def heat_demand(site, P: dict, t_dig_c: float, feed: float | None = None) -> tuple[np.ndarray, dict]:
    feed = P["bio_feed_t_day"] if feed is None else feed  # t/day ~ m3/day
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


def ch4_mwh_yr(feed_t_day: float, P: dict) -> float:
    """Methane energy of the plant's raw biogas, MWh/yr."""
    return feed_t_day * P["bio_biogas_nm3_t"] * P["bio_ch4_share"] * 365 * P["bio_ch4_kwh_nm3"] / 1000


def existing_feed_t_day(cap_mw_e: float, P: dict) -> float:
    """Feed rate equivalent of an existing digester gas plant from its EIA electrical capacity.

    CH4 energy = capacity x 8760 x capacity factor / electrical efficiency; feed = CH4 / (CH4 per tonne).
    """
    ch4 = cap_mw_e * H * P["bio_chp_cf"] / P["bio_chp_eff_e"]
    return ch4 / ch4_mwh_yr(1.0, P)


def digester_capex(feed: float, P: dict) -> float:
    vol_ref = REF_FEED * P["bio_hrt_days"]
    return P["capex_digester_usd_m3"] * vol_ref * (feed / REF_FEED) ** P["bio_digester_scale_exp"] * P["capex_factor"]


def upgrade_capex(raw_nm3_h: float, P: dict) -> float:
    """Upgrading + grid injection, sized for raw_nm3_h, six-tenths style scaling around the reference plant."""
    if raw_nm3_h <= 0:
        return 0.0
    q_ref = REF_FEED * P["bio_biogas_nm3_t"] / 24
    return P["bio_upgrade_capex_usd_nm3h"] * q_ref * (raw_nm3_h / q_ref) ** P["bio_upgrade_scale_exp"] * P["capex_factor"]


def collection_km(feed: float, P: dict) -> float:
    """Mean one way haul beyond the anchor source: uniform disk of radius r, mean distance 2/3 r."""
    extra = max(feed - P["bio_feed_t_day"], 0.0)
    if extra <= 0:
        return 0.0
    r = np.sqrt(extra / (np.pi * P["bio_feed_density_t_day_km2"]))
    return float(r)


def rng_value(site, P: dict) -> float:
    # wholesale gas + D3 RIN (per MMBtu, 3.412 MMBtu/MWh) + LCFS (t CO2e saved per MWh)
    lcfs_t_mwh = max(P["lcfs_ref_ci_g_mj"] - P["rng_ci_g_mj"], 0) * 3600 / 1e6
    return site.x["p_gas_usd_mwh"] + site.x["rin_usd_mmbtu"] * 3.412 + site.x["lcfs_usd_t"] * lcfs_t_mwh


def _dc_heat_cost(site, P: dict, dem: np.ndarray, t_supply: float) -> tuple[np.ndarray, float, float]:
    """Screening for sizing: heat the DC can deliver per hour, electricity cost and CAPEX of the HX / heat pump.

    Same order as the chain simulator: hottest loop first, each loop directly through a heat exchanger
    when hot enough, else through a heat pump with that loop's own COP (source heat = delivered x (1 - 1/COP)).
    """
    served = np.zeros(H)
    e_mwh = capex = 0.0
    for l in sorted(site.loops, key=lambda l: -l.t_return_c):
        need = np.clip(dem - served, 0, None)
        if not need.any():
            break
        if hp.needs_hp(l.t_return_c, t_supply, P):
            c = float(hp.cop(l.t_return_c, t_supply, P))
            out = np.minimum(need, l.q_mw / (1 - 1 / c))
            e_mwh += float((out / c).sum())
            capex += P["capex_hp_usd_kw"] * float(out.max()) * 1000 * P["capex_factor"]
        else:
            out = np.minimum(need, l.q_mw)
            capex += P["capex_hx_usd_kw"] * float(out.max()) * 1000 * P["capex_factor"]
        served = served + out
    return served, e_mwh * site.x["p_elec_usd_mwh"], capex


def _new_plant_economics(site, P: dict, feed: float, t_dig: float, mode: str, d: float, with_dc: bool = True,
                         use_pipe: bool = True):
    """Yearly cash flow and CAPEX of a whole new plant of `feed` t/day (screening for the size choice).

    use_pipe=True: plant at the feedstock source, heat line from the DC; False: feedstock trucked to a plant
    next to the DC. with_dc=False: the same plant at the source, heated with its own biogas (counterfactual).
    """
    dem, det = heat_demand(site, P, t_dig, feed)
    t_supply = t_dig + 7.0
    v_rng = rng_value(site, P)
    gain = P["bio_thermo_yield_gain"] if mode == "thermo" else 0.0
    ch4 = ch4_mwh_yr(feed, P) * (1 + gain)
    r_km = collection_km(feed, P)
    if r_km > P["bio_max_km"]:
        return None
    pp = pipe(max(d, 100.0), float(dem.max()), t_supply, t_dig - 3, float(np.clip(site.t_mean, 5, 20)), P)
    a = annuity(P)
    anchor = min(feed, P["bio_feed_t_day"])
    # regional feed is spread evenly, so it is collected around wherever the plant stands (mean 2/3 r);
    # a plant next to the DC also trucks the anchor feed over d
    haul_dc = (anchor * d / 1000 + (feed - anchor) * 2 / 3 * r_km) * 365 * P["bio_truck_usd_t_km"]
    haul_src = (feed - anchor) * 2 / 3 * r_km * 365 * P["bio_truck_usd_t_km"]  # plant at the anchor source
    if with_dc:
        served, e_cost, conv_capex = _dc_heat_cost(site, P, dem, t_supply)
        self_heat = float((dem - served).sum())
    else:
        use_pipe, served, e_cost, conv_capex, self_heat = True, np.zeros(H), 0.0, 0.0, float(dem.sum())
    rng = max(ch4 - self_heat / P["bio_boiler_eff"], 0.0)
    raw_nm3 = rng * 1000 / P["bio_ch4_kwh_nm3"] / P["bio_ch4_share"]  # raw biogas that is upgraded and sold
    up_cap = upgrade_capex(raw_nm3 / H, P)
    dig_cap = digester_capex(feed, P)
    line_cap = pp["capex_usd"] if (use_pipe and with_dc) else 0.0
    capex = dig_cap + up_cap + line_cap + conv_capex
    haul = haul_src if use_pipe else haul_dc
    opex = (haul + feed * 365 * (P["bio_om_usd_t"] - P["bio_tipping_usd_t"])
            + raw_nm3 * P["bio_upgrade_kwh_nm3"] / 1000 * site.x["p_elec_usd_mwh"] + e_cost
            + P["opex_share"] * capex)
    cash = rng * v_rng - opex
    return {"feed": feed, "npv": cash / a - capex, "cash": cash, "capex": capex, "rng": rng, "use_pipe": use_pipe,
            "r_km": r_km, "dem": dem, "det": det, "pp": pp, "haul": haul, "raw_nm3": raw_nm3,
            "dig_cap": dig_cap, "up_cap": up_cap, "self_heat": self_heat}


def size_new_plant(site, P: dict, t_dig: float, mode: str, d: float) -> tuple[dict, list[dict]]:
    """Best feed rate and logistics (heat line or trucking) by plant NPV with DC heat. Returns (best, NPV curve)."""
    cases = [c for f in FEED_SIZES for line in (True, False)
             if (c := _new_plant_economics(site, P, f, t_dig, mode, d, use_pipe=line)) is not None]
    best = max(cases, key=lambda c: c["npv"])
    curve = [{"feed_t_day": c["feed"], "npv_usd": round(c["npv"]), "capex_usd": round(c["capex"]),
              "collection_km": round(c["r_km"], 1)}
             for f in FEED_SIZES if (opts := [c for c in cases if c["feed"] == f])
             for c in [max(opts, key=lambda c: c["npv"])]]
    return best, curve


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
    cap = site.x.get("bio_capacity_mw")
    if cap is not None and np.isfinite(float(cap)) and float(cap) > 0:
        return _existing_plan(site, P, mode, t_dig, name, label, d, float(cap))
    return _new_plan(site, P, mode, t_dig, name, label, d)


def _existing_plan(site, P, mode, t_dig, name, label, d, cap_mw_e) -> SinkPlan:
    feed = existing_feed_t_day(cap_mw_e, P)
    dem, det = heat_demand(site, P, t_dig, feed)
    t_supply = t_dig + 7.0
    pp = pipe(max(d, 100.0), float(dem.max()), t_supply, t_dig - 3, float(np.clip(site.t_mean, 5, 20)), P)
    aux = pp["pump_design_mw"] * (dem / dem.max()) ** 3
    base_ch4 = ch4_mwh_yr(feed, P)
    gain_mwh = base_ch4 * (P["bio_thermo_yield_gain"] if mode == "thermo" else 0.0)
    v_rng = rng_value(site, P)
    ef = P["ng_kg_co2_per_mwh_fuel"] / 1000
    label = f"{label}, existing digester {feed:,.0f} t/day"

    def settle(q):
        e = float(np.sum(q))
        saved_biogas = e / P["bio_boiler_eff"]
        served = e / max(float(dem.sum()), 1e-9)
        rng_mwh = saved_biogas + gain_mwh * served
        raw_nm3 = rng_mwh * 1000 / P["bio_ch4_kwh_nm3"] / P["bio_ch4_share"]
        up = upgrade_capex(raw_nm3 / H, P)
        upgrade_elec_usd = raw_nm3 * P["bio_upgrade_kwh_nm3"] / 1000 * site.x["p_elec_usd_mwh"]
        return {"revenue_usd": rng_mwh * v_rng - upgrade_elec_usd, "co2_avoided_t": rng_mwh * ef,
                "capex_usd": pp["capex_usd"] + up,
                "detail": {**det, "case": "existing digester", "feed_t_day": round(feed),
                           "logistics": "heat line", "upgrade_capex_usd": round(up), "digester_capex_usd": 0,
                           "upgrade_nm3_h": round(raw_nm3 / H, 1), "rng_value_usd_mwh": round(v_rng, 1),
                           "rng_sold_mwh": round(rng_mwh), "rng_freed_mwh": round(rng_mwh),
                           "plant_ch4_mwh": round(base_ch4), "heat_share_of_ch4": round(dem.sum() / base_ch4, 3),
                           "feedstock": site.x.get("bio_name")}}

    return SinkPlan(name, label, t_supply, dem, pp["loss_mw"], aux, settle=settle,
                    notes=[f"existing digester sized from EIA capacity {cap_mw_e:.1f} MW_e (feed {feed:,.0f} t/day, "
                           "ESTIMATE); assumes it is heated by a biogas boiler today"])


def _new_plan(site, P, mode, t_dig, name, label, d) -> SinkPlan:
    """New plant, sized by the investor's NPV (plant + DC heat). The chain gets only what the DC heat adds.

    Counterfactual for the chain: the same plant (same size, same temperature mode) built at the feedstock
    source and heated with its own biogas. Digester CAPEX, O&M and the gas it sells anyway cancel out;
    what is left is the freed biogas (sold as RNG), the extra upgrading for it, the heat line or the extra
    trucking to a plant next to the DC. The full plant NPV is reported in the details, not in the chain.
    """
    best, curve = size_new_plant(site, P, t_dig, mode, d)
    sa = _new_plant_economics(site, P, best["feed"], t_dig, mode, d, with_dc=False)
    feed, dem, det, pp, use_pipe = best["feed"], best["dem"], best["det"], best["pp"], best["use_pipe"]
    t_supply = t_dig + 7.0
    loss = pp["loss_mw"] if use_pipe else 0.0
    aux = pp["pump_design_mw"] * (dem / dem.max()) ** 3 if use_pipe else 0.0
    gain = P["bio_thermo_yield_gain"] if mode == "thermo" else 0.0
    ch4 = ch4_mwh_yr(feed, P) * (1 + gain)
    v_rng = rng_value(site, P)
    ef = P["ng_kg_co2_per_mwh_fuel"] / 1000
    extra_haul = best["haul"] - sa["haul"]
    label = f"{label}, new plant {feed:,.0f} t/day"

    def settle(q):
        e = float(np.sum(q))
        self_heat = max(float(dem.sum()) - e, 0.0)  # hours the DC cannot cover: the plant burns its own gas
        rng_mwh = max(ch4 - self_heat / P["bio_boiler_eff"], 0.0)
        freed = max(rng_mwh - sa["rng"], 0.0)
        raw_sold = rng_mwh * 1000 / P["bio_ch4_kwh_nm3"] / P["bio_ch4_share"]
        up_extra = max(upgrade_capex(raw_sold / H, P) - sa["up_cap"], 0.0)
        up_elec = (raw_sold - sa["raw_nm3"]) * P["bio_upgrade_kwh_nm3"] / 1000 * site.x["p_elec_usd_mwh"]
        capex = up_extra + (pp["capex_usd"] if use_pipe else 0.0)
        return {"revenue_usd": freed * v_rng - up_elec - extra_haul, "co2_avoided_t": freed * ef, "capex_usd": capex,
                "detail": {**det, "case": "new plant", "feed_t_day": round(feed),
                           "logistics": "heat line" if use_pipe else "truck feedstock to DC",
                           "collection_radius_km": round(best["r_km"], 1),
                           "upgrade_capex_usd": round(up_extra), "digester_capex_usd": 0,
                           "plant_capex_usd": round(best["dig_cap"] + best["up_cap"]),
                           "upgrade_nm3_h": round(raw_sold / H, 1), "rng_value_usd_mwh": round(v_rng, 1),
                           "rng_sold_mwh": round(rng_mwh), "rng_freed_mwh": round(freed),
                           "plant_ch4_mwh": round(ch4), "heat_share_of_ch4": round(dem.sum() / ch4, 3),
                           "extra_trucking_usd_yr": round(extra_haul),
                           "plant_npv_usd": round(best["npv"]), "standalone_npv_usd": round(sa["npv"]),
                           "size_curve": curve, "feedstock": site.x.get("bio_name")}}

    return SinkPlan(name, label, t_supply, dem, loss, aux, settle=settle,
                    notes=[f"new plant sized {feed:,.0f} t/day by NPV (anchor {P['bio_feed_t_day']:.0f} t/day, "
                           f"collection radius {best['r_km']:.0f} km, ASSUMPTIONS), "
                           f"{'heat line' if use_pipe else 'feedstock trucked'} {d / 1000:.1f} km"])
