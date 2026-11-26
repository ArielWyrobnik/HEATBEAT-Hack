# HEATBEAT location database

One row per data center site, with a full year (2024, 8784 hours, UTC) of weather and
electricity price data, plus annual retail price and grid carbon intensity per grid region.
This is the shared input for all solution models (heat reuse, free cooling, load shifting, ...).

## Files

| Path | What | In git |
|---|---|---|
| `data/parquet/*.parquet` | Source of truth, one file per table | yes |
| `data/heatbeat.db` | SQLite copy, built automatically on first use of `heatbeat_data` | no (git-ignored) |
| `data/cache/weather/<site_id>.parquet` | Weather fetched live on first use of a site (git-ignored) | no |
| `data/build_report.json` | What was fetched, coverage per region, synthetic shares | yes |
| `data_pipeline/sites.csv` | Curated site list (edit this to add sites) | yes |
| `data_pipeline/grid_regions.csv` | Grid region mapping and fallback estimates | yes |

## Quick start

```python
import heatbeat_data as hd

sites = hd.list_sites()                 # for the map: site_id, name, lat, lon, capacity_mw, price, CO2
s = hd.get_site("us-va-ashburn-equinix")
s.weather                               # hourly: t_db_c, rh_pct, t_dew_c, t_wb_c, wind_ms, ghi_wm2
                                        # (fetched live from Open-Meteo on first use, then cached)
s.prices                                # hourly: price_usd_mwh, price_kind, is_synthetic
s.hourly()                              # weather and price joined on one UTC index
s.local(s.weather)                      # same frame in the site's local time zone
s.summary()                             # annual indicators as a plain dict
```

Weather: if the database has no stored weather for a site, `get_site()` calls the Open-Meteo API
once (fallback NASA POWER), needs internet for that first call (1 to 3 s), and caches the result in
`data/cache/weather/`. Use `get_site(id, live=False)` to skip the call. To pre-store weather for all
sites, run `python -m data_pipeline.build_db --stage weather` and then `--stage assemble` on a machine
with internet.

SQL users: `sqlite3 data/heatbeat.db` (run any `heatbeat_data` call once to create it).

## Schema (schema_version 1)

Keep this stable: solution models depend on it. Add columns, do not rename or remove.

**sites**: `site_id` (PK, slug), `name`, `operator`, `city`, `region`, `country_iso2`, `lat`, `lon`,
`coord_precision` (`building`, `campus_approx`, `city_approx`), `capacity_mw` (NULL if not public),
`capacity_note`, `grid_region_id` (FK), `is_hypothetical` (1 = not a real data center), `notes`.

**grid_regions**: `grid_region_id` (PK), `name`, `country_iso2`, `country_iso3`, `us_state`, `iso_rto`,
`lmp_location`, `egrid_subregion`, `notes`, `retail_industrial_usd_mwh`, `retail_commercial_usd_mwh`,
`retail_price_year`, `retail_price_source` (FK sources), `retail_price_is_synthetic`, `co2_kg_mwh`,
`co2_year`, `co2_source` (FK sources), `co2_is_synthetic`, `hourly_price_kind`.

**weather_hourly**: `site_id`, `ts_utc`, `t_db_c` (dry bulb, 2 m), `rh_pct`, `t_dew_c`, `t_wb_c`
(wet bulb, derived), `wind_ms` (10 m), `ghi_wm2` (global horizontal irradiance), `source`.

**price_hourly**: `grid_region_id`, `ts_utc`, `price_usd_mwh`, `price_kind`, `is_synthetic`, `source`.
`price_kind` is one of:

- `wholesale_da_lmp`: real day-ahead hourly wholesale price at a hub or zone. Does NOT include
  transmission, distribution, capacity charges or taxes, so it is much lower than what a data center pays.
  Use it for the shape over day and year and for load shifting value; use `retail_*` for the bill level.
- `retail_tou`: real time-of-use retail tariff applied hour by hour (Israel, IEC TAOZ).
- `synthetic_shape`: annual average retail price times a synthetic shape. **Not real hourly data.**

**sources**: `source_id`, `name`, `url`, `licence`, `is_synthetic`, `notes`.
**meta**: `reference_year`, `built_utc`, `build_mode`, `timestamps`, `schema_version`.

All timestamps are UTC, hour-beginning.

## Sources, real versus synthetic

