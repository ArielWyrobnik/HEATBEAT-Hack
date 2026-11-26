"""Tornado sensitivity of one chain: swing each parameter (and key site inputs) low/high.

Parameters come from `params.PARAMS` (their literature or assumption ranges). Site inputs are
swung by +/- 30 % (prices, distances, heat density) because their own uncertainty is not quantified.
Each bar is re-simulated against a baseline that is re-simulated with the same swing, so the bar is
the change of the chain's advantage over the counterfactual, not of the absolute cost.
"""
from __future__ import annotations

import copy
import dataclasses

import pandas as pd

from .chains import build_plans, simulate, add_deltas
from .params import PARAMS, defaults

SITE_SWINGS = {
    "p_elec_usd_mwh": "Electricity price", "p_water_usd_m3": "Water + sewer tariff",
    "p_heat_usd_mwh": "Gas heat price (heat sale value)", "rin_usd_mmbtu": "D3 RIN value",
    "rho_heat_mwh_m": "Linear heat density", "d_dh_m": "Distance to community",
    "d_bio_m": "Distance to feedstock", "it_mw": "IT load",
}
# parameters that matter for most chains; the rest are swung only if `all_params`
CORE = ["capex_factor", "discount_rate", "lifetime_yr", "hp_carnot_fraction", "dry_approach_k", "tower_approach_k",
        "adiabatic_eff", "sfp_dry_kw_kw", "tower_cycles", "chiller_carnot_fraction", "water_scarcity_usd_m3_per_wsi",
        "dh_supply_c", "dh_heat_price_share", "dh_u_a_w_mk", "capex_hp_usd_kw", "capex_dist_network_usd_m",
        "bio_feed_t_day", "bio_wall_u_w_m2k", "ads_cop", "orc_carnot_fraction", "fw_kwh_e_per_kwh_th",
        "med_dt_per_effect_k"]


def _run(site, P, tech, uses, storage, metric):
    plans = build_plans(site, P)
    b = simulate(site, P, site.baseline_rejection, (), None, plans=plans)
    add_deltas(b, b, P)
    r = simulate(site, P, tech, uses, storage, plans=plans, baseline=b)
    if r.get("ko"):
        return None
    return r[metric]


def tornado(site, tech: str, uses: tuple, storage=None, metric: str = "npv_usd", all_params: bool = False,
            P: dict | None = None, top: int = 12) -> pd.DataFrame:
    P0 = {**defaults(), **(P or {})}
    base = _run(site, P0, tech, uses, storage, metric)
    rows = []
    for k in (PARAMS if all_params else CORE):
        p = PARAMS[k]
        if p.low == p.high:
            continue
        vals = []
        for v in (p.low, p.high):
            vals.append(_run(site, {**P0, k: v}, tech, uses, storage, metric))
        rows.append({"input": k, "label": k, "kind": "parameter", "status": p.status, "unit": p.unit,
                     "base_value": P0[k], "low_value": p.low, "high_value": p.high,
                     "metric_low": vals[0], "metric_high": vals[1]})
    for k, label in SITE_SWINGS.items():
        vals = []
        b0 = site.it_mw if k == "it_mw" else site.x.get(k)
        if not b0:
            continue
        for f in (0.7, 1.3):
            s2 = copy.copy(site)
            s2.x = dict(site.x)
            if k == "it_mw":
                s2.it_mw = site.it_mw * f
                s2.loops = [dataclasses.replace(l, q_mw=l.q_mw * f) for l in site.loops]
            else:
                s2.x[k] = b0 * f
            vals.append(_run(s2, P0, tech, uses, storage, metric))
        rows.append({"input": k, "label": label, "kind": "site input", "status": site.prov.get(k, {}).get("status", "data"),
                     "unit": "", "base_value": b0, "low_value": b0 * 0.7, "high_value": b0 * 1.3,
                     "metric_low": vals[0], "metric_high": vals[1]})
    df = pd.DataFrame(rows)
    df["metric_low"] = df["metric_low"].fillna(base)  # a swing that makes the chain KO keeps the base (flag below)
    df["metric_high"] = df["metric_high"].fillna(base)
    df["swing"] = (df["metric_high"] - df["metric_low"]).abs()
    df = df[df["swing"] > 0].sort_values("swing", ascending=False).head(top).reset_index(drop=True)
    df.attrs.update(metric=metric, base=base)
    return df
