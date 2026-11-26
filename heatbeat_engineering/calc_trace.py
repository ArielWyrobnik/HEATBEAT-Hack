"""Step by step calculation trace of one heat chain, for the "Show calculation" view in the frontend.

Every step shows the formula, the numbers put into it (each with its flag and source) and the result.
The numbers are the ones `chains.simulate` and `chains.add_deltas` computed; this module only re-states
them, it does not recompute anything. Hourly terms (fans, chiller, heat pump, delivered heat) are sums
over the 8760 hours of the site's weather year.
"""
from __future__ import annotations

from .params import PARAMS
from .sinks import annuity

# parameter name prefixes that belong to each part of a chain
_USE_PREFIX = {
    "dh": ("dh_", "capex_pipe", "capex_dist"),
    "biogas": ("bio_", "rng_", "lcfs_"),
    "feedwater": ("fw_", "p_wholesale"),
    "desal": ("med_", "md_", "ro_", "sea_", "desal_", "capex_med", "capex_md"),
    "orc": ("orc_", "p_wholesale", "capex_orc"),
    "adsorption": ("ads_", "abs_", "capex_ads", "capex_abs"),
}
_TECH_PREFIX = {
    "dry": ("dry_", "sfp_dry", "capex_dry"),
    "adiabatic": ("adiabatic_", "sfp_adiabatic", "capex_adiabatic"),
    "tower": ("tower_", "sfp_tower", "capex_tower"),
    "wind": ("wind_", "capex_wind", "dry_", "sfp_dry", "capex_dry"),
}
_ALWAYS = ("cp_water", "h_fg", "rho_water", "chiller_", "pump_kw", "hall_fan", "other_overhead", "discount_rate",
           "lifetime_yr", "opex_share", "capex_factor", "water_scarcity", "ng_kg_co2")
_FLAG = {"data": "real", "physics": "real", "literature": "estimated", "estimate": "estimated",
         "assumption": "estimated", "synthetic": "synthetic", "user": "user"}


def relevant_params(r: dict, baseline_tech: str) -> list[str]:
    pre = list(_ALWAYS) + list(_TECH_PREFIX.get(r["tech"], ())) + list(_TECH_PREFIX.get(baseline_tech, ()))
    if r.get("hp_peak_mw", 0) > 0:
        pre += ["hp_", "capex_hp", "capex_hx", "hx_"]
    for u in r["uses"]:
        for k, v in _USE_PREFIX.items():
            if u.startswith(k):
                pre += v
    if r.get("storage"):
        pre += [r["storage"], "storage_", f"capex_{r['storage']}"]
    return [k for k in PARAMS if k.startswith(tuple(pre))]


