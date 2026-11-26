"""Ranking engine: KO gates, techno-economic viability score (0 to 5) and ecological grade (A to F).

`evaluate(inputs, t_amb, mode="excel")` reproduces the team Excel model "Hack data.xlsx"
(v3.0-SI-Diurnal-DualGrade) cell by cell. `mode="corrected"` applies the fixes listed in
`heatbeat_ranking/AUDIT.md` and adds the outputs the brief asks for (tCO2, m3, USD, payback,
PUE/WUE/ERE). Every coefficient that is not from the Excel lives in `CORRECTED` below with a flag.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

from .options import OPTIONS, gross_value_usd, heat_recovered_mw, ko_gate

MODES = ("excel", "corrected")

# Assumptions used only in corrected mode. status: "literature", "physics" or "assumption".
CORRECTED: dict[str, dict] = {
    "carnot_fraction": {"value": 0.5, "status": "assumption",
                        "note": "Same 50 % of Carnot as the Excel. Industrial heat pumps reach 40 to 60 %."},
    "hx_approach_k": {"value": 2.5, "status": "assumption",
                      "note": "Temperature approach per heat exchanger, added to the lift on both sides."},
    "cop_max": {"value": 8.0, "status": "assumption",
                "note": "Cap for small lifts; the Excel gives COP 33.8 for 60 C to 65 C."},
    "orc_carnot_fraction": {"value": 0.4, "status": "assumption",
                            "note": "Real low temperature ORC reach about 40 % of Carnot."},
    "orc_condenser_above_ambient_k": {"value": 10.0, "status": "assumption", "note": ""},
    "chiller_cop": {"value": 4.5, "status": "assumption", "note": "Electric chiller displaced, from the Excel."},
    "absorption_cop": {"value": 0.7, "status": "assumption", "note": "Single effect LiBr, from the Excel."},
    "ro_kwh_m3": {"value": 3.5, "status": "literature",
                  "note": "SWRO 3 to 4 kWh/m3, Al-Karaghouli and Kazmerski 2013 (catalogue source karaghouli_desal_2013)."},
    "dac_t_per_mwh_th": {"value": 0.556, "status": "assumption", "note": "From the Excel (1.8 MWh_th/t)."},
    "dac_mwh_e_per_t": {"value": 0.25, "status": "assumption", "note": "From the Excel."},
    "desal_m3_per_mwh_th": {"value": 15.38, "status": "assumption", "note": "From the Excel (65 kWh_th/m3)."},
    "evap_m3_per_mwh_th": {"value": 1.6, "status": "physics",
                           "note": "Water evaporated in a cooling tower per MWh rejected: 3600 MJ / 2.26 MJ/kg. "
                                   "Applies only when the baseline cooling is evaporative."},
    "cooling_aux_mwh_e_per_mwh_th": {"value": 0.03, "status": "assumption",
                                     "note": "Fan and pump electricity of the heat rejection plant that reuse avoids."},
    "it_capture_factor": {"value": 0.9, "status": "assumption", "note": "q_dc = IT load x 0.9 (Excel definition)."},
    "climate_intercept": {"value": 3.5, "status": "assumption",
                          "note": "Climate/geo score without the capacity factor term (2.5 + 2 x typical CF 0.5)."},
    "hp_capex_usd_per_kw_th": {"value": 700, "status": "assumption",
                               "note": "Midpoint of catalogue heat_pump_booster 400 to 1000 USD/kW_th (unverified)."},
}

# CAPEX per kW_th of peak recovered heat, excluding heat pump and pipeline. Screening only, UNVERIFIED.
# Derived from heatbeat_solutions/catalogue.yaml ranges where a conversion exists, else a team guess.
CAPEX_USD_PER_KW_TH = {
    "fish_farm": 1500, "district_heating": 300, "biogas": 1000, "absorption_cooling": 400,
    "orc": 350, "dac": 9700, "btes_ates": 800, "boiler_feedwater": 175, "desalination": 650,
    "biomass": 500, "drying": 600, "snow_melt": 400, "greenhouse": 800,
}
# Pipeline: (input key with the distance in m, USD per m). UNVERIFIED team assumption;
# district heating from catalogue district_heating_5gdh (1 to 3 M USD per km).
PIPE = {"district_heating": ("d_dh_m", 2000), "fish_farm": ("d_water_m", 500),
        "boiler_feedwater": ("d_pp_m", 1500), "desalination": ("d_coast_m", 800)}


def xround(x: float, nd: int = 0) -> float:
    """Excel ROUND (half away from zero), not Python's banker's rounding."""
    q = Decimal(1).scaleb(-nd)
    return float(Decimal(repr(x)).quantize(q, rounding=ROUND_HALF_UP))


def _band(v, cuts):
    """Score 5..1 from descending thresholds, like the Excel nested IFs."""
    for score, cut in zip((5, 4, 3, 2), cuts):
        if v >= cut:
            return score
    return 1


def _mit_base(x):
    return {"high": 5.0, "med": 3.5}.get(str(x["mit_tier"]), 2.0)


def grade(s):
    if s is None:
        return "N/A (KO)"
    return "A" if s >= 4.2 else "B" if s >= 3.4 else "C" if s >= 2.6 else "D" if s >= 1.8 else "F"


def t_dc_series(x: dict, t_amb: np.ndarray) -> np.ndarray:
    base = float(x["t_dc_base_c"])
    if x["cooling_type"] == "liquid":
        return np.full_like(t_amb, base, dtype=float)
    return np.maximum(base, t_amb + 12.0)


def _cop_excel(t_sink, t_dc):
    return 0.5 * (t_sink + 273.15) / (t_sink - t_dc)


def _hp_corrected(q_src, t_sink, t_dc):
    """Heat pump electricity and delivered heat. Energy balance: Q_delivered = Q_source + W."""
    c = {k: CORRECTED[k]["value"] for k in ("carnot_fraction", "hx_approach_k", "cop_max")}
    need = t_sink > t_dc
    lift = np.maximum(t_sink - t_dc + 2 * c["hx_approach_k"], 1.0)
    cop = np.minimum(c["cop_max"], c["carnot_fraction"] * (t_sink + c["hx_approach_k"] + 273.15) / lift)
    cop = np.maximum(cop, 1.05)
    w = np.where(need, q_src / (cop - 1), 0.0)
    return w, q_src + w


def evaluate(x: dict, t_amb: np.ndarray, mode: str = "excel") -> pd.DataFrame:
    """Score all 13 options for one site. Returns one row per option, ranked."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    t_amb = np.asarray(t_amb, float)
    if len(t_amb) != 8760:
        raise ValueError("t_amb must have 8760 hourly values")
    t_dc = t_dc_series(x, t_amb)
    q = float(x["q_dc_mw"])
    rows = []
    for o in OPTIONS:
        q_src = heat_recovered_mw(o.key, t_amb, x)
        if mode == "excel":
            if o.uses_heat_pump:
                with np.errstate(divide="ignore", invalid="ignore"):
                    w = np.where(o.t_sink_c <= t_dc, 0.0, q_src / _cop_excel(o.t_sink_c, t_dc))
            else:
                w = np.zeros_like(q_src)
            q_del = q_src
        else:
            if o.key == "orc":
                w, q_del = np.zeros_like(q_src), q_src
            else:
                w, q_del = _hp_corrected(q_src, o.t_sink_c, t_dc)
        e, f, e_del = float(q_src.sum()), float(w.sum()), float(q_del.sum())
        r = _score(o, x, t_amb, t_dc, q, e, f, e_del, mode)
        rows.append(r)
    df = pd.DataFrame(rows)
    df.attrs.update(mode=mode, t_amb_mean_c=float(t_amb.mean()), t_dc_min_c=float(t_dc.min()))
    sc = df["viability_score"].to_numpy()
    if mode == "excel":
        # Excel: IF(O=0,"KO",RANK(O,O5:O17)), descending, ties share a rank
        df.insert(0, "rank", [("KO" if s == 0 else int(1 + (sc > s).sum())) for s in sc])
        return df.sort_values("viability_score", ascending=False, kind="stable").reset_index(drop=True)
    # corrected: the banded score ties often, so break ties with the net annual value (AUDIT.md finding 9)
    df = df.sort_values(["viability_score", "net_value_usd_yr"], ascending=False, kind="stable")
    n_ok = int((df["viability_score"] > 0).sum())
    df.insert(0, "rank", list(range(1, n_ok + 1)) + ["KO"] * (len(df) - n_ok))
    return df.reset_index(drop=True)


