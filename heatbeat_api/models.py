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

from .schemas import (Baseline, EnergyFlow, Flag, InputValue, Kpis, ModelInfo, ModelResult, OptionResult,
                      Tornado, TornadoBar)

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
        replaces the site weather, used for custom coordinates."""


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
        from heatbeat_ranking import INPUT_SPEC
        x, prov = self._inputs(site_id, is_greenfield, overrides)
        out = []
        for k, v in x.items():
            p = prov.get(k, {})
            spec = INPUT_SPEC.get(k)
            rng = spec[1] if spec else None
            out.append(InputValue(key=k, label=LABELS.get(k), value=clean(v), unit=unit_for(k), flag=flag_for(p.get("status"), p.get("source")),
                                  status=str(p.get("status")), source=p.get("source"),
                                  description=spec[2] if spec else None,
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
        from heatbeat_ranking import CORRECTED, evaluate
        from heatbeat_ranking import tornado as tornado_fn
        if mode not in self.info.modes:
            raise ValueError(f"mode must be one of {self.info.modes}")
        x, prov = self._inputs(site_id, is_greenfield, overrides)
        t = self._t_amb(site_id, weather)
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

        options = [self._option(r, mode) for r in df.to_dict("records")]
        tor = None
        best = next((o for o in options if o.feasible), None)
        if tornado and best is not None:
            td = tornado_fn(x, t, best.option_id, mode=mode)
            tor = Tornado(option_id=best.option_id, metric="net_value_usd_yr", unit="USD/yr",
                          base=float(td.attrs["base"]),
                          bars=[TornadoBar(input=r["input"], label=LABELS.get(r["input"]), low_value=r["low_value"], high_value=r["high_value"],
                                           metric_low=r["metric_low"], metric_high=r["metric_high"],
                                           flag=flag_for(prov.get(r["input"], {}).get("status"),
                                                         prov.get(r["input"], {}).get("source")))
                                for r in td.head(10).to_dict("records")])
        warnings = list(self.WARNINGS)
        if mode == "excel":
            warnings.insert(0, "Excel mode reproduces the team Excel including its known errors (AUDIT.md).")
        n_est = sum(flag_for(p.get("status"), p.get("source")) != "real" for p in prov.values())
        warnings.append(f"{n_est} of {len(prov)} inputs are estimates or defaults, not site data.")
        return ModelResult(site_id=site_id, model=self.info.name, mode=mode, baseline=baseline, options=options,
                           tornado=tor, warnings=warnings, inputs_used={k: clean(v) for k, v in x.items()})

    @staticmethod
    def _option(r: dict, mode: str) -> OptionResult:
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
        details = {k: g(k) for k in ("build_mode", "t_sink_c", "p1_thermo", "p2_climate_geo", "p3_economics",
                                     "p4_utilization", "eco_score")}
        return OptionResult(
            option_id=r["key"], name=r["option"], rank=r["rank"] if isinstance(r["rank"], int) else None,
            feasible=feasible, score=g("viability_score"), eco_grade=g("eco_grade"), components=[r["key"]],
            product=g("product"), kpis=kpis, energy_balance=flows if feasible else [], details=details,
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
