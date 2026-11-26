"""DSX evaluator behind the heatbeat_api model interface (default model for site rankings).

Inputs: the same 31 site inputs as the Excel ranking (heatbeat_ranking.site_inputs: database,
GIS, industry, water, ecology and market threads, each with status and source), plus pue, wue,
baseline_cooling_evaporative and the 45Q DAC credit. Climate: the real hourly weather of the site
(Open-Meteo ERA5 2024, heatbeat_ranking.climate.hourly_from_site). Planned sites reuse the Excel
model's plan() (regional values from the nearest database site, the point's own weather).
"""
from __future__ import annotations

import math

import numpy as np

from heatbeat_api.models import LABELS, ExcelRankingModel, clean, flag_for
from heatbeat_api.schemas import (Baseline, CalcStep, CalcTerm, EnergyFlow, HeatLoop, HeatRoute, Kpis, ModelInfo,
                                  ModelResult, OptionResult, Tornado, TornadoBar)

from .engine import C, OPTIONS, VERSION, evaluate

# NPV convention shared with the engineering model (heatbeat_engineering/params.py, both assumptions)
DISCOUNT_RATE, LIFETIME_YR = 0.07, 20
ANNUITY = (1 - (1 + DISCOUNT_RATE) ** -LIFETIME_YR) / DISCOUNT_RATE
IT_CAPTURE = 0.9  # heatbeat_ranking: q_dc_mw = it_load_mw x 0.9

COMPONENTS = {
    "fish_farm_ras": ["fish_farm"], "district_heating": ["district_heating"], "biogas": ["biogas"],
    "absorption_cooling": ["absorption_cooling"], "orc": ["orc"], "dac": [], "btes_ates": ["btes_ates"],
    "feedwater_preheat": ["boiler_feedwater"], "desalination": ["desalination"], "biomass_processing": [],
    "industrial_drying": [], "snow_melt": [], "greenhouse": [],
}
IMPLEMENTATION = {
    "fish_farm_ras": "Warm water loop from the cooling plant to recirculating aquaculture tanks next to the campus; heat pump only for the last few kelvin.",
    "district_heating": "Heat pump lifts the cooling return to 65 C and feeds an insulated pipe to the nearest heat network or dense neighbourhood.",
    "biogas": "Cooling water keeps an anaerobic digester at 37 C (mesophilic); substrate from farms or food plants nearby.",
    "absorption_cooling": "Hot water (85 C, heat pump where needed) drives an absorption chiller that replaces electric chillers.",
    "orc": "Organic Rankine cycle turns hot coolant into electricity; needs at least 80 C all year, so only hot liquid cooling.",
    "dac": "Heat pump delivers 90 C to the sorbent regeneration of a direct air capture plant; CO2 piped to storage (45Q).",
    "btes_ates": "Boreholes or an aquifer store summer heat seasonally and return it in winter (designed in with a new build).",
    "feedwater_preheat": "Heat exchanger preheats boiler feedwater of a nearby thermal power plant via a short pipe.",
    "desalination": "Low temperature multi effect distillation or membrane distillation makes fresh water from seawater.",
    "biomass_processing": "Heat pump supplies 65 C air to dry wood chips or agricultural residue in an adjacent hall.",
    "industrial_drying": "Heat pump supplies 75 C air to an industrial dryer (food, timber, sludge) on an industrial plot.",
    "snow_melt": "Low temperature loop under roads and parking keeps the campus free of ice in winter.",
    "greenhouse": "Warm water heats a co-located greenhouse designed together with the data center.",
}
PRODUCT_TEXT = {"MWh_th": "MWh heat", "MWh_cool": "MWh cooling", "MWh_e": "MWh electricity", "m3": "m3 fresh water",
                "tCO2": "t CO2 captured"}
TORNADO_KEYS = ["p_fuel_usd_kwh", "p_elec_usd_kwh", "q_dc_mw", "t_dc_base_c", "ci_grid_g_kwh", "ci_fuel_g_kwh",
                "p_co2_usd_ton", "p_dac_credit_usd_ton", "p_water_usd_m3", "p_steam_usd_mwh", "d_dh_m", "d_bio_m",
                "d_water_m", "d_market_m", "rho_heat_mwh_m", "wsi_index"]