def _score(o, x, t_amb, t_dc, q, e, f, e_del, mode):
    c = {k: v["value"] for k, v in CORRECTED.items()}
    pe = float(x["p_elec_usd_kwh"]) * 1000  # USD/MWh
    ci_grid, ci_fuel = float(x["ci_grid_g_kwh"]), float(x["ci_fuel_g_kwh"])
    cf = e / (q * 8760)
    cop = 99.0 if f == 0 else e / f
    gate = bool(ko_gate(o.key, x, t_amb, t_dc))

    p1 = _band(cop, (20, 5.5, 3.5, 2.5))
    wsi, slope = float(x["wsi_index"]), float(x["slope_deg"])
    if mode == "excel":
        p2 = min(5, max(1, xround(2.5 + 2 * cf - 0.3 * (wsi - 2) - 0.05 * slope)))
        gross = gross_value_usd(o.key, e, x)
        net = gross - (0 if o.key == "orc" else f * pe)
        ghg_g_kwh = (e * ci_fuel - f * ci_grid) / max(1, e)
        extra = {}
    else:
        # capacity factor only in P4, not also in P2 (AUDIT.md finding 3)
        p2 = min(5, max(1, xround(c["climate_intercept"] - 0.3 * (wsi - 2) - 0.05 * slope)))
        gross, avoided_t, water_m3, product, orc_el = _corrected_value(o, x, t_amb, t_dc, e, e_del, c)
        cop = 99.0 if f == 0 else e_del / f  # heating COP = delivered heat / electricity
        p1 = _band(cop, (20, 5.5, 3.5, 2.5))
        net = gross - f * pe
        # baseline: the DC would have rejected the source heat in its own cooling plant
        aux_saved_mwh = c["cooling_aux_mwh_e_per_mwh_th"] * e
        net += aux_saved_mwh * pe
        avoided_t += (aux_saved_mwh - f) * ci_grid / 1000  # MWh * g/kWh / 1000 = t
        net += avoided_t * float(x.get("p_co2_usd_ton", 0) if o.key != "dac" else 0)
        evap = x.get("baseline_cooling_evaporative", True)
        rejected_extra = e - orc_el if o.key == "orc" else 0.0  # ORC condenser still rejects heat
        if o.key == "absorption_cooling":
            # absorber rejects drive heat + cooling load; electric chiller would reject cooling x (1 + 1/COP)
            cool = c["absorption_cop"] * e_del
            rejected_extra = e_del + cool - cool * (1 + 1 / c["chiller_cop"])
        water_m3 += (c["evap_m3_per_mwh_th"] * (e - rejected_extra)) if evap else 0.0
        ghg_g_kwh = avoided_t * 1000 / max(1, e)  # t / MWh * 1000 = kg/MWh = g/kWh
        capex = _capex(o, x, q_del_peak=(q * e_del / e) if e > 0 else 0.0, f=f)
        it_mwh = q / c["it_capture_factor"] * 8760
        pue = float(x.get("pue", 1.3))
        wue = float(x.get("wue_l_kwh", 1.8 if evap else 0.2))
        extra = {
            "heat_delivered_mwh": e_del, "product": product,
            "co2_avoided_t": avoided_t, "water_saved_m3": water_m3,
            "capex_usd": capex, "payback_yr": (capex / net) if net > 0 else math.inf,
            "pue_baseline": pue, "pue_with": pue - c["cooling_aux_mwh_e_per_mwh_th"] * e / it_mwh,
            "ere": (pue * it_mwh - e) / it_mwh,
            "wue_baseline_l_kwh": wue, "wue_with_l_kwh": wue - water_m3 * 1000 / (it_mwh * 1000),
        }
    net_per = net / (q * 8760)
    p3 = _band(net_per, (45, 30, 18, 8))
    p4 = _band(cf, (0.9, 0.75, 0.55, 0.35))
    score = 0.0 if not gate else xround(0.35 * p1 + 0.3 * p2 + 0.25 * p3 + 0.1 * p4, 2)

    eg = _band(ghg_g_kwh, (220, 150, 80, 0))
    base = _mit_base(x)
    ew = min(5, max(1, base - (wsi * 0.6 if o.name == "Absorption Cooling" else wsi * 0.15)))
    el = min(5, max(1, base - (float(x["eco_sens_index"]) - 1) * 0.45))
    es = xround(0.4 * eg + 0.3 * ew + 0.3 * el, 2) if gate else None
    return {
        "option": o.name, "key": o.key, "build_mode": o.build_mode, "t_sink_c": o.t_sink_c,
        "heat_rec_mwh": e, "hp_elec_mwh": f, "capacity_factor": cf, "weighted_cop": cop,
        "ko_gate": int(gate), "p1_thermo": p1, "p2_climate_geo": p2,
        "net_value_usd_mwh_dc": net_per, "net_value_usd_yr": net, "p3_economics": p3,
        "p4_utilization": p4, "viability_score": score, "eco_ghg": eg, "eco_water": ew,
        "eco_local": el, "eco_score": es, "eco_grade": grade(es), **extra,
    }


