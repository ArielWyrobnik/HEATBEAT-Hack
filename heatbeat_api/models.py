"""Model interface and registry.

A model is any object with `info`, `site_inputs()` and `run()` (see `SiteModel`). The API never
imports a model's internals, it only calls these three. To plug in a new model:

    # heatbeat_engineering/api_model.py
    from heatbeat_api.models import SiteModel
    from heatbeat_api.schemas import ModelInfo, ModelResult
    class HeatChainModel:
        info = ModelInfo(name="heat_chain", label="Engineering heat chain", modes=["default"],
                         default_mode="default", description="...", default=True)
        def site_inputs(self, site_id, is_greenfield=None, overrides=None): ...
        def run(self, site_id, mode, is_greenfield=None, overrides=None, weather=None, tornado=True): ...
    MODEL = HeatChainModel()

`load_models()` picks up `heatbeat_engineering.api_model.MODEL` automatically when that module
exists. The model with `info.default=True` (else the first one) answers requests without `?model=`.
"""
from __future__ import annotations

import importlib
import math
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from .schemas import (Baseline, CoolingProfile, EnergyFlow, Flag, InputValue, Kpis, ModelInfo, ModelResult,
                      OptionResult, PlanRequest, Tornado, TornadoBar)

# Modules that may provide a model as `<module>.MODEL`. Missing modules are skipped.
PLUGIN_MODULES = ["heatbeat_engineering.api_model"]


@runtime_checkable
class SiteModel(Protocol):
    info: ModelInfo

    def site_inputs(self, site_id: str, is_greenfield: int | None = None,
                    overrides: dict | None = None) -> list[InputValue]:
        """Every input the model uses for this site, with value, unit, flag and source."""

    def run(self, site_id: str, mode: str, is_greenfield: int | None = None, overrides: dict | None = None,
            weather: pd.DataFrame | None = None, tornado: bool = True) -> ModelResult:
        """Evaluate the site. `weather` (hourly frame like `heatbeat_data.Site.weather`, UTC index)
        replaces the site weather."""

    # Optional: plan(req: PlanRequest, weather: pd.DataFrame, template_site_id: str, template_km: float)
    #   -> ModelResult. A future data center at req.lat/req.lon with req.it_mw and req.cooling_profile.
    # The API passes the hourly weather of that point and the nearest database site (regional prices).


# ---------------------------------------------------------------- helpers shared by models

UNITS = [("_usd_kwh", "USD/kWh"), ("_usd_mwh", "USD/MWh"), ("_usd_m3", "USD/m3"), ("_usd_ton", "USD/t"),
         ("_g_kwh", "g CO2/kWh"), ("_mwh_m", "MWh/m/yr"), ("_l_kwh", "L/kWh"), ("_m2", "m2"), ("_mw", "MW"),
         ("_deg", "deg"), ("_c", "C"), ("_m", "m")]


LABELS = {
    "is_greenfield": "Greenfield site", "cooling_type": "Cooling type", "t_dc_base_c": "Waste heat temperature",
    "q_dc_mw": "Recoverable heat", "slope_deg": "Terrain slope", "flat_land_m2": "Flat land nearby",
    "d_water_m": "Distance to water body", "wsi_index": "Water stress (Aqueduct)",
    "has_existing_dh": "Existing district heating", "d_dh_m": "Distance to heat demand",
    "rho_heat_mwh_m": "Heat demand density", "d_coast_m": "Distance to coast", "dz_m": "Height above intake",
    "d_bio_m": "Distance to biomass", "d_co2_m": "Distance to CO2 storage", "d_pp_m": "Distance to power plant",
    "q_fw_mw": "Feedwater heat demand", "ind_zoning": "Industrial zoning", "campus_area_m2": "Campus area",
    "agri_land_m2": "Farmland nearby", "geo_storage_score": "Geological storage score",
    "p_elec_usd_kwh": "Electricity price", "p_fuel_usd_kwh": "Gas price (heat)", "p_steam_usd_mwh": "Steam price",
    "p_water_usd_m3": "Water price", "p_co2_usd_ton": "Carbon price", "p_dac_credit_usd_ton": "DAC credit (45Q)",
    "d_market_m": "Distance to food market", "ci_grid_g_kwh": "Grid carbon intensity",
    "ci_fuel_g_kwh": "Fuel carbon intensity", "eco_sens_index": "Ecological sensitivity",
    "mit_tier": "Mitigation tier", "pue": "PUE (baseline)", "wue_l_kwh": "WUE (baseline)",
    "baseline_cooling_evaporative": "Evaporative cooling (baseline)",
}


