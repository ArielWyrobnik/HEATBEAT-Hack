"""Everything the heat chain model needs to know about one data center, with provenance.

`load_site(site_id)` collects:
- the heat source: IT load and two cooling loops (liquid loop and air side loop) with supply and
  return temperatures, from `heatbeat_data.heat_profile` (data center profiles, mostly estimates)
- hourly weather (dry bulb, wet bulb), 8760 local hours
- prices: electricity (EIA retail), gas heat cost, water + sewer tariff, RNG / RIN / LCFS, CO2
- distances and neighbours: district heating, power plant, biomass, coast, geology score

Every value carries a status (data / estimate / assumption) so outputs can be flagged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

SITE_SCOPES = ("site", "campus", "campus_legacy", "cluster", "operator_region")  # see heatbeat_data.current_setup
LCFS_STATES = {"CA", "OR", "WA"}  # state low carbon fuel standards with tradeable credits (2025)

# Baseline heat rejection per cooling profile (what an operating site of that type most likely uses).
# Team assumption from typical designs; operators rarely publish it.
BASELINE_REJECTION = {
    "air_chilled_legacy": "tower", "air_chilled_elevated": "tower", "air_economizer": "adiabatic",
    "tpu_dlc": "tower", "dlc_cold": "tower", "dlc_warm": "adiabatic", "dlc_hot": "dry",
}


@dataclass
class Loop:
    """A cooling loop that collects heat at t_return_c and must be cooled back to t_supply_c."""
    name: str
    q_mw: float
    t_supply_c: float
    t_return_c: float


@dataclass
class SiteCase:
    site_id: str
    name: str
    state: str
    it_mw: float
    loops: list[Loop]
    cooling_profile: str
    baseline_rejection: str
    pue_reported: float
    t_db: np.ndarray
    t_wb: np.ndarray
    x: dict  # scalar site inputs (prices, distances, scores)
    prov: dict = field(default_factory=dict)
    setup: dict = field(default_factory=dict)  # verified current setup (heatbeat_data.current_setup), field -> fact
    already: list = field(default_factory=list)  # components the site already has (already_implemented)

    @property
    def t_mean(self) -> float:
        return float(np.mean(self.t_db))


def _to_8760(s: pd.Series, tz: str) -> np.ndarray:
    from heatbeat_ranking.climate import to_8760
    return to_8760(s, tz)


def _num(v, default):
    try:
        f = float(v)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _row(df: pd.DataFrame):
    t = df.drop_duplicates("site_id").set_index("site_id")
    return lambda sid: t.loc[sid].to_dict() if sid in t.index else {}


def load_site(site_id: str, live: bool = True, weather: pd.DataFrame | None = None,
              is_greenfield: int | None = None, overrides: dict | None = None) -> SiteCase:
    """Site case from the database. `weather` (hourly, UTC index, columns t_db_c and t_wb_c) replaces
    the stored weather (custom coordinates). `overrides` set site inputs (keys of SiteCase.x or it_mw)."""
    import heatbeat_data as hd

    prov: dict[str, dict] = {}

    def put(k, v, default, status, source):
        val = _num(v, None)
        if val is None:
            prov[k] = {"status": "assumption", "source": f"default {default} (no data)"}
            return default
        prov[k] = {"status": status, "source": source}
        return val

    site = hd.get_site(site_id, live=live and weather is None)
    m = site.meta
    hp = hd.heat_profile(site_id)
    it = float(hp["it_load_mw"])
    prof = hp.get("cooling_profile_id") or "air_chilled_elevated"
    liq_share = _num(hp.get("liquid_heat_share"), 0.0)
    loops = []
    if liq_share > 0:
        loops.append(Loop("liquid", it * liq_share, _num(hp.get("facility_supply_temp_c"), 32.0),
                          _num(hp.get("facility_return_temp_c"), 42.0)))
    if liq_share < 1:
        if prof == "air_economizer":
            # direct air side economizer: supply air 24 C, hot aisle exhaust (ASHRAE A1 recommended band)
            air = Loop("air", it * (1 - liq_share), 24.0, _num(hp.get("exhaust_air_temp_c"), 32.0))
        elif prof.startswith("air_chilled"):
            air = Loop("air", it * (1 - liq_share), _num(hp.get("facility_supply_temp_c"), 18.0),
                       _num(hp.get("facility_return_temp_c"), 26.0))
        else:  # residual air heat of a liquid cooled hall, chilled water to the CRAHs at 18/26 C
            air = Loop("air", it * (1 - liq_share), 18.0, 26.0)
        loops.append(air)
    prov["loops"] = {"status": "estimate", "source": f"cooling profile {prof}, site_profiles.csv "
                                                     f"(confidence {hp.get('confidence')})"}

    w = weather if weather is not None else site.weather
    t_db = _to_8760(w["t_db_c"], site.tz)
    t_wb = _to_8760(w["t_wb_c"], site.tz)
    prov["weather"] = {"status": "data", "source": str(w["source"].iloc[0]) if "source" in w else "heatbeat_data"}

    mk = hd.site_market(site_id)
    wat, gis, ind = (_row(hd.site_water()), _row(hd.site_gis()), _row(hd.site_industry()))
    wat, gis, ind = wat(site_id), gis(site_id), ind(site_id)
    eco = hd.excel_ecology_inputs(site_id) if hasattr(hd, "excel_ecology_inputs") else {}
    dh_lower_bound = _num(gis.get("d_dh_m_is_lower_bound"), 0) == 1
    dh_source = "site_gis.csv (estimated distance to a mapped network or dense heat demand)"
    if dh_lower_bound:
        dh_source = f"site_gis.csv: {gis['d_dh_m_source']}"

    x = {
        "p_elec_usd_mwh": put("p_elec_usd_mwh", site.grid.get("retail_industrial_usd_mwh"), 80.0, "data",
                              "EIA retail industrial price of the grid region (location database)"),
        "ci_grid_kg_mwh": put("ci_grid_kg_mwh", site.grid.get("co2_kg_mwh"), 400.0, "data",
                              "grid region CO2 intensity (location database)"),
        "p_heat_usd_mwh": put("p_heat_usd_mwh", 1000 * _num(mk.get("heat_cost_gas_commercial_usd_kwh_th"), np.nan),
                              50.0, "data", "EIA commercial gas price / boiler efficiency (market_prices.csv)"),
        "p_gas_usd_mwh": put("p_gas_usd_mwh", _num(mk.get("ng_citygate_usd_mmbtu"), np.nan) * 3.412, 12.5, "data",
                             "EIA citygate gas price, USD/MMBtu x 3.412 (market_prices.csv)"),
        "rin_usd_mmbtu": put("rin_usd_mmbtu", mk.get("rng_d3_value_usd_mmbtu"), 25.0, "data",
                             "D3 RIN value per MMBtu RNG (market_prices.csv)"),
        "lcfs_usd_t": put("lcfs_usd_t", mk.get("lcfs_credit_usd_t") if m["region"] in LCFS_STATES else 0.0, 0.0,
                          "data", "LCFS credit price, only CA/OR/WA (market_prices.csv)"),
        "p_co2_usd_t": put("p_co2_usd_t", mk.get("p_co2_usd_ton"), 0.0, "data", "state carbon market (market_prices.csv)"),
        "p_water_usd_m3": put("p_water_usd_m3", wat.get("p_water_effective_usd_m3"), 3.0, "data",
                              "water + sewer tariff (site_water.csv)"),
        "wsi": put("wsi", wat.get("wsi_index"), 2.0, "data", "WRI Aqueduct 4.0 baseline water stress 0 to 5"),
        "d_dh_m": put("d_dh_m", gis.get("d_dh_m"), 5000.0, "estimate", dh_source),
        "rho_heat_mwh_m": put("rho_heat_mwh_m", gis.get("rho_heat_mwh_m"), 1.0, "estimate",
                              "site_gis.csv linear heat density (low confidence)"),
        "d_coast_m": put("d_coast_m", gis.get("d_coast_m"), 1e6, "data", "site_gis.csv"),
        "flat_land_m2": put("flat_land_m2", gis.get("flat_land_m2"), 100000.0, "estimate",
                            "site_gis.csv largest flat open land patch within 2 km (ESA WorldCover + DEM, low confidence)"),
        "d_pp_m": put("d_pp_m", ind.get("d_pp_m"), 1e6, "data", "site_industry.csv (EIA-860 thermal plant)"),
        "q_fw_mw": put("q_fw_mw", ind.get("q_fw_mw"), 0.0, "estimate", "site_industry.csv feedwater heat (engineering estimate)"),
        "d_bio_m": put("d_bio_m", ind.get("d_bio_m"), 1e6, "data", "site_industry.csv nearest biomass / digester feedstock"),
        "geo_storage_score": put("geo_storage_score", eco.get("geo_storage_score"), 3.0, "estimate",
                                 "site_ecology.csv (team thresholds)"),
    }
    if dh_lower_bound and prov["d_dh_m"]["status"] != "assumption":
        prov["d_dh_m"]["lower_bound"] = True
    pr = site.prices["price_usd_mwh"] if len(site.prices) else pd.Series(dtype=float)
    x["p_wholesale_usd_mwh"] = put("p_wholesale_usd_mwh", pr.mean() if len(pr) else None, 0.6 * x["p_elec_usd_mwh"],
                                   "data" if len(pr) and not site.prices["is_synthetic"].astype(bool).all() else "synthetic",
                                   "mean hourly day-ahead price of the grid region (location database)")
    if prov["p_heat_usd_mwh"]["status"] == "assumption":  # outside the US: Eurostat gas price per country
        intl = intl_heat_price(m.get("country_iso2"))
        if intl:
            x["p_heat_usd_mwh"], prov["p_heat_usd_mwh"] = intl
    x["has_lcfs"] = m["region"] in LCFS_STATES
    x["pp_name"] = ind.get("pp_name")
    x["bio_name"] = ind.get("bio_name")
    x["bio_kind"] = ind.get("bio_kind")
    x["bio_capacity_mw"] = bio_capacity_mw(ind.get("bio_name"), ind.get("bio_kind"))
    x["is_greenfield"] = bool(int(m.get("is_hypothetical") or 0))
    prov["is_greenfield"] = {"status": "assumption", "source": "is_hypothetical flag in sites.csv"}
    if is_greenfield is not None:
        x["is_greenfield"] = bool(int(is_greenfield))
        prov["is_greenfield"] = {"status": "user", "source": "UI toggle"}
    # what the site does today, from public sources (heatbeat_data.current_setup); else the profile default
    setup = hd.current_setup(site_id) if hasattr(hd, "current_setup") else {}
    vr = hd.verified_rejection(site_id) if setup else None
    if vr:
        rej = vr["value"]
        prov["baseline_rejection"] = {"status": "data", "source": f"{vr['source_title']} ({vr['source_date']}), "
                                      f"{vr['source_url']}, confidence {vr['confidence']}"}
    else:
        rej = BASELINE_REJECTION.get(prof, "tower")
        prov["baseline_rejection"] = {"status": "assumption", "source": f"typical for cooling profile {prof} "
                                      "(no public source for this site)"}
    pue = _num(hp.get("pue_assumed"), 1.4)
    pf = setup.get("pue")
    if pf and pf.get("confidence") in ("high", "medium") and pf.get("scope") in SITE_SCOPES:
        pue = _num(pf["value"], pue)
        prov["pue_reported"] = {"status": "data", "source": f"{pf['source_title']} ({pf['source_date']})"}
    case = SiteCase(site_id=site_id, name=m["name"], state=m["region"], it_mw=it, loops=loops,
                    cooling_profile=prof, baseline_rejection=rej,
                    pue_reported=pue, t_db=t_db, t_wb=t_wb, x=x, prov=prov, setup=setup,
                    already=hd.already_implemented(site_id) if setup else [])
    prov["it_mw"] = {"status": "estimate", "source": f"site_profiles.csv it_load_mw (confidence {hp.get('confidence')})"}
    apply_overrides(case, overrides)
    return case


def apply_overrides(case: "SiteCase", overrides: dict | None) -> None:
    """UI overrides; the cooling profile first, loop tweaks combined, so a heat rejection override given with it wins."""
    o = dict(overrides or {})
    if "cooling_profile" in o:
        set_input(case, "cooling_profile", o.pop("cooling_profile"))
    loop_keys = ("liquid_heat_share", "t_liquid_supply_c", "t_liquid_return_c", "t_air_supply_c", "t_air_return_c")
    if any(k in o for k in loop_keys):
        _update_loops(
            case,
            liquid_share=float(o.pop("liquid_heat_share")) if "liquid_heat_share" in o else None,
            t_liq_sup=float(o.pop("t_liquid_supply_c")) if "t_liquid_supply_c" in o else None,
            t_liq_ret=float(o.pop("t_liquid_return_c")) if "t_liquid_return_c" in o else None,
            t_air_sup=float(o.pop("t_air_supply_c")) if "t_air_supply_c" in o else None,
            t_air_ret=float(o.pop("t_air_return_c")) if "t_air_return_c" in o else None,
        )
    for k, v in o.items():
        set_input(case, k, v)


def _update_loops(case: SiteCase, *, liquid_share: float | None = None, t_liq_sup: float | None = None,
                  t_liq_ret: float | None = None, t_air_sup: float | None = None, t_air_ret: float | None = None) -> None:
    liq = next((l for l in case.loops if l.name == "liquid"), None)
    air = next((l for l in case.loops if l.name == "air"), None)
    cur_share = (liq.q_mw / case.it_mw) if (liq and case.it_mw > 0) else 0.0
    share = float(np.clip(cur_share if liquid_share is None else liquid_share, 0.0, 1.0))
    lsup = t_liq_sup if t_liq_sup is not None else (liq.t_supply_c if liq else 45.0)
    lret = t_liq_ret if t_liq_ret is not None else (liq.t_return_c if liq else 55.0)
    asup = t_air_sup if t_air_sup is not None else (air.t_supply_c if air else 18.0)
    aret = t_air_ret if t_air_ret is not None else (air.t_return_c if air else 26.0)
    if lret <= lsup:
        raise ValueError("t_liquid_return_c must be greater than t_liquid_supply_c")
    if aret <= asup:
        raise ValueError("t_air_return_c must be greater than t_air_supply_c")
    loops = []
    if share > 0:
        loops.append(Loop("liquid", case.it_mw * share, float(lsup), float(lret)))
    if share < 1:
        loops.append(Loop("air", case.it_mw * (1.0 - share), float(asup), float(aret)))
    case.loops = loops
    case.prov["loops"] = {"status": "user", "source": "cooling loop settings customized in the UI"}


def set_input(case: SiteCase, key: str, value) -> None:
    """Change one site input in place (UI override)."""
    import dataclasses
    if key == "cooling_profile":
        prof = str(value)
        case.loops = loops_for_profile(prof, case.it_mw)
        case.cooling_profile = prof
        case.prov["loops"] = {"status": "user", "source": f"cooling profile {prof} set in the UI"}
        if case.prov.get("baseline_rejection", {}).get("status") not in ("data", "user"):
            case.baseline_rejection = BASELINE_REJECTION.get(prof, "tower")
        return
    if key == "liquid_heat_share":
        _update_loops(case, liquid_share=float(value))
        return
    if key == "t_liquid_supply_c":
        _update_loops(case, t_liq_sup=float(value))
        return
    if key == "t_liquid_return_c":
        _update_loops(case, t_liq_ret=float(value))
        return
    if key == "t_air_supply_c":
        _update_loops(case, t_air_sup=float(value))
        return
    if key == "t_air_return_c":
        _update_loops(case, t_air_ret=float(value))
        return
    if key == "baseline_rejection":
        from .heat_rejection import TECHS
        if value not in TECHS:
            raise ValueError(f"baseline_rejection must be one of {TECHS}")
        case.baseline_rejection = str(value)
        case.prov["baseline_rejection"] = {"status": "user", "source": "set in the UI"}
        return
    if key == "it_mw":
        f = float(value) / case.it_mw
        case.it_mw = float(value)
        case.loops = [dataclasses.replace(l, q_mw=l.q_mw * f) for l in case.loops]
    elif key in case.x:
        old = case.x[key]
        if isinstance(old, bool):
            value = str(value).strip().lower() in ("1", "true", "yes")
        elif isinstance(old, (int, float)):
            value = float(value)
        case.x[key] = value
    else:
        raise KeyError(key)
    case.prov[key] = {"status": "user", "source": "set in the UI"}


# Non-US heat value, same definition as the US value: commercial gas price / boiler efficiency.
INTL_HEAT_FILE = Path(__file__).resolve().parents[1] / "data_pipeline" / "heat_prices_intl.csv"
EUROPE_PROXY = {"FR", "IE", "DK", "NO", "GB", "BE", "AT", "IT", "ES", "PT", "PL", "CH"}
BOILER_EFF = 0.85       # as in data_pipeline/build_market_prices.py (US heat cost)
EUR_USD = 1.10          # ASSUMPTION, not sourced: round EUR to USD rate, check against the ECB reference rate


def intl_heat_price(country: str | None):
    """(USD/MWh_th, provenance) from heat_prices_intl.csv, or None (then the 50 USD/MWh default stays)."""
    if not country or not INTL_HEAT_FILE.exists():
        return None
    t = pd.read_csv(INTL_HEAT_FILE).set_index("country_iso2")
    key = country if country in t.index else "EU" if country in EUROPE_PROXY else None
    if key is None:
        return None
    r = t.loc[key]
    usd = 1000 * float(r["gas_eur_kwh"]) * EUR_USD / BOILER_EFF
    proxy = key != country
    return round(usd, 1), {
        "status": "estimate" if proxy else "data",
        "source": (f"Eurostat non-household gas {r['period']} ({'EU average as proxy for ' + country if proxy else country}), "
                   f"{r['gas_eur_kwh']} EUR/kWh x {EUR_USD} USD/EUR (FX rate is a team estimate) / boiler eff {BOILER_EFF}; "
                   f"{r['source_url']}")}


def bio_capacity_mw(name, kind) -> float | None:
    """Electrical capacity (MW) of an existing digester gas plant (EIA-860 via PUDL), None if not a digester."""
    if not name or not str(kind or "").startswith("biogas"):
        return None
    from pathlib import Path
    f = Path(__file__).resolve().parents[1] / "data_pipeline" / "industry" / "eia_biomass_plants.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f)
    hit = t[t["name"] == name]
    return float(hit["capacity_mw"].max()) if len(hit) else None


def synthetic_site(it_mw=100.0, t_mean=15.0, swing=12.0, liquid_share=0.9, t_sup=45.0, t_ret=55.0,
                   **x_over) -> SiteCase:
    """A synthetic site for tests and examples (SYNTHETIC, not a real location)."""
    h = np.arange(8760)
    t_db = t_mean - swing * np.cos(2 * np.pi * h / 8760) - 4 * np.cos(2 * np.pi * (h % 24 - 4) / 24)
    t_wb = t_db - 4 - 0.15 * np.clip(t_db, 0, None)
    loops = [Loop("liquid", it_mw * liquid_share, t_sup, t_ret)]
    if liquid_share < 1:
        loops.append(Loop("air", it_mw * (1 - liquid_share), 18.0, 26.0))
    x = dict(p_elec_usd_mwh=80.0, ci_grid_kg_mwh=400.0, p_heat_usd_mwh=50.0, p_gas_usd_mwh=12.5,
             rin_usd_mmbtu=25.0, lcfs_usd_t=0.0, p_co2_usd_t=0.0, p_water_usd_m3=3.0, wsi=2.0, d_dh_m=2000.0,
             rho_heat_mwh_m=2.0, d_coast_m=1e6, flat_land_m2=300000.0, d_pp_m=8000.0, q_fw_mw=10.0, d_bio_m=10000.0,
             geo_storage_score=4.0, p_wholesale_usd_mwh=45.0, has_lcfs=False, is_greenfield=False, pp_name="synthetic", bio_name="synthetic",
             bio_kind="food processing (synthetic)")
    x.update(x_over)
    return SiteCase("synthetic", "Synthetic site", "XX", it_mw, loops, "dlc_hot", "dry", 1.2, t_db, t_wb, x,
                    {"all": {"status": "synthetic", "source": "synthetic_site()"}})


# ---- planned data centers: any location, any size ------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def nearest_site(lat: float, lon: float, country: str | None = "US") -> tuple[str, float]:
    import heatbeat_data as hd
    s = hd.list_sites()
    if country:
        s = s[s["country_iso2"] == country]
    d = _haversine_m(lat, lon, s["lat"].to_numpy(), s["lon"].to_numpy())
    i = int(np.argmin(d))
    return s["site_id"].iloc[i], float(d[i])


def loops_for_profile(profile_id: str, it_mw: float) -> list[Loop]:
    import heatbeat_data as hd
    cp = hd.cooling_profiles().set_index("cooling_profile_id")
    if profile_id not in cp.index:
        raise KeyError(f"cooling profile {profile_id!r}; one of {list(cp.index)}")
    r = cp.loc[profile_id]
    liq = _num(r.get("liquid_heat_share"), 0.0)
    out = []
    if liq > 0:
        out.append(Loop("liquid", it_mw * liq, _num(r["facility_supply_temp_c"], 32.0), _num(r["facility_return_temp_c"], 42.0)))
    if liq < 1:
        if profile_id == "air_economizer":
            out.append(Loop("air", it_mw * (1 - liq), 24.0, _num(r.get("exhaust_air_temp_c"), 32.0)))
        elif profile_id.startswith("air_chilled"):
            out.append(Loop("air", it_mw * (1 - liq), _num(r["facility_supply_temp_c"], 18.0), _num(r["facility_return_temp_c"], 26.0)))
        else:
            out.append(Loop("air", it_mw * (1 - liq), 18.0, 26.0))
    return out


def load_location(lat: float, lon: float, it_mw: float, cooling_profile: str = "dlc_warm",
                  is_greenfield: bool = True, weather: pd.DataFrame | None = None, live: bool = True,
                  overrides: dict | None = None) -> SiteCase:
    """Case for a planned data center at any point (lat, lon) with IT load it_mw (MW; 1 GW = 1000).

    Weather: `weather` if given, else a live fetch for the point (Open-Meteo, fallback NASA POWER);
    if that fails (no internet), the nearest database site's weather, flagged.
    Prices, water tariff, water stress, gas, RIN/LCFS: the nearest database site (same region in most
    cases), flagged "estimate". Distances to community, power plant, feedstock and coast: the nearest
    site's value plus the distance between both points (an upper bound), flagged "estimate".
    """
    tpl, dist = nearest_site(lat, lon, country=None)  # nearest site of any country: right market and jurisdiction
    w, wsrc = weather, "given"
    if w is None and live:
        try:
            from data_pipeline.fetch_weather import fetch_nasa_power, fetch_open_meteo
            for name, fn in (("open_meteo_era5", fetch_open_meteo), ("nasa_power", fetch_nasa_power)):
                try:
                    w = fn(lat, lon)
                    w.index = pd.to_datetime(w.index, utc=True)
                    wsrc = name
                    break
                except Exception:  # noqa: BLE001
                    continue
        except ImportError:
            w = None
    case = load_site(tpl, live=live, weather=w)
    if w is None:
        case.prov["weather"] = {"status": "synthetic", "source": f"no weather for the point: weather of {tpl} "
                                                                 f"({dist / 1000:.0f} km away) used"}
    else:
        case.prov["weather"] = {"status": "data", "source": f"{wsrc} for {lat:.3f}, {lon:.3f}"}
    case.site_id = f"custom:{lat:.4f},{lon:.4f}"
    case.name = f"Planned {it_mw:,.0f} MW data center ({lat:.3f}, {lon:.3f})"
    case.it_mw = float(it_mw)
    case.loops = loops_for_profile(cooling_profile, it_mw)
    case.cooling_profile = cooling_profile
    case.baseline_rejection = BASELINE_REJECTION.get(cooling_profile, "tower")
    case.prov["loops"] = {"status": "estimate", "source": f"cooling profile {cooling_profile} (cooling_profiles.csv)"}
    case.prov["it_mw"] = {"status": "user", "source": "planned size"}
    for k in ("d_dh_m", "d_pp_m", "d_bio_m", "d_coast_m"):
        if k == "d_dh_m" and case.prov[k].get("lower_bound"):
            source = f"{tpl} GIS lower bound + {dist / 1000:.1f} km offset (screening estimate)"
        else:
            source = f"{tpl} value + {dist / 1000:.1f} km offset (upper bound)"
        case.x[k] = case.x[k] + dist
        case.prov[k] = {"status": "estimate", "source": source}
    for k in ("p_elec_usd_mwh", "ci_grid_kg_mwh", "p_heat_usd_mwh", "p_gas_usd_mwh", "p_water_usd_m3", "wsi",
              "rho_heat_mwh_m", "q_fw_mw", "geo_storage_score", "rin_usd_mmbtu", "lcfs_usd_t", "p_co2_usd_t",
              "p_wholesale_usd_mwh"):
        st = case.prov.get(k, {}).get("source", "")
        case.prov[k] = {"status": "estimate", "source": f"nearest database site {tpl} ({dist / 1000:.0f} km): {st}"}
    case.x["is_greenfield"] = bool(is_greenfield)
    case.prov["is_greenfield"] = {"status": "user", "source": "planned site"}
    case.setup, case.already = {}, []  # a planned site has no current setup; the template's does not apply
    case.prov["baseline_rejection"] = {"status": "assumption", "source": f"typical for cooling profile {cooling_profile}"}
    if not tpl.startswith("us-"):
        case.prov["template"] = {"status": "estimate", "source": f"template {tpl} is outside the US: most site data "
                                 "(water, GIS, industry) are US only, so defaults are used (flagged)"}
    case.x["template_site_id"] = tpl
    case.x["template_distance_m"] = dist
    apply_overrides(case, overrides)
    return case