def _corrected_value(o, x, t_amb, t_dc, e, e_del, c):
    """Gross value (USD/yr), avoided tCO2 (excluding HP and cooling aux), water m3, product text
    and ORC net electricity (MWh, 0 for other options).

    Each option gets its own counterfactual instead of always "displaces heating fuel".
    """
    pe = float(x["p_elec_usd_kwh"]) * 1000
    ci_grid, ci_fuel = float(x["ci_grid_g_kwh"]), float(x["ci_fuel_g_kwh"])
    match o.output:
        case "cooling":
            cool = c["absorption_cop"] * e_del
            elec = cool / c["chiller_cop"]
            return elec * pe, elec * ci_grid / 1000, 0.0, f"{cool:,.0f} MWh cooling", 0.0
        case "electricity":
            q_src = heat_recovered_mw(o.key, t_amb, x)
            t_hot = t_dc + 273.15
            t_cold = t_amb + c["orc_condenser_above_ambient_k"] + 273.15
            eta = np.clip(c["orc_carnot_fraction"] * (1 - t_cold / t_hot), 0, None)
            el = float((q_src * eta).sum())
            return el * pe, el * ci_grid / 1000, 0.0, f"{el:,.0f} MWh electricity", el
        case "co2_removal":
            t = c["dac_t_per_mwh_th"] * e_del
            el = c["dac_mwh_e_per_t"] * t
            credit = float(x.get("p_dac_credit_usd_ton", x["p_co2_usd_ton"]))
            return t * credit - el * pe, t - el * ci_grid / 1000, 0.0, f"{t:,.0f} t CO2 captured", 0.0
        case "water":
            m3 = c["desal_m3_per_mwh_th"] * e_del
            # counterfactual: the same water from seawater RO
            ro = m3 * c["ro_kwh_m3"] / 1000
            return m3 * float(x["p_water_usd_m3"]), ro * ci_grid / 1000, m3, f"{m3:,.0f} m3 fresh water", 0.0
    # heat products keep the Excel price factors but are paid on delivered heat (source + HP work)
    return (gross_value_usd(o.key, e_del, x), e_del * ci_fuel / 1000, 0.0,
            f"{e_del:,.0f} MWh heat at {o.t_sink_c:.0f} C", 0.0)


def _capex(o, x, q_del_peak, f):
    cap = CAPEX_USD_PER_KW_TH[o.key] * q_del_peak * 1000
    if f > 0:
        cap += CORRECTED["hp_capex_usd_per_kw_th"]["value"] * q_del_peak * 1000
    if o.key in PIPE:
        key, usd_m = PIPE[o.key]
        cap += float(x[key]) * usd_m
    return cap
