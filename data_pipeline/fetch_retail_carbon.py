"""Annual retail electricity prices and grid carbon intensity per grid region.

US retail: EIA Electric Power Annual Table 2.10 (2024 values, transcribed), public domain.
US carbon: EPA eGRID2023 rev2 subregion total output CO2 emission rates (lb/MWh), public domain,
           transcribed from https://www.epa.gov/egrid/summary-data (fetched 2026-11-26).
Non-US carbon: Ember yearly electricity data (global), CC BY 4.0.
Non-US retail: rough estimates in grid_regions.csv, flagged as synthetic / unverified.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import CACHE_DIR, http_get, log

EIA_AVGPRICE_URL = "https://www.eia.gov/electricity/annual/html/epa_02_10.html"
EMBER_GLOBAL_URL = "https://files.ember-energy.org/public-downloads/generation/outputs/release_generation_yearly_global.csv"

LB_TO_KG = 0.45359237

# eGRID2023 (rev2) subregion total output emission rate, CO2, lb/MWh.
EGRID2023_CO2_LB_MWH = {
    "AKGD": 899.633, "AKMS": 520.483, "AZNM": 703.703, "CAMX": 428.464, "ERCT": 733.862, "FRCC": 782.262,
    "HIMS": 1123.371, "HIOA": 1489.548, "MROE": 1397.313, "MROW": 920.130, "NEWE": 539.275, "NWPP": 631.735,
    "NYCW": 864.469, "NYLI": 1180.672, "NYUP": 242.089, "PRMS": 1543.073, "RFCE": 596.904, "RFCM": 970.617,
    "RFCW": 911.424, "RMPA": 1036.601, "SPNO": 861.999, "SPSO": 872.042, "SRMV": 739.720, "SRMW": 1239.839,
    "SRSO": 842.329, "SRTV": 898.079, "SRVC": 593.419, "US": 767.209,
}


# EIA Electric Power Annual, Table 2.10 "Average Price of Electricity to Ultimate Customers by End-Use
# Sector, by State, 2025 and 2024", year 2024 columns, cents/kWh (Form EIA-861, final). Transcribed
# 2026-11-26 from https://www.eia.gov/electricity/annual/html/epa_02_10.html. (commercial, industrial)
EIA_EPA_2_10_2024_CENTS = {
    "VA": (8.72, 8.99), "TX": (8.55, 6.12), "AZ": (12.23, 7.90), "IL": (11.81, 8.83), "GA": (10.87, 7.21),
    "CA": (25.54, 21.53), "OR": (10.11, 8.05), "WA": (9.99, 6.61), "IA": (10.22, 6.80), "NE": (8.39, 7.66),
    "OK": (8.92, 5.84), "OH": (10.66, 7.10), "WI": (12.63, 8.54), "LA": (10.46, 5.61), "TN": (12.05, 6.21),
    "NV": (10.19, 8.64), "UT": (9.39, 7.86), "NC": (10.56, 7.77), "SC": (10.64, 6.84), "NY": (18.77, 9.17),
    "NJ": (14.64, 11.93), "MA": (20.90, 18.19), "WY": (9.27, 7.96), "FL": (10.99, 8.50),
    # added 2026-11-26 for the reference validation sites (same table, 2024 columns)
    "ND": (7.19, 7.25), "HI": (38.18, 34.13),
}


def fetch_eia_retail(fetch: bool = True) -> tuple[pd.DataFrame, int]:
    """Industrial and commercial price (USD/MWh) per state for 2024 (transcribed EIA Table 2.10)."""
    df = pd.DataFrame.from_dict(EIA_EPA_2_10_2024_CENTS, orient="index", columns=["commercial", "industrial"])
    out = pd.DataFrame({"industrial_usd_mwh": df["industrial"] * 10, "commercial_usd_mwh": df["commercial"] * 10})
    return out, 2024


def fetch_ember_intensity(fetch: bool = True) -> tuple[dict[str, float], dict[str, int]]:
    """Latest-year overall emissions intensity (gCO2e/kWh == kg/MWh) per ISO3 country code."""
    cache = CACHE_DIR / "ember_yearly_global.csv"
    if not cache.exists() and not fetch:
        raise FileNotFoundError(f"{cache} not cached (run --stage regions)")
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(http_get(EMBER_GLOBAL_URL, timeout=600).content)
    df = pd.read_csv(cache, low_memory=False)
    cols = {c.lower(): c for c in df.columns}
    log.info("ember columns: %s", list(df.columns)[:30])
    iso_col = next(cols[c] for c in cols if "iso" in c and "3" in c)
    year_col = next(cols[c] for c in cols if c in ("year", "date"))
    if "variable" in cols and "value" in cols:  # pre-July-2026 long format
        sel = df[df[cols["variable"]].astype(str).str.lower().isin(["co2 intensity", "emissions intensity"])]
        val_col = cols["value"]
    else:  # July-2026 format: metrics are columns, overall rows have source "Total generation"
        src_col = next(cols[c] for c in cols if "source" in c and "aggregat" not in c)
        sel = df[df[src_col].astype(str).str.lower() == "total generation"]
        val_col = next(cols[c] for c in cols if "intensity" in c)
    sel = sel[[iso_col, year_col, val_col]].dropna()
    sel[year_col] = pd.to_numeric(sel[year_col].astype(str).str[:4], errors="coerce")
    latest = sel.sort_values(year_col).groupby(iso_col).tail(1).set_index(iso_col)
    return latest[val_col].astype(float).to_dict(), latest[year_col].astype(int).to_dict()


def enrich_regions(regions: pd.DataFrame, offline: bool = False, fetch: bool = True) -> tuple[pd.DataFrame, dict]:
    reg = regions.copy()
    status: dict[str, str] = {}
    for c in ("retail_industrial_usd_mwh", "retail_commercial_usd_mwh", "co2_kg_mwh"):
        reg[c] = np.nan
    for c in ("retail_price_year", "co2_year"):
        reg[c] = pd.NA
    reg["retail_price_source"] = None
    reg["retail_price_is_synthetic"] = 1
    reg["co2_source"] = None
    reg["co2_is_synthetic"] = 1

    us = reg["country_iso2"] == "US"
    # --- US retail (EIA) ---
    if not offline:
        try:
            eia, year = fetch_eia_retail(fetch)
            for i in reg.index[us]:
                st = reg.at[i, "us_state"]
                if st in eia.index:
                    reg.at[i, "retail_industrial_usd_mwh"] = eia.at[st, "industrial_usd_mwh"]
                    reg.at[i, "retail_commercial_usd_mwh"] = eia.at[st, "commercial_usd_mwh"]
                    reg.at[i, "retail_price_year"] = year
                    reg.at[i, "retail_price_source"] = "eia_avgprice_annual"
                    reg.at[i, "retail_price_is_synthetic"] = 0
            status["eia_retail"] = f"ok ({year})"
        except Exception as exc:  # noqa: BLE001
            log.warning("EIA retail failed: %s", exc)
            status["eia_retail"] = f"failed: {exc}"
    # --- US carbon (eGRID, transcribed) ---
    for i in reg.index[us]:
        sub = reg.at[i, "egrid_subregion"]
        reg.at[i, "co2_kg_mwh"] = EGRID2023_CO2_LB_MWH[sub] * LB_TO_KG
        reg.at[i, "co2_year"] = 2023
        reg.at[i, "co2_source"] = "epa_egrid2023_rev2"
        reg.at[i, "co2_is_synthetic"] = 0
    # --- Non-US carbon (Ember) ---
    if not offline:
        try:
            inten, years = fetch_ember_intensity(fetch)
            for i in reg.index[~us]:
                iso3 = reg.at[i, "country_iso3"]
                if iso3 in inten:
                    reg.at[i, "co2_kg_mwh"] = inten[iso3]
                    reg.at[i, "co2_year"] = years[iso3]
                    reg.at[i, "co2_source"] = "ember_yearly_global"
                    reg.at[i, "co2_is_synthetic"] = 0
            status["ember"] = f"ok ({len(inten)} countries)"
        except Exception as exc:  # noqa: BLE001
            log.warning("Ember failed: %s", exc)
            status["ember"] = f"failed: {exc}"
    # --- Fallbacks (flagged synthetic) ---
    miss = reg["co2_kg_mwh"].isna()
    reg.loc[miss, "co2_kg_mwh"] = reg.loc[miss, "fallback_co2_kg_mwh"]
    reg.loc[miss, "co2_source"] = "estimate_unverified"
    miss = reg["retail_industrial_usd_mwh"].isna()
    reg.loc[miss, "retail_industrial_usd_mwh"] = reg.loc[miss, "fallback_retail_usd_mwh"]
    reg.loc[miss & reg["retail_industrial_usd_mwh"].notna(), "retail_price_source"] = "estimate_unverified"
    if offline:  # make US prices usable for offline tests only
        us_miss = us & reg["retail_industrial_usd_mwh"].isna()
        reg.loc[us_miss, "retail_industrial_usd_mwh"] = 85.0
        reg.loc[us_miss, "retail_price_source"] = "synthetic_offline"
    return reg.drop(columns=["fallback_retail_usd_mwh", "fallback_co2_kg_mwh"]), status