def unit_for(key: str) -> str | None:
    for suffix, unit in UNITS:
        if key.endswith(suffix):
            return unit
    return None


def flag_for(status: str | None, source: str | None) -> Flag:
    """Map a model's raw provenance status to the four UI flags."""
    st, src = str(status or "").lower(), str(source or "").lower()
    if st == "user":
        return "user"
    if "synthetic" in st or "synthetic" in src:
        return "synthetic"
    if st == "data" and not any(w in src for w in ("estimate", "confidence low", "team factor", "proxy")):
        return "real"
    return "estimated"


def clean(v: Any) -> Any:
    """JSON safe scalar: NaN and inf become None, numpy types become Python types."""
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


COOLING_LABELS = {
    "air_chilled_legacy": "Air, chilled water (legacy)", "air_chilled_elevated": "Air, elevated chilled water",
    "air_economizer": "Air, economizer", "rear_door": "Rear door heat exchanger",
    "dlc_cold": "Direct liquid cooling, cold", "dlc_warm": "Direct liquid cooling, warm (GPU standard)",
    "dlc_hot": "Direct liquid cooling, hot", "tpu_dlc": "TPU liquid cooling", "immersion_1p": "Immersion, single phase",
}


def cooling_profiles() -> list[CoolingProfile]:
    """Cooling profiles a planned data center can choose (data_pipeline/cooling_profiles.csv).

    pue_typical = median pue_assumed of the database sites with that profile (team estimates).
    """
    import heatbeat_data as hd
    from heatbeat_ranking.inputs import _cooling_type
    cp = hd.cooling_profiles()
    pue = hd.site_heat_profiles().groupby("cooling_profile_id")["pue_assumed"].median()
    out = []
    for r in cp.to_dict("records"):
        pid = r["cooling_profile_id"]
        ct = _cooling_type(pid)
        t = clean(r.get("facility_return_temp_c"))
        if ct == "air" or t is None:
            t = t or clean(r.get("exhaust_air_temp_c"))
        out.append(CoolingProfile(cooling_profile_id=pid, label=COOLING_LABELS.get(pid, pid), cooling_type=ct,
                                  heat_temp_c=t, pue_typical=clean(pue.get(pid)),
                                  description=clean(r.get("description"))))
    return out


# Inputs a planned site takes from the nearest database site (they vary by state or grid region).
# Every other input is a US default. Distances must be measured for a real plan.
REGIONAL_KEYS = ["p_elec_usd_kwh", "ci_grid_g_kwh", "p_fuel_usd_kwh", "p_steam_usd_mwh", "p_water_usd_m3",
                 "p_co2_usd_ton", "p_dac_credit_usd_ton", "ci_fuel_g_kwh", "wsi_index", "geo_storage_score",
                 "eco_sens_index"]

# How each option of the Excel ranking would be built (team description for the UI, not a design).
IMPLEMENTATION = {
    "fish_farm": "Warm water loop from the cooling plant to recirculating aquaculture tanks next to the campus; heat pump only for the last few kelvin.",
    "district_heating": "Heat pump lifts the cooling return to 65 C and feeds an insulated pipe to the nearest heat network or dense neighbourhood.",
    "biogas": "Cooling water keeps an anaerobic digester at 37 C (mesophilic); substrate trucked in from farms or food plants nearby.",
    "absorption_cooling": "Hot water (85 C, heat pump) drives a LiBr absorption chiller that replaces electric chillers on site or next door.",
    "orc": "Organic Rankine cycle turns hot coolant into electricity; needs at least 80 C supply, so mainly hot liquid cooling.",
    "dac": "Heat pump delivers 90 C to the sorbent regeneration of a direct air capture plant; CO2 piped to storage.",
    "btes_ates": "Boreholes or an aquifer store summer heat seasonally and return it in winter (greenfield design).",
    "boiler_feedwater": "Heat exchanger preheats boiler feedwater of a nearby thermal power plant via a short pipe.",
    "desalination": "Low temperature multi effect distillation or membrane distillation produces fresh water from seawater.",
    "biomass": "Heat pump supplies 65 C air to dry wood chips or agricultural residue in an adjacent hall.",
    "drying": "Heat pump supplies 75 C air to an industrial dryer (food, timber, sludge) on an industrial plot.",
    "snow_melt": "Low temperature loop under roads and parking keeps the campus free of ice in winter.",
    "greenhouse": "Warm water heats a co-located greenhouse; CO2 enrichment and lighting can share the grid connection.",
}