def build(r: dict, b: dict, s, P: dict, labels: dict, units: dict) -> list[dict]:
    """List of CalcStep dicts for chain result `r` against baseline `b` at site `s` with parameters `P`."""
    x = s.x

    def site(k):
        p = s.prov.get(k, {})
        return {"key": k, "label": labels.get(k, k), "value": x.get(k), "unit": units.get(k),
                "flag": _FLAG.get(p.get("status"), "estimated"), "source": p.get("source")}

    def par(k):
        p = PARAMS[k]
        return {"key": k, "label": k, "value": P[k], "unit": p.unit,
                "flag": "user" if P[k] != p.value else _FLAG.get(p.status, "estimated"), "source": p.source}

    def calc(k, label, v, unit):
        return {"key": k, "label": label, "value": v, "unit": unit, "flag": None, "source": None}

    it = r["it_mwh"]
    steps = []
    steps.append({
        "title": "IT energy per year",
        "formula": "E_IT = IT load x 8760 h",
        "terms": [{"key": "it_mw", "label": "IT load", "value": s.it_mw, "unit": "MW",
                   "flag": _FLAG.get(s.prov.get("loops", {}).get("status"), "estimated"),
                   "source": s.prov.get("loops", {}).get("source")},
                  {"key": "hours", "label": "Hours per year", "value": 8760, "unit": "h", "flag": "real", "source": "Definition (365 days x 24 h)"}],
        "result": it, "unit": "MWh/yr",
        "note": "All heat from the IT load ends up in the cooling loops (energy balance input)."})
    steps.append({
        "title": "Cooling electricity, hour by hour",
        "formula": "E_cool = sum over 8760 h of (fans + pumps + trim chiller)",
        "terms": [calc("fan_mwh", "Fans", r["fan_mwh"], "MWh/yr"), calc("pump_mwh", "Pumps", r["pump_mwh"], "MWh/yr"),
                  calc("chiller_mwh", "Trim chiller", r["chiller_mwh"], "MWh/yr"),
                  calc("chiller_hours", "Hours the chiller runs", r["chiller_hours"], "h/yr"),
                  par(f"sfp_{'dry' if r['tech'] == 'wind' else r['tech']}_kw_kw"), par("pump_kw_kw"),
                  par("chiller_carnot_fraction"),
                  *([calc("passive_mwh", "Heat rejected by the wind radiator with no fans",
                          r["details"]["wind_radiator"]["passive_mwh"], "MWh/yr"),
                     par("wind_area_m2_per_mw"), par("wind_coil_k"), par("wind_ua_ref_kw_km2"),
                     par("wind_yaw_array_factor")] if r["tech"] == "wind" else [])],
        "result": r["cooling_mwh"], "unit": "MWh/yr",
        "note": f"Baseline ({s.baseline_rejection}): {b['cooling_mwh']:,.0f} MWh/yr. The chiller COP follows the "
                "hourly lift from the weather (Carnot fraction model)."})
    if r.get("plant_mwh", 0) > 0:
        steps.append({
            "title": "Electricity of the reuse plant",
            "formula": "E_plant = heat pump work + auxiliaries (pumps of pipes, desalination, ORC)",
            "terms": [calc("hp_work_mwh", "Heat pump work", r["hp_work_mwh"], "MWh/yr"),
                      calc("cop_hp", "Seasonal heat pump COP", r.get("cop_hp"), "-"),
                      *([par("hp_carnot_fraction")] if r.get("hp_peak_mw", 0) > 0 else [])],
            "result": r["plant_mwh"], "unit": "MWh/yr"})
    other = r["other_mwh"]
    steps.append({
        "title": "PUE with this solution",
        "formula": "PUE = (E_IT + E_cool + E_other) / E_IT",
        "terms": [calc("it_mwh", "E_IT", it, "MWh/yr"), calc("cooling_mwh", "E_cool", r["cooling_mwh"], "MWh/yr"),
                  calc("other_mwh", "E_other (hall fans, overhead)", other, "MWh/yr"),
                  par("other_overhead_share"), par("hall_fan_kw_kw")],
        "result": r["pue"], "unit": "-", "note": f"Baseline PUE {b['pue']:.3f}."})
    if r["heat_delivered_mwh"] > 0 or r.get("cold_delivered_mwh", 0) > 0:
        steps.append({
            "title": "Heat put to use",
            "formula": "Q_used = sum over 8760 h of heat delivered to the sinks, after pipe, network and storage losses",
            "terms": [calc("heat_recovered_mwh", "Heat taken from the IT loops", r["heat_recovered_mwh"], "MWh/yr"),
                      calc("hp_work_mwh", "Heat pump work added", r["hp_work_mwh"], "MWh/yr"),
                      calc("losses_mwh", "Losses", r["losses_mwh"], "MWh/yr"),
                      calc("cold_delivered_mwh", "Cold delivered (adsorption)", r.get("cold_delivered_mwh", 0), "MWh/yr")],
            "result": r["heat_delivered_mwh"], "unit": "MWh/yr",
            "note": "Each hour the sink takes at most its demand (community heat demand of the sink from heating degree hours, "
                    "digester, feedwater or desalination capacity); the rest goes to the heat rejection."})
    steps.append({
        "title": "ERE (energy reuse effectiveness)",
        "formula": "ERE = (E_IT + E_cool + E_other + E_plant - E_reused) / E_IT",
        "terms": [calc("facility", "E_IT + E_cool + E_other", it + r["cooling_mwh"] + other, "MWh/yr"),
                  calc("plant_mwh", "E_plant", r["plant_mwh"], "MWh/yr"),
                  calc("reused", "E_reused (heat delivered, ORC electricity)",
                       (it + r["cooling_mwh"] + other + r["plant_mwh"]) - r["ere"] * it, "MWh/yr")],
        "result": r["ere"], "unit": "-", "note": "ERE below PUE means energy leaves the site as a useful product."})
    steps.append({
        "title": "Energy balance check",
        "formula": "In (IT + heat pump work + chiller work) - Out (rejected + used + losses) = residual",
        "terms": [calc("balance_in_mwh", "Energy in", r["balance_in_mwh"], "MWh/yr"),
                  calc("balance_out_mwh", "Energy out", r["balance_out_mwh"], "MWh/yr")],
        "result": r["balance_residual_mwh"], "unit": "MWh/yr",
        "note": "Close to zero means no energy is created or lost in the model."})
    steps.append({
        "title": "Water use",
        "formula": "Water saved = W_baseline - W_solution (evaporation + blowdown of wet cooling)",
        "terms": [calc("water_base", "Baseline water", b["water_m3"], "m3/yr"),
                  calc("water_m3", "Water with solution", r["water_m3"], "m3/yr"),
                  calc("wet_hours", "Hours wetted", r["wet_hours"], "h/yr"), par("h_fg_mj_kg")],
        "result": r["water_saved_m3_yr"], "unit": "m3/yr", "note": f"WUE {b['wue_l_kwh']:.2f} to {r['wue_l_kwh']:.2f} L/kWh."})
    elec = r["cooling_mwh"] + r["plant_mwh"]
    co2_use = elec * x["ci_grid_kg_mwh"] / 1000 - r["co2_t"]
    steps.append({
        "title": "CO2 avoided",
        "formula": "CO2 = E_cool+plant x grid intensity / 1000 - CO2 avoided by the products; avoided = CO2_baseline - CO2",
        "terms": [calc("elec", "E_cool + E_plant", elec, "MWh/yr"), site("ci_grid_kg_mwh"),
                  calc("co2_products", "CO2 avoided by products (gas heat, RNG, water, power)", co2_use, "t/yr"),
                  calc("co2_base", "Baseline CO2 of cooling", b["co2_t"], "t/yr")],
        "result": r["co2_avoided_t_yr"], "unit": "t CO2/yr"})
    c, cb = r["cost"], b["cost"]
    names = {"electricity_usd": "Electricity", "water_usd": "Water and sewer", "water_scarcity_usd": "Water scarcity charge",
             "carbon_usd": "Carbon cost", "opex_usd": "Fixed O&M", "revenue_usd": "Revenue (negative = income)"}
    steps.append({
        "title": "Annual cost with this solution",
        "formula": "Cost = E x electricity price + W x (tariff + WSI x scarcity charge) + E x CI x carbon price "
                   "+ O&M share x CAPEX - revenue",
        "terms": [site("p_elec_usd_mwh"), site("p_water_usd_m3"), site("wsi"), site("p_co2_usd_t"),
                  par("water_scarcity_usd_m3_per_wsi"), par("opex_share"),
                  *[calc(k, names.get(k, k), v, "USD/yr") for k, v in c.items()]],
        "result": r["net_cost_usd"], "unit": "USD/yr",
        "note": "Baseline: " + ", ".join(f"{names.get(k, k)} {v:,.0f}" for k, v in cb.items() if v) +
                f" = {b['net_cost_usd']:,.0f} USD/yr."})
    steps.append({
        "title": "Net value per year",
        "formula": "Net value = cost_baseline - cost_solution",
        "terms": [calc("cost_base", "Baseline cost", b["net_cost_usd"], "USD/yr"),
                  calc("cost_sol", "Cost with solution", r["net_cost_usd"], "USD/yr")],
        "result": r["net_value_usd_yr"], "unit": "USD/yr",
        "note": f"Real money (bills, revenue, O&M): {r['cash_value_usd_yr']:,.0f} USD/yr. Water value from the scarcity "
                f"shadow price (not cash): {r['water_value_usd_yr']:,.0f} USD/yr."})
    steps.append({
        "title": "Extra investment (CAPEX)",
        "formula": "dCAPEX = sum of chain items x capex factor - baseline cooling plant",
        "terms": [*[calc(k, k.replace("_", " "), v, "USD") for k, v in r["capex"].items() if v],
                  calc("capex_base", "Baseline cooling plant", b["capex_usd"], "USD"), par("capex_factor")],
        "result": r["delta_capex_usd"], "unit": "USD",
        "note": "Screening level CAPEX (+/- 40 %), mostly unverified team assumptions."})
    a = annuity(P)
    steps.append({
        "title": "NPV and payback",
        "formula": "NPV = net value / annuity - dCAPEX, annuity = i / (1 - (1 + i)^-n); payback = dCAPEX / net value",
        "terms": [par("discount_rate"), par("lifetime_yr"), calc("annuity", "Annuity factor", a, "1/yr"),
                  calc("net_value", "Net value", r["net_value_usd_yr"], "USD/yr"),
                  calc("dcapex", "dCAPEX", r["delta_capex_usd"], "USD"),
                  calc("payback", "Payback", r["payback_yr"], "yr")],
        "result": r["npv_usd"], "unit": "USD", "note": "The ranking sorts chains by this NPV."})
    return steps
