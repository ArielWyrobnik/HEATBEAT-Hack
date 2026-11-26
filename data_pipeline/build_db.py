"""Build data/parquet/*.parquet (committed) and data/heatbeat.db (SQLite, local) from all sources.

Usage:
    python -m data_pipeline.build_db            # real data (needs internet)
    python -m data_pipeline.build_db --offline  # synthetic placeholders, for testing the pipeline only
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

from .common import DB_PATH, PARQUET_DIR, REPORT_PATH, YEAR, load_grid_regions, load_sites, log, setup_logging, write_json
from .fetch_prices import ILS_PER_USD, get_prices
from .fetch_retail_carbon import EIA_AVGPRICE_URL, EMBER_GLOBAL_URL, enrich_regions
from .fetch_weather import COLUMNS as WEATHER_COLS, get_weather
from heatbeat_data.sqlite_build import build_sqlite

REGION_COLS = ["grid_region_id", "name", "country_iso2", "country_iso3", "us_state", "iso_rto", "lmp_location",
               "egrid_subregion", "notes", "retail_industrial_usd_mwh", "retail_commercial_usd_mwh",
               "retail_price_year", "retail_price_source", "retail_price_is_synthetic", "co2_kg_mwh", "co2_year",
               "co2_source", "co2_is_synthetic", "hourly_price_kind"]

SOURCES = [
    ("open_meteo_era5", "Open-Meteo Historical Weather API (ERA5 / ERA5-Land reanalysis)",
     "https://open-meteo.com/en/docs/historical-weather-api", "CC BY 4.0 (data); free API for non-commercial use", 0,
     "Wet bulb derived with Stull (2011) from t_db_c and rh_pct."),
    ("nasa_power", "NASA POWER hourly point API", "https://power.larc.nasa.gov/docs/services/api/temporal/hourly/",
     "Public domain (NASA)", 0, "Fallback weather source. Wet bulb derived with Stull (2011)."),
    ("eia_avgprice_annual", "EIA Average Price by State by Provider (annual)", EIA_AVGPRICE_URL,
     "Public domain (US government)", 0, "Total Electric Industry rows; cents/kWh converted to USD/MWh."),
    ("epa_egrid2023_rev2", "EPA eGRID2023 rev2, subregion total output CO2 emission rate",
     "https://www.epa.gov/egrid/summary-data", "Public domain (US government)", 0,
     "lb/MWh transcribed from the summary page on 2026-11-26, converted to kg/MWh."),
    ("ember_yearly_global", "Ember yearly electricity data (global)", EMBER_GLOBAL_URL, "CC BY 4.0", 0,
     "Overall emissions intensity (gCO2e/kWh), latest available year per country."),
    ("caiso_gridstatus_da_hourly", "CAISO OASIS day-ahead hourly LMP via gridstatus", "https://oasis.caiso.com",
     "Public ISO market data; gridstatus is BSD-3", 0, ""),
    ("miso_gridstatus_da_hourly", "MISO day-ahead hourly LMP via gridstatus", "https://www.misoenergy.org/markets-and-operations/real-time--market-data/market-reports/",
     "Public ISO market data; gridstatus is BSD-3", 0, ""),
    ("nyiso_gridstatus_da_hourly", "NYISO day-ahead hourly LBMP via gridstatus", "https://www.nyiso.com/energy-market-operational-data",
     "Public ISO market data; gridstatus is BSD-3", 0, ""),
    ("isone_gridstatus_da_hourly", "ISO-NE day-ahead hourly LMP via gridstatus", "https://www.iso-ne.com/isoexpress/",
     "Public ISO market data; gridstatus is BSD-3", 0, ""),
    ("spp_gridstatus_da_hourly", "SPP day-ahead hourly LMP via gridstatus", "https://portal.spp.org/groups/integrated-marketplace",
     "Public ISO market data; gridstatus is BSD-3", 0, ""),
    ("pjm_gridstatus_da_hourly", "PJM Data Miner 2 day-ahead hourly LMP via gridstatus", "https://dataminer2.pjm.com",
     "PJM Data Miner terms; free API key required; gridstatus is BSD-3", 0, ""),
    ("ercot_ercot_dam_spp_historical", "ERCOT historical DAM hub and load zone prices (NP4-180-ER) via gridstatus",
     "https://www.ercot.com/mp/data-products/data-product-details?id=NP4-180-ER",
     "Public ISO market data; gridstatus is BSD-3", 0, ""),
    ("iec_taoz_2023", "Israel Electric Corp. Time of Use (TAOZ) tariff, applicable as of 1 April 2023",
     "https://ieccontent.iec.co.il/media/uduj1bi3/%D7%AA%D7%A2%D7%A8%D7%99%D7%A4%D7%99%D7%9D-1-4-23-%D7%91%D7%90%D7%A0%D7%92%D7%9C%D7%99%D7%AA-%D7%9E%D7%A2%D7%9E-17.pdf",
     "Published tariff", 0,
     f"Lower of the two rate columns used (read as high voltage, UNVERIFIED). Excl. VAT. Holidays ignored. "
     f"Converted at {ILS_PER_USD} ILS/USD (approximate, UNVERIFIED). Tariff may have changed since 2023."),
    ("synthetic_shape", "Synthetic diurnal and seasonal price shape x annual retail price", "docs/DATA.md",
     "n/a", 1, "Used where no public hourly price is available. Not real market data."),
    ("estimate_unverified", "Rough estimate (team placeholder)", "data_pipeline/grid_regions.csv", "n/a", 1,
     "Order-of-magnitude placeholder. Replace with a cited value before drawing conclusions."),
    ("synthetic_offline", "Offline synthetic placeholder", "data_pipeline/fetch_weather.py", "n/a", 1,
     "Generated only by --offline test builds."),
]


def build(offline: bool = False) -> dict:
    sites, regions = load_sites(), load_grid_regions()
    assert sites["grid_region_id"].isin(regions["grid_region_id"]).all(), "site with unknown grid_region_id"

    regions, carbon_status = enrich_regions(regions, offline=offline)
    retail = dict(zip(regions["grid_region_id"], regions["retail_industrial_usd_mwh"]))
    prices, price_status = get_prices(regions, retail, offline=offline)
    weather, weather_status = get_weather(sites, offline=offline)

    kind = prices.groupby("grid_region_id")["price_kind"].first()
    regions["hourly_price_kind"] = regions["grid_region_id"].map(kind)
    il = regions["grid_region_id"] == "IL"
    il_mean = prices.loc[prices["grid_region_id"] == "IL", "price_usd_mwh"].mean()
    regions.loc[il, ["retail_industrial_usd_mwh", "retail_price_year", "retail_price_source", "retail_price_is_synthetic"]] = [il_mean, 2023, "iec_taoz_2023", 0]

    for df in (weather, prices):
        df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    weather[WEATHER_COLS] = weather[WEATHER_COLS].round(2)
    prices["price_usd_mwh"] = prices["price_usd_mwh"].round(2)

    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {"reference_year": str(YEAR), "built_utc": built, "build_mode": "offline_synthetic" if offline else "online",
            "timestamps": "UTC, hour-beginning", "schema_version": "1"}
    src = pd.DataFrame(SOURCES, columns=["source_id", "name", "url", "licence", "is_synthetic", "notes"])
    regions = regions[REGION_COLS]

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    tables = {"sites": sites, "grid_regions": regions, "weather_hourly": weather, "price_hourly": prices,
              "sources": src, "meta": pd.DataFrame(list(meta.items()), columns=["key", "value"])}
    for name, df in tables.items():
        df.to_parquet(PARQUET_DIR / f"{name}.parquet", index=False)
    build_sqlite(PARQUET_DIR, DB_PATH)

    report = {
        "meta": meta, "carbon_and_retail": carbon_status, "prices": price_status, "weather": weather_status,
        "counts": {"sites": len(sites), "grid_regions": len(regions), "weather_rows": len(weather),
                   "price_rows": len(prices)},
        "synthetic_share": {"price_rows": float(prices["is_synthetic"].mean()),
                            "weather_sites": float(weather.groupby("site_id")["source"].first().str.startswith("synthetic").mean())},
    }
    write_json(REPORT_PATH, report)
    log.info("built %s: %s", DB_PATH, report["counts"])
    return report


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="synthetic placeholders only, for pipeline tests")
    build(offline=ap.parse_args().offline)


if __name__ == "__main__":
    main()
