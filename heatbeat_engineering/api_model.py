"""Adapter: the engineering heat chain model behind the HEATBEAT API model interface.

`heatbeat_api.models.load_models()` imports `MODEL` from here when this module exists. The API and
its schema live in `heatbeat_api/` (API thread); this file only converts our results into
`heatbeat_api.schemas.ModelResult`. Nothing in `heatbeat_engineering` itself depends on the API.
"""
from __future__ import annotations

import math

from heatbeat_api.schemas import (Baseline, BudgetSummary, EnergyFlow, HeatLoop, InputValue, Kpis, ModelInfo,
                                  ModelResult, OptionResult, PlanDefaults, SetupFact, Tornado, TornadoBar)

from . import calc_trace
from .chains import DH_SIZED_PLANS, best_per_use, evaluate_site
from .params import PARAMS, defaults
from .sensitivity import tornado as tornado_fn
from .site import load_location, load_site, set_input
from .verdict import verdict as verdict_fn

UNITS = {
    "p_elec_usd_mwh": "USD/MWh", "ci_grid_kg_mwh": "kg CO2/MWh", "p_heat_usd_mwh": "USD/MWh_th",
    "p_gas_usd_mwh": "USD/MWh", "rin_usd_mmbtu": "USD/MMBtu", "lcfs_usd_t": "USD/t", "p_co2_usd_t": "USD/t",
    "p_water_usd_m3": "USD/m3", "wsi": "0 to 5", "d_dh_m": "m", "rho_heat_mwh_m": "MWh/m/yr", "d_coast_m": "m",
    "d_pp_m": "m", "q_fw_mw": "MW", "d_bio_m": "m", "geo_storage_score": "1 to 5", "p_wholesale_usd_mwh": "USD/MWh",
    "it_mw": "MW",
}
LABELS = {
    "p_elec_usd_mwh": "Electricity price (retail)", "ci_grid_kg_mwh": "Grid carbon intensity",
    "p_heat_usd_mwh": "Gas heat cost (customers)", "p_gas_usd_mwh": "Gas price (citygate)",
    "rin_usd_mmbtu": "D3 RIN value for RNG", "lcfs_usd_t": "LCFS credit", "p_co2_usd_t": "Carbon price",
    "p_water_usd_m3": "Water + sewer tariff", "wsi": "Water stress (Aqueduct)", "d_dh_m": "Distance to community",
    "rho_heat_mwh_m": "Linear heat density", "d_coast_m": "Distance to coast", "d_pp_m": "Distance to power plant",
    "q_fw_mw": "Power plant feedwater heat", "d_bio_m": "Distance to digester feedstock",
    "geo_storage_score": "Geological storage score", "p_wholesale_usd_mwh": "Wholesale power price",
    "is_greenfield": "Greenfield site", "it_mw": "IT load",
    "liquid_heat_share": "Liquid cooling heat share", "t_liquid_supply_c": "Liquid supply temperature",
    "t_liquid_return_c": "Liquid return temperature",
}
FLAG = {"data": "real", "estimate": "estimated", "assumption": "estimated", "synthetic": "synthetic", "user": "user"}


def _c(v):
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _split(overrides: dict | None):
    site_o, par_o = {}, {}
    for k, v in (overrides or {}).items():
        (par_o if k in PARAMS else site_o)[k] = v
    return site_o, {k: float(v) for k, v in par_o.items()}