| Data | Source | Real? | Licence |
|---|---|---|---|
| Hourly weather | [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) (ERA5 reanalysis); fallback [NASA POWER](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/) | real (reanalysis, about 25 km grid, not a station at the site) | [CC BY 4.0](https://open-meteo.com/en/licence), free for non-commercial use; NASA POWER public domain |
| Wet bulb | Derived from dry bulb and RH with Stull (2011), about 1 C error | derived | n/a |
| US hourly prices, ISO regions | Day-ahead hourly LMP from CAISO, ERCOT, MISO, NYISO, ISO-NE, SPP, PJM via [gridstatus](https://pypi.org/project/gridstatus/) | real where `is_synthetic = 0`; see `build_report.json` for coverage | public ISO data; gridstatus BSD-3 |
| US hourly prices, non-market regions (Southeast, Northwest, Southwest, TVA) | annual EIA retail price x synthetic shape | **synthetic** | n/a |
| PJM (Virginia, Illinois, Ohio, New Jersey) | needs a free PJM Data Miner API key (repo secret `PJM_API_KEY`); without it, **synthetic** | depends | PJM terms |
| US retail price | [EIA Electric Power Annual Table 2.10](https://www.eia.gov/electricity/annual/html/epa_02_10.html), 2024, commercial and industrial, transcribed | real | public domain |
| US carbon intensity | [EPA eGRID2023 rev2](https://www.epa.gov/egrid/summary-data) subregion total output CO2 rate, lb/MWh converted to kg/MWh | real, annual average | public domain |
| Non-US carbon intensity | [Ember yearly electricity data](https://ember-energy.org/data/yearly-electricity-data/), latest year | real, annual average | CC BY 4.0 |
| Non-US retail price (except Israel) | rough team estimates in `grid_regions.csv` | **unverified estimate**, flagged `estimate_unverified` | n/a |
| Israel hourly price | [IEC Time of Use tariff, as of 1 April 2023](https://ieccontent.iec.co.il/media/uduj1bi3/%D7%AA%D7%A2%D7%A8%D7%99%D7%A4%D7%99%D7%9D-1-4-23-%D7%91%D7%90%D7%A0%D7%92%D7%9C%D7%99%D7%AA-%D7%9E%D7%A2%D7%9E-17.pdf) | real tariff, see caveats | published tariff |
| Site coordinates | curated by hand from public knowledge of the campuses | approximate, see `coord_precision` | n/a |
| Site capacity (MW) | only where widely press-reported; otherwise NULL | **unverified** | n/a |

### Known caveats (please read before presenting numbers)

1. **Coordinates** are campus or city level, not surveyed. They are good enough for weather
   (the reanalysis grid is about 25 km) but not for siting a pipe.
2. **Capacities** are only filled for two announced projects (Stargate Abilene 1.2 GW, Meta Hyperion
   2 GW) and are press-reported, unverified targets.
3. **Israel tariff**: the PDF has two rate columns per row; we use the lower one, read as the
   high-voltage rate. That mapping is unverified. Rates are excl. VAT, from April 2023, applied to the
   2024 calendar with holidays ignored, converted at 3.70 ILS/USD (approximate). Israeli site locations
   are city level; the Be'er Sheva site is hypothetical.
4. **Wholesale versus retail**: see `price_kind` above. Do not mix the levels.
5. **Proxy hubs**: Iowa uses MISO Minnesota Hub, Wisconsin uses MISO Illinois Hub, One Wilshire
   (served by LADWP) uses CAISO SP15.
6. **Carbon** is an annual average, not hourly or marginal. Good for tCO2 per year estimates, not for
   hour-by-hour carbon-aware scheduling.
7. **Non-US retail prices** are placeholders. Replace with cited values before drawing conclusions.

### Synthetic price shape

Used only where `price_kind = synthetic_shape`: a diurnal curve with a night trough, a small morning
ramp and an evening peak around 19:00 local time, scaled up in summer (June to September, cooling
load) and slightly in winter, 8 % lower on weekends, normalised to an annual mean of exactly 1.0 and
multiplied by the annual retail price. See `data_pipeline/fetch_prices.py::synthetic_shape`.

## Rebuilding

The GitHub Actions workflow `Build location database` runs on every push that touches
`data_pipeline/` (or manually from the Actions tab), fetches everything, commits the Parquet files
and attaches `heatbeat.db` as a workflow artifact. Locally (needs internet):

```bash
pip install -r requirements.txt
python -m data_pipeline.build_db           # real data, cached in data/cache
python -m data_pipeline.build_db --stage weather   # or regions / prices --iso CAISO / assemble
python -m data_pipeline.build_db --offline # synthetic placeholders, only to test code
python -m pytest -q
```

To add a site: append a row to `data_pipeline/sites.csv` (reuse an existing `grid_region_id` or add
one to `grid_regions.csv`) and push. The workflow fetches only what is not cached yet.
