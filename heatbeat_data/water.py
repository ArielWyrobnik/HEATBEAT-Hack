"""Water per site: tariff (USD/m3), water stress (WRI Aqueduct) and a baseline WUE estimate.

Reads curated CSVs in data_pipeline/ (no build step):

    site_water.csv        one row per US site: water and sewer tariff with low/high range, utility, flags
    aqueduct_sites.csv    WRI Aqueduct 4.0 baseline water stress per site (written by fetch_aqueduct.py)
    wue_profiles.csv      per cooling profile: how heat is rejected and an annual WUE range
    water_sources.csv     citations

Main entry point:

    import heatbeat_data as hd
    w = hd.site_water()                       # DataFrame, one row per US site, annual numbers
    hd.get_site("us-az-chandler").water()     # same row as a dict
    hd.hourly_wue(site.weather, "dlc_warm")   # hourly WUE from weather (wet bulb / dry bulb)

Field names match the team Excel (sheet 1): p_water_usd_m3, wsi_index.

Definitions:
    p_water_usd_m3      volumetric water supply charge for a large non-residential user, USD/m3
    p_sewer_usd_m3      volumetric sewer charge, USD/m3 (only paid on water that goes to the sewer)
    wsi_index           Aqueduct 4.0 baseline water stress score 0..5 (bws_score); NaN until looked up
    wue_l_kwh           on-site water for cooling per kWh of IT energy (site WUE, The Green Grid)
    water_m3_yr         wue_l_kwh * it_load_mw * 8760 (L/kWh * MWh = m3)
    discharge_share     share of withdrawn water that goes to the sewer (cooling tower blowdown)
                        = 1 / COC for towers, about 0.2 for evaporative media, 0 for dry systems
    water_cost_usd_yr   water_m3_yr * (p_water_usd_m3 + discharge_share * p_sewer_usd_m3)
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

_DIR = Path(__file__).resolve().parents[1] / "data_pipeline"

H_FG_KJ_KG = 2430.0                   # latent heat of water at about 30 C (evap_physics)
L_PER_KWH_EVAP = 3600.0 / H_FG_KJ_KG  # 1.48 L evaporated per kWh of heat
COC_DEFAULT = 4.0                     # cooling tower cycles of concentration (team assumption)
CHILLER_COP = 6.0                     # adds compressor heat to the tower load when chillers run
TOWER_APPROACH_K = 4.0                # tower can free-cool when wet bulb <= supply - approach
AIR_DT_K = 12.0                       # air temperature rise across IT for adiabatic economizers
EVAP_EFFECTIVENESS = 0.85             # direct evaporative media
MEDIA_BLEED = 1.2                     # evaporative media bleed factor (team assumption)
HOURS = 8760


@lru_cache(maxsize=1)
def water_tariffs() -> pd.DataFrame:
    return pd.read_csv(_DIR / "site_water.csv")


@lru_cache(maxsize=1)
def wue_profiles() -> pd.DataFrame:
    return pd.read_csv(_DIR / "wue_profiles.csv")


@lru_cache(maxsize=1)
def water_sources() -> pd.DataFrame:
    return pd.read_csv(_DIR / "water_sources.csv")


@lru_cache(maxsize=1)
def aqueduct() -> pd.DataFrame:
    """Aqueduct 4.0 per site. Empty frame if data_pipeline/aqueduct_sites.csv has not been made yet."""
    p = _DIR / "aqueduct_sites.csv"
    if not p.exists():
        return pd.DataFrame(columns=["site_id", "bws_score", "bws_raw", "bws_label"])
    return pd.read_csv(p)


def _profile(profile_id: str) -> dict:
    p = wue_profiles()
    row = p[p["cooling_profile_id"] == profile_id]
    if row.empty:
        raise KeyError(f"no WUE profile for {profile_id!r}")
    return row.iloc[0].to_dict()


def _tower_l_kwh(t_wb: pd.Series, supply_c: float | None, coc: float) -> pd.Series:
    """Tower water per kWh IT heat: evaporation (plus chiller heat when free cooling is not enough) and blowdown."""
    if supply_c is None or np.isnan(supply_c):
        chiller_on = pd.Series(True, index=t_wb.index)
    else:
        chiller_on = t_wb > supply_c - TOWER_APPROACH_K
    heat = 1.0 + chiller_on.astype(float) / CHILLER_COP
    return heat * L_PER_KWH_EVAP * coc / (coc - 1.0)


def hourly_wue(weather: pd.DataFrame, profile_id: str, liquid_share: float | None = None,
               coc: float = COC_DEFAULT) -> pd.Series:
    """Hourly site WUE in L per kWh IT from dry bulb (t_db_c) and wet bulb (t_wb_c).

    Simple engineering model, not a plant simulation. Parameters are module constants and the
    columns of wue_profiles.csv; all of them are team assumptions except the latent heat.
    """
    prof = _profile(profile_id)
    cp = _cooling_profile_row(profile_id)
    supply = cp.get("facility_supply_temp_c")
    t_db, t_wb = weather["t_db_c"], weather["t_wb_c"]
    kind = prof["heat_rejection"]

    if kind == "dry_cooler":
        return pd.Series(0.0, index=weather.index, name="wue_l_kwh")
    if kind == "cooling_tower":
        return _tower_l_kwh(t_wb, supply, coc).rename("wue_l_kwh")
    if kind == "adiabatic_air":
        # cool outside air from t_db towards the economizer limit, bounded by the wet bulb depression
        limit = float(prof["evap_assist_above_db_c"])
        d_t = np.minimum((t_db - limit).clip(lower=0), EVAP_EFFECTIVENESS * (t_db - t_wb).clip(lower=0))
        m_air_kg_s_per_kw = 1.0 / (1.006 * AIR_DT_K)
        return (m_air_kg_s_per_kw * 1.006 * d_t / H_FG_KJ_KG * 3600 * MEDIA_BLEED).rename("wue_l_kwh")
    if kind == "hybrid_dry_tower":
        share = cp.get("liquid_heat_share") if liquid_share is None else liquid_share
        share = 1.0 if share is None or np.isnan(share) else float(share)
        dry_ok = t_db <= float(prof["dry_max_db_c"])
        liquid = (~dry_ok).astype(float) * _tower_l_kwh(t_wb, supply, coc)
        air = _tower_l_kwh(t_wb, 18.0, coc)  # remaining air heat via an elevated chilled water room
        return (share * liquid + (1 - share) * air).rename("wue_l_kwh")
    raise ValueError(f"unknown heat_rejection {kind!r}")


@lru_cache(maxsize=None)
def _cooling_profile_row(profile_id: str) -> dict:
    from .heat_profiles import cooling_profiles
    c = cooling_profiles()
    row = c[c["cooling_profile_id"] == profile_id]
    return row.iloc[0].to_dict() if not row.empty else {}


def _discharge_share(profile_id: str, coc: float) -> float:
    kind = _profile(profile_id)["heat_rejection"]
    return {"cooling_tower": 1 / coc, "hybrid_dry_tower": 1 / coc,
            "adiabatic_air": 1 - 1 / MEDIA_BLEED, "dry_cooler": 0.0}[kind]


def site_water(weather: dict[str, pd.DataFrame] | None = None, coc: float = COC_DEFAULT) -> pd.DataFrame:
    """One row per US site with tariff, water stress, baseline WUE, annual water volume and cost.

    weather: optional {site_id: hourly weather frame}. Sites with weather get a weather-based WUE
    (wue_method = "hourly_weather"); the others use the annual default of their cooling profile
    (wue_method = "profile_default"). Low/high always come from the profile range and the IT load range.
    """
    from .heat_profiles import site_heat_profiles

    t = water_tariffs()
    hp = site_heat_profiles()[["site_id", "cooling_profile_id", "liquid_heat_share", "it_load_mw_low",
                               "it_load_mw", "it_load_mw_high", "pue_assumed"]]
    df = t.merge(hp, on="site_id", how="left", validate="one_to_one")
    df["wue_profile_id"] = df["wue_profile_override"].fillna("").replace("", np.nan).fillna(df["cooling_profile_id"])

    aq = aqueduct()
    if len(aq):
        df = df.merge(aq[["site_id", "bws_score", "bws_raw", "bws_label"]], on="site_id", how="left")
        df["wsi_index"] = df["bws_score"]
    else:
        df["wsi_index"] = np.nan
        df["bws_raw"] = np.nan
        df["bws_label"] = "not looked up yet (run data_pipeline/fetch_aqueduct.py)"

    prof = wue_profiles().set_index("cooling_profile_id")
    df["wue_l_kwh_low"] = df["wue_profile_id"].map(prof["wue_l_kwh_low"])
    df["wue_l_kwh"] = df["wue_profile_id"].map(prof["wue_l_kwh"])
    df["wue_l_kwh_high"] = df["wue_profile_id"].map(prof["wue_l_kwh_high"])
    df["wue_method"] = "profile_default"
    for i, r in df.iterrows():
        w = (weather or {}).get(r["site_id"])
        if w is not None and len(w):
            share = None if r["wue_profile_id"] != r["cooling_profile_id"] else r["liquid_heat_share"]
            df.at[i, "wue_l_kwh"] = round(float(hourly_wue(w, r["wue_profile_id"], share, coc).mean()), 3)
            df.at[i, "wue_method"] = "hourly_weather"

    df["discharge_share"] = [round(_discharge_share(p, coc), 3) for p in df["wue_profile_id"]]
    for sfx, mw, wue in (("_low", "it_load_mw_low", "wue_l_kwh_low"), ("", "it_load_mw", "wue_l_kwh"),
                         ("_high", "it_load_mw_high", "wue_l_kwh_high")):
        df[f"water_m3_yr{sfx}"] = (df[wue] * df[mw] * HOURS).round(-2)
    price = df["p_water_usd_m3"] + df["discharge_share"] * df["p_sewer_usd_m3"]
    price_lo = df["p_water_usd_m3_low"] + df["discharge_share"] * df["p_sewer_usd_m3_low"]
    price_hi = df["p_water_usd_m3_high"] + df["discharge_share"] * df["p_sewer_usd_m3_high"]
    df["p_water_effective_usd_m3"] = price.round(3)
    df["water_cost_usd_yr_low"] = (df["water_m3_yr_low"] * price_lo).round(-3)
    df["water_cost_usd_yr"] = (df["water_m3_yr"] * price).round(-3)
    df["water_cost_usd_yr_high"] = (df["water_m3_yr_high"] * price_hi).round(-3)
    cols = ["site_id", "water_utility", "p_water_usd_m3", "p_water_usd_m3_low", "p_water_usd_m3_high",
            "p_sewer_usd_m3", "p_sewer_usd_m3_low", "p_sewer_usd_m3_high", "p_water_effective_usd_m3",
            "wsi_index", "bws_raw", "bws_label", "wue_profile_id", "wue_method",
            "wue_l_kwh_low", "wue_l_kwh", "wue_l_kwh_high", "discharge_share",
            "it_load_mw", "water_m3_yr_low", "water_m3_yr", "water_m3_yr_high",
            "water_cost_usd_yr_low", "water_cost_usd_yr", "water_cost_usd_yr_high",
            "tariff_basis", "rate_year", "confidence", "water_is_estimated", "sewer_is_estimated",
            "source_ids", "notes"]
    return df[cols].sort_values("site_id").reset_index(drop=True)


def site_water_row(site_id: str, weather: pd.DataFrame | None = None) -> dict:
    df = site_water({site_id: weather} if weather is not None else None)
    row = df[df["site_id"] == site_id]
    if row.empty:
        raise KeyError(f"no water data for {site_id!r} (US sites only for now)")
    d = row.iloc[0].to_dict()
    return {k: (None if (isinstance(v, float) and pd.isna(v)) else (v.item() if hasattr(v, "item") else v))
            for k, v in d.items()}


def write_ranking_inputs(path: Path | str | None = None) -> Path:
    """Write data_pipeline/site_ranking_inputs_water.csv for the ranking engine (long format).

    Columns: site_id, key, value, status (data or assumption), source, note. Keys: p_water_usd_m3,
    wsi_index (only for sites with an Aqueduct lookup).
    """
    df = site_water()
    rows = []
    for r in df.itertuples():
        rows.append((r.site_id, "p_water_usd_m3", r.p_water_usd_m3,
                     "assumption" if r.water_is_estimated else "data", r.source_ids,
                     f"{r.water_utility}; range {r.p_water_usd_m3_low} to {r.p_water_usd_m3_high} USD/m3; "
                     f"sewer {r.p_sewer_usd_m3} USD/m3 extra on discharged water"))
        if not pd.isna(r.wsi_index):
            rows.append((r.site_id, "wsi_index", round(float(r.wsi_index), 2), "data", "wri_aqueduct_4",
                         f"Aqueduct 4.0 baseline water stress: {r.bws_label}"))
    out = pd.DataFrame(rows, columns=["site_id", "key", "value", "status", "source", "note"])
    p = Path(path) if path else _DIR / "site_ranking_inputs_water.csv"
    out.to_csv(p, index=False)
    return p