class HeatChainModel:
    info = ModelInfo(
        name="heat_chain", label="Engineering heat chain", modes=["best", "reuse_only"], default_mode="best",
        description="Hourly component physics (dry / adiabatic / tower heat rejection with trim chiller, Carnot "
                    "fraction heat pumps, district heating pipes, storage, digester heating, feedwater, MED/MD, ORC, "
                    "adsorption chilling). Every chain is compared with the site's existing cooling. "
                    "'reuse_only' hides chains that only change the heat rejection.", default=True)

    WARNINGS = [
        "CAPEX values are screening level (+/- 40 %) and partly unverified team assumptions; see docs/ENGINEERING.md.",
        "Data center loads, cooling types and coolant temperatures are mostly team estimates (low confidence).",
        "Biogas uses a reference digester (300 t/day); feedstock quantity per site is not in the data.",
    ]

    def site_inputs(self, site_id, is_greenfield=None, overrides=None):
        site_o, par_o = _split(overrides)
        s = load_site(site_id, is_greenfield=is_greenfield, overrides=site_o)
        return self._inputs_list(s, par_o)

    def _inputs_list(self, s, par_o):
        out = []
        for k, v in {**s.x, "it_mw": s.it_mw}.items():
            if isinstance(v, str) or v is None:
                continue
            p = s.prov.get(k, {})
            out.append(InputValue(key=k, label=LABELS.get(k, k), value=_c(v), unit=UNITS.get(k),
                                  flag=FLAG.get(p.get("status"), "estimated"), status=str(p.get("status", "assumption")),
                                  source=p.get("source")))
        liq = next((l for l in s.loops if l.name == "liquid"), None)
        liq_share = round((liq.q_mw / s.it_mw), 4) if (liq and s.it_mw > 0) else 0.0
        loop_prov = s.prov.get("loops", {})
        loop_flag = FLAG.get(loop_prov.get("status"), "estimated")
        for k, val, unit in (
            ("liquid_heat_share", liq_share, "-"),
            ("t_liquid_supply_c", liq.t_supply_c if liq else 45.0, "C"),
            ("t_liquid_return_c", liq.t_return_c if liq else 55.0, "C"),
        ):
            out.append(InputValue(key=k, label=LABELS.get(k, k), value=_c(val), unit=unit,
                                  flag=loop_flag, status=str(loop_prov.get("status", "estimate")),
                                  source=loop_prov.get("source")))
        P = {**defaults(), **par_o}
        for k, p in PARAMS.items():
            out.append(InputValue(key=k, label=k, value=P[k], unit=p.unit,
                                  flag="user" if k in par_o else ("real" if p.status == "physics" else "estimated"),
                                  status="user" if k in par_o else p.status, source=p.source,
                                  sens_low=p.low, sens_high=p.high))
        return out

    def plan_defaults(self, lat: float, lon: float) -> PlanDefaults:
        """Return pre-filled regional estimates and Vera Rubin defaults for a planned point (no simulation)."""
        s = load_location(lat, lon, 100.0, "dlc_hot", True, weather=None, live=False)
        return PlanDefaults(
            lat=lat,
            lon=lon,
            template_site_id=str(s.x.get("template_site_id") or ""),
            template_km=round(float(s.x.get("template_distance_m", 0.0)) / 1000.0, 1),
            inputs=self._inputs_list(s, {}),
        )

    def run(self, site_id, mode="best", is_greenfield=None, overrides=None, weather=None, tornado=True):
        site_o, par_o = _split(overrides)
        s = load_site(site_id, weather=weather, is_greenfield=is_greenfield, overrides=site_o)
        return self._result(s, mode, par_o, tornado)

    def plan(self, req, weather=None, template_site_id=None, template_km=None):
        """Planned data center: any point + size (or total budget). `req` is heatbeat_api.schemas.PlanRequest."""
        site_o, par_o = _split(getattr(req, "overrides", None))
        is_gf = bool(getattr(req, "is_greenfield", 1) if getattr(req, "is_greenfield", 1) is not None else 1)
        prof = getattr(req, "cooling_profile", None) or "dlc_hot"
        budget_usd = getattr(req, "budget_usd", None)
        mode = getattr(req, "mode", None) or "best"
        tornado = getattr(req, "tornado", True)

        if budget_usd is None:
            s = load_location(req.lat, req.lon, req.it_mw, prof, is_gf,
                              weather=weather, live=weather is None, overrides=site_o)
            if getattr(req, "name", None):
                s.name = req.name
            return self._result(s, mode, par_o, tornado, planned=True)

        P0 = defaults()
        P = {**P0, **par_o}
        compute_usd_mw = P["compute_capex_usd_mw"]
        facility_usd_mw = par_o["facility_capex_usd_mw"] if "facility_capex_usd_mw" in par_o else (
            P0["facility_capex_usd_mw"] if is_gf else 0.0
        )
        rack_kw = max(P["vera_rubin_rack_kw"], 1.0)
        base_per_mw = compute_usd_mw + facility_usd_mw
        if base_per_mw <= 0:
            raise ValueError("compute_capex_usd_mw + facility_capex_usd_mw must be positive")
        if budget_usd < 0.1 * base_per_mw:
            raise ValueError(
                f"Budget ${budget_usd:,.0f} is too small for minimum 0.1 MW Vera Rubin deployment "
                f"(~${0.1 * base_per_mw:,.0f} compute + facility)."
            )

        it_guess = max(0.1, min(10000.0, budget_usd / (base_per_mw + 150_000.0)))
        s = load_location(req.lat, req.lon, it_guess, prof, is_gf,
                          weather=weather, live=weather is None, overrides=site_o)
        if getattr(req, "name", None):
            s.name = req.name

        # Solve IT MW iteratively accounting for fixed vs. MW-scaled cooling/heat-reuse plant CAPEX.
        def _solve_next_mw(it_cur: float) -> tuple[float, dict | None]:
            df, _, results = evaluate_site(s, P)
            if not len(df):
                return it_cur, None
            anchor_cid = next((cid for cid in df["chain_id"] if results[cid]["capex_usd"] <= budget_usd * 0.6),
                              df["chain_id"].iloc[0])
            r_anchor = results[anchor_cid]
            var_capex = sum(r_anchor["capex"].get(k, 0.0) for k in ("heat_rejection", "heat_pump", "heat_exchangers"))
            fixed_capex = max(0.0, r_anchor["capex_usd"] - var_capex)
            var_per_mw = var_capex / max(it_cur, 1e-6)
            nxt = (budget_usd - fixed_capex) / (base_per_mw + var_per_mw)
            clamped = max(0.1, min(10000.0, nxt))
            return math.floor(clamped * 100) / 100, r_anchor

        it_solved, _ = _solve_next_mw(it_guess)
        set_input(s, "it_mw", it_solved)
        it_refined, r_check = _solve_next_mw(it_solved)
        if abs(it_refined - it_solved) > max(0.05, 0.005 * it_solved):
            it_solved = it_refined
            set_input(s, "it_mw", it_solved)

        s.prov["it_mw"] = {"status": "user", "source": f"solved from ${budget_usd:,.0f} build budget"}
        res = self._result(s, mode, par_o, tornado, planned=True)

        anchor_opt = None
        for o in res.options:
            if not o.feasible:
                continue
            plant_capex = float(sum(o.details.get("capex_breakdown_usd", {}).values()))
            var_capex = float(sum(o.details.get("capex_breakdown_usd", {}).get(k, 0.0)
                                  for k in ("heat_rejection", "heat_pump", "heat_exchangers")))
            fixed_capex = max(0.0, plant_capex - var_capex)
            var_per_mw = var_capex / max(it_solved, 1e-6)
            opt_max_mw = max(0.0, (budget_usd - fixed_capex) / (base_per_mw + var_per_mw))
            total_cost = it_solved * base_per_mw + plant_capex
            o.details["budget_fit"] = {
                "budget_usd": budget_usd,
                "compute_capex_usd": round(it_solved * compute_usd_mw),
                "facility_capex_usd": round(it_solved * facility_usd_mw),
                "cooling_reuse_capex_usd": round(plant_capex),
                "total_build_capex_usd": round(total_cost),
                "fits_budget": total_cost <= budget_usd * 1.01,
                "max_it_mw_for_budget": round(opt_max_mw, 2),
                "max_vera_rubin_racks": int(opt_max_mw * 1000 // rack_kw),
            }
            if anchor_opt is None and o.details["budget_fit"]["fits_budget"]:
                anchor_opt = o
        if anchor_opt is None:
            anchor_opt = next((o for o in res.options if o.feasible), None)

        anchor_plant = float(sum(anchor_opt.details.get("capex_breakdown_usd", {}).values())) if anchor_opt else 0.0
        res.budget_summary = BudgetSummary(
            budget_usd=float(budget_usd),
            solved_it_mw=float(it_solved),
            vera_rubin_racks=int(it_solved * 1000 // rack_kw),
            rack_kw=float(rack_kw),
            compute_capex_usd=float(round(it_solved * compute_usd_mw)),
            facility_capex_usd=float(round(it_solved * facility_usd_mw)),
            cooling_reuse_capex_usd=float(round(anchor_plant)),
            total_build_capex_usd=float(round(it_solved * base_per_mw + anchor_plant)),
            compute_usd_per_mw=float(compute_usd_mw),
            facility_usd_per_mw=float(facility_usd_mw),
        )
        res.warnings.insert(
            0,
            f"Budget sizing assumes ${compute_usd_mw / 1e6:.1f}M/MW for Vera Rubin ({rack_kw:.0f} kW/rack) hardware "
            f"and ${facility_usd_mw / 1e6:.1f}M/MW for facility shell & power (editable under parameters).",
        )
        return res

    def _result(self, s, mode, par_o, tornado, planned=False):
        if mode not in self.info.modes:
            raise ValueError(f"mode must be one of {self.info.modes}")
        site_id = s.site_id
        P = {**defaults(), **par_o}
        df, base, results = evaluate_site(s, P)
        if mode == "reuse_only":
            df = df[df["uses"] != "none"].reset_index(drop=True)
        pick = [*df["chain_id"].head(10), *best_per_use(df)["chain_id"], *df.loc[df["uses"] == "none", "chain_id"]]
        # Every objective sees all simulated chains before the response is shortlisted.
        by_heat = sorted((cid for cid in df["chain_id"] if results[cid]["heat_recovered_mwh"] > 0),
                         key=lambda cid: results[cid]["heat_recovered_mwh"], reverse=True)
        by_reuse_npv = sorted(by_heat, key=lambda cid: results[cid]["reuse_npv_usd"], reverse=True)
        by_profitable_heat = [cid for cid in by_heat
                              if results[cid]["reuse_npv_usd"] > 0 and results[cid]["npv_usd"] > 0]
        for objective in (by_heat, by_reuse_npv, by_profitable_heat):
            pick.extend(objective[:3])
        if planned:
            # Keep standalone designs for every use and every heat rejection technology.
            # A high-ranking combined chain should not hide its standalone alternatives.
            standalone = df[~df["uses"].str.contains("+", regex=False)]
            standalone = standalone.drop_duplicates(["uses", "tech", "storage"])
            pick.extend(standalone.loc[~standalone["uses"].isin(DH_SIZED_PLANS), "chain_id"])
            for objective in (by_heat, by_reuse_npv, by_profitable_heat, df["chain_id"]):
                best_by_use = {}
                for cid in objective:
                    chain = results[cid]
                    for use in (*chain["uses"], chain["storage"]):
                        if use:
                            best_by_use.setdefault(use, cid)
                pick.extend(best_by_use.values())
        rank = {cid: i + 1 for i, cid in enumerate(df["chain_id"])}
        options = []
        for cid in sorted(set(pick), key=lambda c: rank[c]):
            r = results[cid]
            options.append(self._option(cid, r, rank[cid], base, s, P, planned=planned))
        for name, why in df.attrs.get("ko", {}).items():
            options.append(OptionResult(option_id=f"ko:{name}", name=name, rank=None, feasible=False, ko_reasons=[why]))
        torn = None
        if tornado and len(df):
            top = results[df["chain_id"].iloc[0]]
            t = tornado_fn(s, top["tech"], top["uses"], top["storage"], P=P)
            torn = Tornado(option_id=df["chain_id"].iloc[0], metric="npv_usd", unit="USD", base=float(t.attrs["base"]),
                           bars=[TornadoBar(input=b.input, label=b.label, low_value=float(b.low_value),
                                            high_value=float(b.high_value), metric_low=float(b.metric_low),
                                            metric_high=float(b.metric_high),
                                            flag="real" if b.status in ("data", "physics") else "estimated")
                                 for b in t.itertuples()])
        bl = Baseline(it_load_mw=s.it_mw, it_energy_mwh_yr=base["it_mwh"],
                      facility_energy_mwh_yr=base["it_mwh"] + base["cooling_mwh"] + base["other_mwh"],
                      heat_rejected_mwh_yr=base["heat_rejected_mwh"], pue=base["pue"], wue_l_kwh=base["wue_l_kwh"],
                      water_use_m3_yr=base["water_m3"], co2_t_yr=base["co2_t"] + (base["it_mwh"] + base["other_mwh"]) * s.x["ci_grid_kg_mwh"] / 1000,
                      electricity_cost_usd_yr=(base["it_mwh"] + base["cooling_mwh"] + base["other_mwh"]) * s.x["p_elec_usd_mwh"],
                      cooling_type=f"{s.cooling_profile} ({s.baseline_rejection})")
        bfields = getattr(Baseline, "model_fields", {})
        if "current_setup" in bfields:
            rp = s.prov.get("baseline_rejection", {})
            bl.cooling_profile = s.cooling_profile
            bl.heat_rejection = s.baseline_rejection
            bl.heat_rejection_flag = FLAG.get(rp.get("status"), "estimated")
            bl.heat_rejection_source = rp.get("source")
            bl.setup_status = setup_status(s)
            bl.current_setup = [SetupFact(field=k, **{a: b for a, b in v.items() if a in SetupFact.model_fields})
                                for k, v in s.setup.items()]
        warnings = list(self.WARNINGS)
        if not planned and s.prov.get("baseline_rejection", {}).get("status") == "assumption":
            warnings.append(f"Today's heat rejection at this site is not documented publicly; the baseline assumes "
                            f"{s.baseline_rejection} (typical for {s.cooling_profile}). Set it under 'Current setup' "
                            "if you know better.")
        if abs(base["pue"] - s.pue_reported) > 0.1:
            warnings.append(f"Modelled baseline PUE {base['pue']:.2f} differs from the profile value {s.pue_reported:.2f}; "
                            "the model counts cooling, hall fans and a fixed overhead only.")
        if s.prov.get("weather", {}).get("status") == "synthetic":
            warnings.append(s.prov["weather"]["source"])
        extra = {}
        fields = getattr(ModelResult, "model_fields", {})
        if "verdict" in fields and mode != "reuse_only":
            v = verdict_fn(df, base, s, planned=planned)
            extra["verdict"], extra["verdict_level"] = v["text"], v["level"]
        if planned and "inputs" in fields:
            extra["inputs"] = self._inputs_list(s, par_o)
        if planned and "planned_site" in fields:
            extra["planned_site"] = {"name": s.name, "it_mw": s.it_mw, "cooling_profile": s.cooling_profile,
                                     "template_site_id": s.x.get("template_site_id"),
                                     "template_km": round(s.x.get("template_distance_m", 0) / 1000, 1)}
        return ModelResult(site_id=site_id, model=self.info.name, mode=mode, model_version="0.1",
                           score_scale="NPV vs baseline, million USD", baseline=bl, options=options, tornado=torn,
                           warnings=warnings,
                           inputs_used={k: _c(v) for k, v in {**s.x, "it_mw": s.it_mw}.items()}, **extra)

    def _option(self, cid, r, rank, base, s, P, *, planned=False):
        k = Kpis(heat_recovered_mwh_yr=r["heat_recovered_mwh"], heat_delivered_mwh_yr=r["heat_delivered_mwh"],
                 electricity_used_mwh_yr=r["plant_mwh"], electricity_saved_mwh_yr=r["electricity_saved_mwh_yr"],
                 co2_avoided_t_yr=r["co2_avoided_t_yr"], water_saved_m3_yr=r["water_saved_m3_yr"],
                 net_value_usd_yr=r["net_value_usd_yr"], cash_value_usd_yr=r["cash_value_usd_yr"],
                 water_value_usd_yr=r["water_value_usd_yr"], capex_usd=r["delta_capex_usd"], payback_yr=_c(r["payback_yr"]),
                 pue_baseline=base["pue"], pue_with=r["pue"], wue_baseline_l_kwh=base["wue_l_kwh"],
                 wue_with_l_kwh=r["wue_l_kwh"], ere=r["ere"], cop=_c(r["cop_hp"]))
        prod = []
        if r["heat_delivered_mwh"] > 0:
            prod.append(f"{r['heat_delivered_mwh']:,.0f} MWh heat")
        if r["cold_delivered_mwh"] > 0:
            prod.append(f"{r['cold_delivered_mwh']:,.0f} MWh cold")
        if r["water_produced_m3"] > 0:
            prod.append(f"{r['water_produced_m3']:,.0f} m3 water")
        if r["elec_generated_mwh"] > 0:
            prod.append(f"{r['elec_generated_mwh']:,.0f} MWh electricity")
        if r.get("elec_exported_mwh", 0) > 0:
            prod.append(f"{r['elec_exported_mwh']:,.0f} MWh extra power plant output")
        flows = [EnergyFlow(**f) for f in r["flows"]]
        extra = {}
        fields = getattr(OptionResult, "model_fields", {})
        capex_bd = {a: round(b) for a, b in r["capex"].items() if b}
        if "implementation" in fields:
            extra["implementation"] = implementation(r, s, P)
        if "already_in_place" in fields:
            extra["already_in_place"] = already_in_place(r, s)
        if "calculation" in fields:
            extra["calculation"] = calc_trace.build(r, base, s, P, LABELS, UNITS)
            keep = set(calc_trace.relevant_params(r, s.baseline_rejection))
            extra["calculation_inputs"] = [i for i in self._inputs_list(s, {k: v for k, v in P.items() if k in PARAMS
                                                                             and v != PARAMS[k].value})
                                           if i.key not in PARAMS or i.key in keep]
        if "capex_breakdown" in fields:
            # breakdown of the chain CAPEX minus what the baseline itself would cost (greenfield cooling plant)
            bd = dict(capex_bd)
            base_cap = base["capex_usd"]
            if base_cap:
                bd["baseline cooling plant (not needed in this chain)"] = -round(base_cap)
            extra["capex_breakdown"] = bd
        name = r["label"]
        today = r["tech"] == s.baseline_rejection and not r["uses"] and not r["storage"]
        if today:
            name += " (reference design)" if planned else " (today's setup, no change)"
        if "is_today" in fields:
            extra["is_today"] = today and not planned
        return OptionResult(**extra, option_id=cid, name=name, rank=rank, feasible=True,
                            score=round(r["npv_usd"] / 1e6, 2), components=r["components"],
                            reuse_npv_usd=r["reuse_npv_usd"] if r["uses"] else None,
                            product=", ".join(prod) or "cooling only", kpis=k, energy_balance=flows,
                            heat_loops=[HeatLoop(**loop) for loop in r["heat_loops"]],
                            details={"capex_breakdown_usd": {a: round(b) for a, b in r["capex"].items()},
                                     "cost_usd_yr": {a: round(b) for a, b in r["cost"].items()},
                                     "npv_usd": r["npv_usd"], "reuse_npv_usd": r.get("reuse_npv_usd"),
                                     "balance_residual_mwh": r["balance_residual_mwh"],
                                     "chiller_hours": r["chiller_hours"], "wet_hours": r["wet_hours"],
                                     **{a: b for a, b in r.get("details", {}).items()}})


def setup_status(s) -> str | None:
    """verified / partial / context / None, same rule as heatbeat_data.verification_status."""
    from .site import SITE_SCOPES
    if not s.setup:
        return None
    if s.prov.get("baseline_rejection", {}).get("status") == "data":
        return "verified"
    site_facts = [v for v in s.setup.values() if v.get("scope") in SITE_SCOPES and v.get("confidence") in ("high", "medium")]
    return "partial" if site_facts else "context"


_USE_FAMILY = {"dh": "dh", "biogas": "biogas", "desal": "desal", "feedwater": "feedwater", "orc": "orc",
               "adsorption": "adsorption"}


def already_in_place(r: dict, s) -> list[str]:
    """Parts of a chain the site already has today (from the verified setup or a UI override)."""
    from .chains import TECH_LABEL
    out = []
    rp = s.prov.get("baseline_rejection", {})
    if r["tech"] == s.baseline_rejection and rp.get("status") in ("data", "user"):
        src = "set by you" if rp["status"] == "user" else (s.setup.get("heat_rejection", {}).get("source_title")
                                                            or rp.get("source", ""))
        out.append(f"{TECH_LABEL[r['tech']]} is what the site already uses ({src})"
                   + (": no change to the heat rejection, only the heat use is new." if r["uses"] else
                      ": this is today's setup, nothing to improve."))
    have = set(s.already)
    for u in r["uses"]:
        fam = next((f for k, f in _USE_FAMILY.items() if u.startswith(k)), u)
        if u in have or fam in have:
            f = s.setup.get("already_implemented", {})
            out.append(f"{u}: already in place at this site ({f.get('source_title') or 'current setup'}).")
    if r.get("storage") and r["storage"] in have:
        out.append(f"{r['storage']} storage: already in place at this site.")
    return out


def implementation(r: dict, s, P: dict) -> str:
    """Plain text: how the chain is built at this site, with the sizing the model computed."""
    from .chains import TECH_LABEL
    loops = ", ".join(f"{l.name} loop {l.q_mw:,.0f} MW at {l.t_return_c:.0f}/{l.t_supply_c:.0f} C" for l in s.loops)
    parts = [f"Heat source: {loops}.",
             f"Heat rejection: {TECH_LABEL[r['tech']].lower()} sized for the full load "
             f"({sum(l.q_mw for l in s.loops):,.0f} MW); trim chiller needed in {r['chiller_hours']:,} h/yr"
             + (f", wetted {r['wet_hours']:,} h/yr" if r["wet_hours"] else "") + "."]
    if r["tech"] == "wind" and "wind_radiator" in r.get("details", {}):
        w = r["details"]["wind_radiator"]
        parts.append(f"Wind radiator: {w['face_area_m2']:,} m2 of flat finned panels turned face-on to the wind, ahead of "
                     f"the dry coolers; {w['passive_share']:.0%} of the heat leaves with no fan power, "
                     f"{w['hours_fully_passive']:,} h/yr fully passive (2024 hourly wind at 10 m). The dry coolers stay as "
                     "backup for calm hours. Panel cost, coil and array losses are UNVERIFIED team assumptions.")
    if r["hp_peak_mw"] > 0:
        parts.append(f"Heat pump: {r['hp_peak_mw']:,.1f} MW_th output, seasonal COP {r['cop_hp']:.1f}, "
                     f"{r['hp_work_mwh']:,.0f} MWh_e/yr.")
    d = r.get("details", {})
    for u in r["uses"]:
        x = d.get(u, {})
        if u.startswith("dh_"):
            distance_note = ""
            if s.prov.get("d_dh_m", {}).get("lower_bound"):
                distance_note = (
                    " The GIS search found no qualifying heat-demand area or mapped network within its search limits. "
                    "The model uses the distance lower bound to price this screening scenario."
                )
            sizing_note = ""
            if x.get("peak_share", 100) < 100:
                sizing_note = (f" The reuse equipment is sized for {x['peak_share']}% of the community peak. "
                               "Other heat sources cover the remaining demand.")
            parts.append(f"District heating: DN{x.get('dn_mm')} twin transmission line {s.x['d_dh_m'] / 1000:.1f} km "
                         f"(U' {x.get('pipe_u_w_mk')} W/mK, {x.get('pipe_loss_mw', 0) * 1000:.0f} kW loss, pumps "
                         f"{x.get('pump_design_kw')} kW), {P['dh_supply_c']:.0f}/{P['dh_return_c']:.0f} C, community "
                         f"network demand {x.get('community_demand_mwh', 0):,} MWh/yr, peak {x.get('peak_mw')} MW, "
                         f"{x.get('served_share', 0) * 100:.0f} % served. Heat sold at "
                         f"{s.x['p_heat_usd_mwh'] * P['dh_heat_price_share']:.0f} USD/MWh "
                         f"({P['dh_heat_price_share'] * 100:.0f} % of local gas heat cost)." + distance_note + sizing_note)
        elif u.startswith("biogas"):
            parts.append(f"Digester heating: {x.get('volume_m3', 0):,} m3 digester (D {x.get('diameter_m')} m), "
                         f"{x.get('delivered_mwh', 0):,} MWh/yr heat ({x.get('feed_mwh', 0):,} feed, {x.get('wall_mwh', 0):,} walls), "
                         f"{x.get('logistics')}; frees {x.get('rng_freed_mwh', 0):,} MWh RNG at {x.get('rng_value_usd_mwh')} USD/MWh "
                         f"(feedstock: {x.get('feedstock')}).")
        elif u == "feedwater":
            parts.append(f"Feedwater preheat at {s.x.get('pp_name')}: DN{x.get('dn_mm')} line {s.x['d_pp_m'] / 1000:.1f} km, "
                         f"{x.get('delivered_mwh', 0):,} MWh/yr, +{x.get('extra_turbine_mwh_e', 0):,} MWh_e turbine output.")
        elif u.startswith("desal"):
            parts.append(f"Desalination {u[6:].upper()}: {x.get('effects')} effects, GOR {x.get('gor')}, "
                         f"{x.get('kwh_th_m3')} kWh_th/m3, up to {x.get('m3_day_peak', 0):,} m3/day.")
        elif u == "orc":
            parts.append(f"ORC: mean efficiency {x.get('eta_mean', 0) * 100:.1f} % (max {x.get('eta_max', 0) * 100:.1f} %).")
        elif u == "adsorption":
            parts.append(f"Adsorption chiller: {x.get('cold_mwh', 0):,} MWh/yr cold from {x.get('drive_mwh', 0):,} MWh "
                         f"drive heat, runs {x.get('hours_running', 0):,} h/yr (recooling must stay below "
                         f"{P['ads_max_cond_c']:.0f} C).")
    if r["storage"]:
        st = d.get("storage", {})
        parts.append(f"Storage ({r['storage']}): {st.get('capacity_mwh', 0):,} MWh capacity, shifts "
                     f"{st.get('shifted_mwh', 0):,} MWh/yr, loses {st.get('loss_mwh', 0):,} MWh/yr.")
    return " ".join(parts)


MODEL = HeatChainModel()