def capex_breakdown(option_key: str, x: dict, q_del_peak_mw: float, hp_elec_mwh: float) -> dict[str, float]:
    """Split of heatbeat_ranking.engine._capex into cost items (same placeholder numbers, UNVERIFIED)."""
    from heatbeat_ranking.engine import CAPEX_USD_PER_KW_TH, CORRECTED, PIPE
    out = {"plant": CAPEX_USD_PER_KW_TH[option_key] * q_del_peak_mw * 1000}
    if hp_elec_mwh > 0:
        out["heat_pump"] = CORRECTED["hp_capex_usd_per_kw_th"]["value"] * q_del_peak_mw * 1000
    if option_key in PIPE:
        key, usd_m = PIPE[option_key]
        out["pipeline"] = float(x[key]) * usd_m
    return out


# ---------------------------------------------------------------- adapter for heatbeat_ranking

class ExcelRankingModel:
    """The ranking engine ported from the team Excel (`heatbeat_ranking`), behind the model interface."""

    info = ModelInfo(
        name="excel_ranking", label="Team Excel ranking", modes=["corrected", "excel"], default_mode="corrected",
        description="13 heat reuse options, knock-out gates, viability score 0 to 5, eco grade A to F. "
                    "'excel' reproduces Hack data.xlsx, 'corrected' fixes its energy balance (heatbeat_ranking/AUDIT.md).")

    WARNINGS = ["CAPEX per option is a placeholder (unverified), so payback is indicative only.",
                "The heat sink is not sized: MWh, tCO2 and USD are upper bounds."]

    def _inputs(self, site_id, is_greenfield, overrides):
        from heatbeat_ranking import site_inputs
        x, prov = site_inputs(site_id, is_greenfield=is_greenfield)
        for k, v in (overrides or {}).items():
            x[k] = v
            prov[k] = {"status": "user", "source": "set in the UI"}
        return x, prov

    def site_inputs(self, site_id, is_greenfield=None, overrides=None):
        x, prov = self._inputs(site_id, is_greenfield, overrides)
        return self._input_values(x, prov)

    def _input_values(self, x, prov):
        from heatbeat_ranking import INPUT_SPEC
        out = []
        for k, v in x.items():
            p = prov.get(k, {})
            spec = INPUT_SPEC.get(k)
            rng = spec[1] if spec else None
            out.append(InputValue(key=k, label=LABELS.get(k), value=clean(v), unit=unit_for(k),
                                  flag=flag_for(p.get("status"), p.get("source")), status=str(p.get("status")),
                                  source=p.get("source"), description=spec[2] if spec else None,
                                  sens_low=rng[0] if rng else None, sens_high=rng[1] if rng else None))
        return out

    def _t_amb(self, site_id, weather):
        import heatbeat_data as hd
        from heatbeat_ranking.climate import hourly_from_site, to_8760
        site = hd.get_site(site_id, live=weather is None)
        if weather is not None:
            return to_8760(weather["t_db_c"], site.tz)
        return hourly_from_site(site)

    def run(self, site_id, mode, is_greenfield=None, overrides=None, weather=None, tornado=True):
        x, prov = self._inputs(site_id, is_greenfield, overrides)
        return self._evaluate(site_id, x, prov, self._t_amb(site_id, weather), mode, tornado)

    def plan(self, req: PlanRequest, weather: pd.DataFrame, template_site_id: str, template_km: float) -> ModelResult:
        """Future data center: regional inputs from the nearest site, distances as US defaults."""
        import heatbeat_data as hd
        from heatbeat_ranking import CORRECTED, INPUT_SPEC
        from heatbeat_ranking.climate import to_8760
        from heatbeat_ranking.inputs import us_defaults
        cp = {c.cooling_profile_id: c for c in cooling_profiles()}
        if req.cooling_profile not in cp:
            raise ValueError(f"cooling_profile must be one of {sorted(cp)}")
        c = cp[req.cooling_profile]
        x = us_defaults()
        prov = {k: {"status": "assumption", "source": f"US default, not measured for this location. {INPUT_SPEC[k][2]}"}
                for k in x}
        tx, tprov = self._inputs(template_site_id, None, None)
        for k in REGIONAL_KEYS:
            x[k] = tx[k]
            prov[k] = {"status": "assumption", "source": f"from nearest database site {template_site_id} "
                                                         f"({template_km:.0f} km): {tprov[k].get('source')}"}
        planned_it_mw = req.it_mw if req.it_mw is not None else round(max(0.1, min(10000.0, (req.budget_usd or 0.0) / 35_000_000.0)), 2)
        user = {"is_greenfield": int(req.is_greenfield), "cooling_type": c.cooling_type,
                "q_dc_mw": round(planned_it_mw * CORRECTED["it_capture_factor"]["value"], 2)}
        if c.heat_temp_c is not None:
            user["t_dc_base_c"] = c.heat_temp_c
        for k, v in user.items():
            x[k] = v
            prov[k] = {"status": "user", "source": f"planned data center ({c.label}, {planned_it_mw:g} MW IT)"}
        if req.pue is not None:
            x["pue"] = req.pue
            prov["pue"] = {"status": "user", "source": "design PUE set in the UI"}
        elif c.pue_typical:
            x["pue"] = c.pue_typical
            prov["pue"] = {"status": "assumption", "source": f"median PUE of database sites with {c.label} (team estimates)"}
        if req.cooling_profile == "dlc_hot":
            x["baseline_cooling_evaporative"], x["wue_l_kwh"] = False, 0.2
        for k, v in (req.overrides or {}).items():
            x[k] = v
            prov[k] = {"status": "user", "source": "set in the UI"}
        tz = hd.get_site(template_site_id, live=False).tz
        res = self._evaluate(None, x, prov, to_8760(weather["t_db_c"], tz), req.mode or self.info.default_mode,
                             req.tornado)
        res.planned_site = req
        res.inputs = self._input_values(x, prov)
        res.warnings.insert(0, f"Planned site: power, gas and water prices, grid CO2 and water stress come from the "
                               f"nearest database site {template_site_id} ({template_km:.0f} km away). Distances to "
                               f"heat users, water and industry are US defaults until measured.")
        return res

    def _evaluate(self, site_id, x, prov, t, mode, tornado) -> ModelResult:
        from heatbeat_ranking import CORRECTED, evaluate
        from heatbeat_ranking import tornado as tornado_fn
        if mode not in self.info.modes:
            raise ValueError(f"mode must be one of {self.info.modes}")
        df = evaluate(x, t, mode)

        q = float(x["q_dc_mw"])
        it_mw = q / CORRECTED["it_capture_factor"]["value"]
        it_mwh = it_mw * 8760
        pue = float(x.get("pue", 1.4))
        wue = float(x.get("wue_l_kwh", 1.8))
        fac = it_mwh * pue
        baseline = Baseline(
            it_load_mw=round(it_mw, 2), it_energy_mwh_yr=it_mwh, facility_energy_mwh_yr=fac,
            heat_rejected_mwh_yr=fac, pue=pue, wue_l_kwh=wue, water_use_m3_yr=it_mwh * wue,
            co2_t_yr=fac * float(x["ci_grid_g_kwh"]) / 1000,
            electricity_cost_usd_yr=fac * float(x["p_elec_usd_kwh"]) * 1000, cooling_type=str(x["cooling_type"]))

        options = [self._option(r, mode, x, q) for r in df.to_dict("records")]
        tor = None
        best = next((o for o in options if o.feasible), None)
        if tornado and best is not None:
            td = tornado_fn(x, t, best.option_id, mode=mode)
            tor = Tornado(option_id=best.option_id, metric="net_value_usd_yr", unit="USD/yr",
                          base=float(td.attrs["base"]),
                          bars=[TornadoBar(input=r["input"], label=LABELS.get(r["input"]), low_value=r["low_value"],
                                           high_value=r["high_value"], metric_low=r["metric_low"],
                                           metric_high=r["metric_high"],
                                           flag=flag_for(prov.get(r["input"], {}).get("status"),
                                                         prov.get(r["input"], {}).get("source")))
                                for r in td.head(10).to_dict("records")])
        warnings = list(self.WARNINGS)
        if mode == "excel":
            warnings.insert(0, "Excel mode reproduces the team Excel including its known errors (AUDIT.md).")
        n_est = sum(flag_for(p.get("status"), p.get("source")) == "estimated" for p in prov.values())
        warnings.append(f"{n_est} of {len(prov)} inputs are estimates or defaults, not site data.")
        return ModelResult(site_id=site_id or "planned", model=self.info.name, mode=mode, baseline=baseline,
                           options=options, tornado=tor, warnings=warnings,
                           inputs_used={k: clean(v) for k, v in x.items()})

    @staticmethod
    def _option(r: dict, mode: str, x: dict, q: float) -> OptionResult:
        g = lambda k: clean(r.get(k))  # noqa: E731
        feasible = bool(r["ko_gate"]) and (r["viability_score"] or 0) > 0
        e, e_del, w = g("heat_rec_mwh") or 0.0, g("heat_delivered_mwh"), g("hp_elec_mwh") or 0.0
        flows = [EnergyFlow(source="Data center", target="Heat recovery", mwh_yr=e)]
        if w:
            flows.append(EnergyFlow(source="Grid", target="Heat pump", mwh_yr=w, kind="electricity"))
        flows.append(EnergyFlow(source="Heat recovery" if not w else "Heat pump", target=r["option"],
                                mwh_yr=e_del if e_del is not None else e))
        kpis = Kpis(heat_recovered_mwh_yr=e, heat_delivered_mwh_yr=e_del, electricity_used_mwh_yr=w,
                    co2_avoided_t_yr=g("co2_avoided_t"), water_saved_m3_yr=g("water_saved_m3"),
                    net_value_usd_yr=g("net_value_usd_yr"), capex_usd=g("capex_usd"), payback_yr=g("payback_yr"),
                    pue_baseline=g("pue_baseline"), pue_with=g("pue_with"), wue_baseline_l_kwh=g("wue_baseline_l_kwh"),
                    wue_with_l_kwh=g("wue_with_l_kwh"), ere=g("ere"),
                    cop=None if (g("weighted_cop") or 0) >= 99 else g("weighted_cop"),
                    capacity_factor=g("capacity_factor"))
        breakdown = {}
        if feasible and mode != "excel" and e > 0:
            breakdown = capex_breakdown(r["key"], x, q * (e_del or e) / e, w)
        details = {k: g(k) for k in ("build_mode", "t_sink_c", "p1_thermo", "p2_climate_geo", "p3_economics",
                                     "p4_utilization", "eco_score")}
        return OptionResult(
            option_id=r["key"], name=r["option"], rank=r["rank"] if isinstance(r["rank"], int) else None,
            feasible=feasible, score=g("viability_score"), eco_grade=g("eco_grade"), components=[r["key"]],
            product=g("product"), implementation=IMPLEMENTATION.get(r["key"]), capex_breakdown=breakdown, kpis=kpis, energy_balance=flows if feasible else [], details=details,
            ko_reasons=[] if feasible else [f"Fails the knock-out gate of '{r['option']}' "
                                            f"({r['build_mode']}), see docs/RANKING.md"])


# ---------------------------------------------------------------- registry

def load_models() -> dict[str, SiteModel]:
    models: dict[str, SiteModel] = {}
    for mod in PLUGIN_MODULES:
        try:
            m = importlib.import_module(mod).MODEL
        except (ImportError, AttributeError):
            continue
        models[m.info.name] = m
    rk = ExcelRankingModel()
    models[rk.info.name] = rk
    return models


def default_model(models: dict[str, SiteModel]) -> str:
    return next((n for n, m in models.items() if m.info.default), next(iter(models)))