def _site(x: dict) -> dict:
    s = {k: (int(v) if isinstance(v, bool) else v) for k, v in x.items()}
    s["baseline_evaporative"] = 1 if x.get("baseline_cooling_evaporative", True) else 0
    s.setdefault("p_dac_credit_usd_ton", s.get("p_co2_usd_ton", 0))
    return s


class DsxModel(ExcelRankingModel):
    """DSX evaluator v3.3 on database inputs and real hourly weather."""

    info = ModelInfo(
        name="dsx", label="DSX heat reuse evaluator", modes=["as_built"], default_mode="as_built", default=True,
        description="13 heat reuse pathways on the site's real hourly weather. Knock-out gates name the site value "
                    "and the limit; viability 0 to 5 = 0.30 thermodynamics + 0.30 climate fit + 0.25 economics + "
                    "0.15 utilisation; separate eco grade A to F (0.40 CO2, 0.30 water, 0.30 local impact). docs/DSX.md")

    WARNINGS = ["Specific costs per kW and per m of pipe are generic planning values (DSX evaluator), so payback and "
                "NPV are indicative.",
                f"NPV over {LIFETIME_YR} years at {DISCOUNT_RATE:.0%} (same convention as the engineering model)."]

    # site_inputs(), run(), plan() and _t_amb() come from ExcelRankingModel; only the evaluation differs.

    def _evaluate(self, site_id, x, prov, t, mode, tornado) -> ModelResult:
        if mode not in self.info.modes:
            raise ValueError(f"mode must be one of {self.info.modes}")
        s = _site(x)
        res = evaluate(s, np.asarray(t, float))
        q = float(s["q_dc_mw"])
        it_mw = q / IT_CAPTURE
        it_mwh = it_mw * 8760
        pue = float(x.get("pue", 1.4))
        wue = float(x.get("wue_l_kwh", 1.8))
        fac = it_mwh * pue
        base = Baseline(
            it_load_mw=round(it_mw, 2), it_energy_mwh_yr=it_mwh, facility_energy_mwh_yr=fac, heat_rejected_mwh_yr=fac,
            pue=pue, wue_l_kwh=wue, water_use_m3_yr=it_mwh * wue if s["baseline_evaporative"] else 0.0,
            co2_t_yr=fac * float(s["ci_grid_g_kwh"]) / 1000,
            electricity_cost_usd_yr=fac * float(s["p_elec_usd_kwh"]) * 1000, cooling_type=str(s["cooling_type"]))
        options = [self._dsx_option(o, s, prov, base, res["climate_summary"]) for o in res["options"]]
        feas = [o for o in options if o.feasible]
        rank = 1
        for o in options:
            o.rank = rank if o.feasible else None
            rank += o.feasible
        tor = self._tornado(s, t, feas[0].option_id, prov) if tornado and feas else None
        warnings = list(self.WARNINGS)
        n_est = sum(flag_for(p.get("status"), p.get("source")) == "estimated" for p in prov.values())
        warnings.append(f"{n_est} of {len(prov)} inputs are estimates or defaults, not site data.")
        verdict, level = self._verdict(feas)
        return ModelResult(site_id=site_id or "planned", model=self.info.name, mode=mode, model_version=VERSION,
                           score_scale="viability 0 to 5", baseline=base, options=options, tornado=tor,
                           warnings=warnings, verdict=verdict, verdict_level=level,
                           inputs_used={k: clean(v) for k, v in x.items()})

    @staticmethod
    def _verdict(feas):
        if not feas:
            return "No heat reuse pathway passes the knock-out gates at this site.", "no_gain"
        b = feas[0]
        npv = b.details.get("npv_usd") or 0
        if npv > 0:
            return (f"{b.name} is the most viable heat reuse here (viability {b.score:.2f} of 5, eco grade "
                    f"{b.eco_grade}). Worth {npv / 1e6:.1f} M USD over {LIFETIME_YR} years."), "gain"
        return (f"{b.name} passes the gates (viability {b.score:.2f} of 5) but does not pay back at today's "
                f"prices."), "small_gain"

    def _dsx_option(self, o: dict, s: dict, prov: dict, base: Baseline, h: dict) -> OptionResult:
        a = o["annual"]
        feasible = o["ko_pass"] and o["viability"] > 0
        qs, qd, w = a["q_src_mwh"], a["q_del_mwh"], a["w_hp_mwh"]
        # water: heat sent to reuse no longer evaporates in the cooling tower (evaporative baseline only)
        saved = 0.0
        if s["baseline_evaporative"] and base.heat_rejected_mwh_yr:
            saved = base.water_use_m3_yr * min(1.0, qs / base.heat_rejected_mwh_yr)
        if a["product_unit"] == "m3":
            saved += a["product_qty"]
        net = a["net_annual_usd"]
        npv = -a["capex_usd"] + net * ANNUITY
        comps = list(COMPONENTS[o["key"]]) + (["heat_pump"] if w > 0 else [])
        flows = []
        if feasible:
            flows.append(EnergyFlow(source="Data center", target="Heat recovery", mwh_yr=qs))
            if w > 0:
                flows.append(EnergyFlow(source="Grid", target="Heat pump", mwh_yr=w, kind="electricity"))
                flows.append(EnergyFlow(source="Heat recovery", target="Heat pump", mwh_yr=qs))
            flows.append(EnergyFlow(source="Heat pump" if w > 0 else "Heat recovery", target=o["name"], mwh_yr=qd))
            flows.append(EnergyFlow(source="Data center", target="Cooling (rejected)",
                                    mwh_yr=max(0.0, base.it_energy_mwh_yr - qs), kind="loss"))
        # where the server heat goes (HeatFlow in the UI): all IT energy ends up as heat in the cooling
        # loop; the pathway takes Q_src of it, the cooling plant rejects the rest
        loops = []
        if feasible:
            server = base.it_energy_mwh_yr
            loops = [HeatLoop(name=str(s["cooling_type"]), mwh_yr=server, return_c=float(s["t_dc_base_c"]),
                              routes=[HeatRoute(name=o["name"], mwh_yr=min(qs, server), kind="reuse"),
                                      HeatRoute(name="Cooling plant (rejected to air)" if not s["baseline_evaporative"]
                                                else "Cooling plant (cooling tower)",
                                                mwh_yr=max(0.0, server - qs), kind="cooling")])]
        kpis = Kpis(heat_recovered_mwh_yr=qs, heat_delivered_mwh_yr=qd, electricity_used_mwh_yr=w,
                    co2_avoided_t_yr=a["net_abated_tco2"], water_saved_m3_yr=round(saved, 1), net_value_usd_yr=net,
                    cash_value_usd_yr=net, capex_usd=a["capex_usd"],
                    payback_yr=None if a["payback_yr"] is None else a["payback_yr"], pue_baseline=base.pue,
                    pue_with=base.pue, wue_baseline_l_kwh=base.wue_l_kwh,
                    wue_with_l_kwh=round(base.wue_l_kwh * (1 - min(1.0, qs / base.heat_rejected_mwh_yr)), 3)
                    if s["baseline_evaporative"] and base.heat_rejected_mwh_yr else base.wue_l_kwh,
                    ere=round((base.facility_energy_mwh_yr + w - (qd if a["product_unit"] != "MWh_e" else 0))
                              / base.it_energy_mwh_yr, 3) if base.it_energy_mwh_yr else None,
                    cop=a["mean_cop"], capacity_factor=a["utilisation"])
        details = {
            "build_mode": o["mode"], "t_sink_c": o["t_sink_c"], **o["subscores"], **o["eco_subscores"],
            "eco_score": o["eco_score"], "viability_ungated": o["viability_ungated"], "npv_usd": round(npv),
            "money_product_usd": a["value_usd"], "money_carbon_usd": a["carbon_rev_usd"],
            "money_hp_usd": a["hp_elec_cost_usd"], "money_om_usd": a["om_usd"], "money_net_usd": net,
            "capex_plant_usd": a["capex_plant_usd"], "capex_pipe_usd": a["capex_pipe_usd"],
            "capex_hp_usd": a["capex_hp_usd"], "energy_src_mwh": qs, "energy_hp_mwh": w, "energy_del_mwh": qd,
            "product": a["product_unit"],
        }
        breakdown = {k: v for k, v in (("plant", a["capex_plant_usd"]), ("pipeline", a["capex_pipe_usd"]),
                                       ("heat_pump", a["capex_hp_usd"])) if v}
        return OptionResult(
            option_id=o["key"], name=o["name"], feasible=feasible, score=o["viability"], reuse_npv_usd=round(npv),
            eco_grade=o["eco_grade"], components=comps,
            product=f"{a['product_qty']:,.0f} {PRODUCT_TEXT.get(a['product_unit'], a['product_unit'])} per year",
            ko_reasons=[] if feasible else (o["ko_failures"] or ["scores 0 at this site"]),
            implementation=IMPLEMENTATION.get(o["key"]), capex_breakdown=breakdown, kpis=kpis,
            energy_balance=flows, heat_loops=loops, details=details,
            calculation=self._steps(o, s, prov, h))

    @staticmethod
    def _term(s, prov, k):
        p = prov.get(k, {})
        return CalcTerm(key=k, label=LABELS.get(k, k), value=clean(s.get(k)), unit=None,
                        flag=flag_for(p.get("status"), p.get("source")), source=p.get("source"))

    def _steps(self, o, s, prov, h) -> list[CalcStep]:
        a, sc, e = o["annual"], o["subscores"], o["eco_subscores"]
        calc = lambda k, lab, v, u=None: CalcTerm(key=k, label=lab, value=clean(v), unit=u)  # noqa: E731
        t = lambda k: self._term(s, prov, k)  # noqa: E731
        opt = next(x for x in OPTIONS if x["key"] == o["key"])
        w, ew = C["weights"], C["eco_weights"]
        product_formula = {
            "MWh_th": "value = Q_del x heat price (gas boiler heat it replaces); CO2 avoided = Q_del x CI of that heat - W_hp x grid CI",
            "MWh_cool": "cooling = 0.70 x Q_del; chiller power saved = cooling / 5; value = saved x electricity price",
            "MWh_e": "electricity = Q_src x 0.45 x (1 - (T_amb + 10 + 273.15) / (T_dc + 273.15)); value = electricity x electricity price",
            "m3": "water = Q_del / 60 kWh_th per m3; value = water x water price; CO2 avoided = 3.5 kWh/m3 of reverse osmosis x grid CI",
            "tCO2": "CO2 captured = Q_del / 1.8 MWh_th per t; value = captured x 45Q credit",
        }
        return [
            CalcStep(title="Hourly weather and coolant temperature",
                     formula=f"T_amb = real hourly 2024 weather of the site (8760 h); T_dc = t_dc_base (liquid) or max(t_dc_base, T_amb + {C['air_offset_c']:g}) (air)",
                     terms=[t("cooling_type"), t("t_dc_base_c"), calc("mean_amb", "Mean ambient", round(h["mean_amb"], 1), "C"),
                            calc("tdc", "Coolant range", f"{h['min_tdc']:.0f} to {h['max_tdc']:.0f}", "C")],
                     result=round(h["mean_amb"], 1), unit="C mean"),
            CalcStep(title="Knock-out gates", formula="G = 1 only if every gate of this pathway holds",
                     terms=[t("is_greenfield"), calc("lt15", "Hours below 15 C", h["lt15"], "h"),
                            calc("gt30", "Hours above 30 C", h["gt30"], "h")]
                     + ([t(opt["dist_key"])] if opt["dist_key"] else []),
                     result=1 if o["ko_pass"] else 0, unit="pass" if o["ko_pass"] else "knocked out",
                     note="All gates hold." if o["ko_pass"] else "Fails: " + "; ".join(o["ko_failures"]) + "."),
            CalcStep(title="Heat drawn from the data center",
                     formula="Q_src = sum over 8760 h of q_dc x demand(T_amb) x size cap x 0.998 uptime",
                     terms=[t("q_dc_mw"), calc("cap", "Off-taker size cap", a["cap_fraction"]),
                            calc("util", "Share of site heat used", a["utilisation"])],
                     result=a["q_src_mwh"], unit="MWh/yr"),
            CalcStep(title="Power cycle" if o["key"] == "orc" else "Heat pump lift",
                     formula="eta = 0.45 x (1 - (T_amb + 10 + 273.15) / (T_dc + 273.15))" if o["key"] == "orc" else
                     f"direct exchange if T_dc >= T_sink + {C['approach_k']:g} K; else COP = min({C['cop_cap']:g}, "
                     f"{C['carnot_eta']:g} x (T_sink + 5 + 273.15) / lift), W_hp = Q_src / (COP - 1)",
                     terms=[calc("t_sink", "Sink temperature", o["t_sink_c"], "C"),
                            calc("cop", "Mean cycle efficiency" if o["key"] == "orc" else "Mean COP",
                                 a["orc_mean_eta"] if o["key"] == "orc" else (a["mean_cop"] or "direct")),
                            calc("direct_h", "Hours with direct exchange", a["direct_hx_hours"], "h")],
                     result=a["w_hp_mwh"], unit="MWh_e/yr heat pump"),
            CalcStep(title="Product, value and CO2", formula=product_formula[a["product_unit"]],
                     terms=[t("p_fuel_usd_kwh"), t("p_elec_usd_kwh"), t("ci_fuel_g_kwh"), t("ci_grid_g_kwh"),
                            t("p_co2_usd_ton"), calc("abated", "Net CO2 avoided", a["net_abated_tco2"], "t/yr")],
                     result=a["revenue_usd"], unit="USD/yr revenue"),
            CalcStep(title="Investment, payback and NPV",
                     formula=f"CAPEX = peak heat x {opt['capex_usd_kw']:g} $/kW + distance x {opt['pipe_usd_m']:g} $/m + heat pump x "
                             f"{C['hp_capex_usd_kw']:g} $/kW; net = revenue - heat pump power - 2 % CAPEX; payback = CAPEX / net; "
                             f"NPV = -CAPEX + net x {ANNUITY:.2f} ({LIFETIME_YR} yr at {DISCOUNT_RATE:.0%})",
                     terms=[calc("capex", "CAPEX", a["capex_usd"], "USD"), calc("hp", "Heat pump electricity", a["hp_elec_cost_usd"], "USD/yr"),
                            calc("net", "Net cash flow", a["net_annual_usd"], "USD/yr")],
                     result=a["payback_yr"], unit="years", note="Specific costs are generic planning values."),
            CalcStep(title="Viability score",
                     formula=f"viability = G x ({w['thermo']:.2f} P_thermo + {w['climate']:.2f} P_climate + {w['econ']:.2f} P_econ + "
                             f"{w['util']:.2f} P_util); P_thermo = 5 x free heat share (ORC: 5 x efficiency / 12 %); "
                             f"P_econ = 5 at 3 yr payback, 0 at 15 yr",
                     terms=[calc("p_thermo", "P thermo", sc["p_thermo"]), calc("p_climate", "P climate", sc["p_climate"]),
                            calc("p_econ", "P econ", sc["p_econ"]), calc("p_util", "P util", sc["p_util"])],
                     result=o["viability"], unit="of 5"),
            CalcStep(title="Eco grade (independent of viability)",
                     formula=f"E = {ew['ghg']:.2f} e_GHG + {ew['water']:.2f} e_water + {ew['local']:.2f} e_local; "
                             "A >= 4.2, B >= 3.4, C >= 2.6, D >= 1.8, else F",
                     terms=[calc("e_ghg", "e GHG", e["e_ghg"]), calc("e_water", "e water", e["e_water"]),
                            calc("e_local", "e local", e["e_local"]), t("wsi_index"), t("eco_sens_index"), t("mit_tier")],
                     result=o["eco_score"], unit=f"grade {o['eco_grade']}"),
        ]

    def _tornado(self, s, t, option_id, prov) -> Tornado | None:
        from heatbeat_ranking import INPUT_SPEC

        def net(site):
            r = evaluate(site, np.asarray(t, float))
            return next(o for o in r["options"] if o["key"] == option_id)["annual"]["net_annual_usd"]

        base = net(s)
        bars = []
        for k in TORNADO_KEYS:
            spec = INPUT_SPEC.get(k)
            if not spec or not spec[1] or k not in s:
                continue
            lo, hi = spec[1]
            ml, mh = net({**s, k: lo}), net({**s, k: hi})
            if ml == base and mh == base:
                continue
            p = prov.get(k, {})
            bars.append(TornadoBar(input=k, label=LABELS.get(k), low_value=lo, high_value=hi, metric_low=ml,
                                   metric_high=mh, flag=flag_for(p.get("status"), p.get("source"))))
        bars.sort(key=lambda b: -abs(b.metric_high - b.metric_low))
        return Tornado(option_id=option_id, metric="net_value_usd_yr", unit="USD/yr", base=float(base), bars=bars[:10])


MODEL = DsxModel()
