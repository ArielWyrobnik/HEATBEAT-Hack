# Water per data center: price, water stress, baseline WUE

Adds the water side of the baseline for the 40 US sites: what water costs at each site, how
stressed the local water supply is, and how much water the site's cooling uses today. Solution
models use this to turn "m3 of water saved" into money and into a water score.

US only for now. Israel and the other countries are not covered yet.

## Files

| Path | What |
|---|---|
| `data_pipeline/site_water.csv` | One row per US `site_id`: utility, water and sewer tariff (mid, low, high, USD/m3), basis, flags, sources |
| `data_pipeline/wue_profiles.csv` | Per cooling profile: how heat is rejected (tower, dry, adiabatic) and an annual WUE range |
| `data_pipeline/aqueduct_sites.csv` | WRI Aqueduct 4.0 water stress per site. **Not in the repo yet**, see below |
| `data_pipeline/fetch_aqueduct.py` | Writes `aqueduct_sites.csv` (needs internet and geopandas, run once) |
| `data_pipeline/site_ranking_inputs_water.csv` | Long format hand-over for the ranking engine (`site_id,key,value,status,source,note`) |
| `data_pipeline/water_sources.csv` | Citations |
| `heatbeat_data/water.py` | Joins everything, hourly WUE model, annual water volume and cost |

## Quick start

```python
import heatbeat_data as hd

w = hd.site_water()                          # DataFrame, one row per US site
hd.site_water_row("us-az-chandler")          # one row as a dict, no DB or network needed
hd.get_site("us-az-chandler").water()        # same, with WUE computed from the site's hourly weather
hd.hourly_wue(site.weather, "dlc_warm")      # hourly L/kWh series for your own model
hd.water.write_ranking_inputs()              # refresh the ranking engine CSV
```

## Field names

`p_water_usd_m3` and `wsi_index` are the names in the team Excel (sheet `1_Site_Inputs_Schema`).

| Column | Meaning |
|---|---|
| `p_water_usd_m3` (`_low`, `_high`) | Volumetric water supply charge for a large non-residential customer, USD/m3. Fixed meter charges excluded |
| `p_sewer_usd_m3` (`_low`, `_high`) | Volumetric sewer charge, USD/m3. Paid only on water that goes to the sewer |
| `p_water_effective_usd_m3` | `p_water + discharge_share * p_sewer`: what one m3 of cooling water really costs |
| `wsi_index` | Aqueduct 4.0 baseline water stress score, 0 (low) to 5 (extremely high). Column `bws_score` |
| `wue_l_kwh` (`_low`, `_high`) | Site WUE: litres of on-site water per kWh of IT energy (The Green Grid definition) |
| `wue_method` | `hourly_weather` (computed from the site's weather) or `profile_default` (annual default of the cooling profile) |
| `discharge_share` | Share of withdrawn water sent to the sewer: `1/COC` for towers (0.25 at 4 cycles), about 0.17 for evaporative media, 0 for dry systems |
| `water_m3_yr` (`_low`, `_high`) | `wue_l_kwh * it_load_mw * 8760`. Low and high combine the WUE range with the IT load range |
| `water_cost_usd_yr` (`_low`, `_high`) | `water_m3_yr * p_water_effective_usd_m3` |
| `tariff_basis` | `tariff` (read from the utility's published schedule) or `estimate` |
| `water_is_estimated`, `sewer_is_estimated` | 1 = synthetic number. **Flagged per the team rule** |
| `confidence` | `high` (current official schedule, clear class), `medium` (official but older, class unclear or partly missing), `low` (estimate) |

## How the tariffs were collected

For each site we picked the utility that serves the address (city utility, county authority or
water district) and read its current published rate schedule for commercial, industrial or general
service customers. We took the volumetric rate a large customer pays (a data center uses roughly
50,000 to 3,000,000 m3 per year, so it sits in the top block of tiered tariffs) and converted it:
1,000 US gal = 3.785 m3, 1 CCF (100 cubic feet) = 2.832 m3.

Ranges: `low` and `high` cover tier choice (for example Loudoun Water Tier 1 within reserved capacity
versus Tier 2 above it), inside versus outside city rates, and known surcharges. For estimated sites
the range is deliberately wide.

24 of 40 sites have a real water tariff; 16 are estimates bracketed by neighbouring utilities, and
22 sewer values are estimates. Cross-check: the MLGW 2026 rate survey of about 40 US cities ranks
the same order (Boston, Los Angeles, Miami, Atlanta expensive; Memphis, Omaha, Reno cheap).

Things a model should know:

- **Sewer matters as much as water.** In Atlanta, Boston and NYC the sewer rate is higher than the
  water rate. Evaporated water never reaches the sewer, so only blowdown is billed (NYC has formal
  wastewater allowances for this; most utilities need a sub-meter).
- **Quincy WA** charges data centers 1.00 USD per 100 cf for water but 11.50 USD per 100 cf for
  discharged cooling water, which pushes operators to reuse it.
- **Reclaimed water**: Google Douglas County and Microsoft Cheyenne cool partly with treated
  wastewater, so the potable tariff overstates their real cost.
- Fixed charges (meter, availability, SNWA daily infrastructure charge in Las Vegas) are left out.
  They are large in absolute terms but do not change with water saved.

### Tariffs per site

| Site | Utility | Water USD/m3 (range) | Sewer USD/m3 (range) | Basis |
|---|---|---|---|---|
| `us-az-chandler` | City of Chandler | 0.72 (0.72 to 1.01) | 1.33 (1.33 to 2.13) | tariff |
| `us-az-mesa` | City of Mesa (rate book sections not readable) | 1.00 (0.72 to 1.50) | 1.20 (0.95 to 1.60) | **estimate** |
| `us-ca-la-one-wilshire` | LADWP (water); City of LA Sanitation (sewer, not found) | 3.72 (3.72 to 5.13) | 2.30 (1.80 to 3.00) | tariff, sewer **estimate** |
| `us-ca-santa-clara` | City of Santa Clara Water & Sewer Utilities | 3.49 (3.49 to 3.49) | 2.00 (1.50 to 3.00) | tariff, sewer **estimate** |
| `us-fl-miami-equinix` | Miami-Dade Water and Sewer Department | 2.50 (1.45 to 3.56) | 2.88 (2.85 to 2.88) | tariff |
| `us-ga-atlanta-qts` | Atlanta Department of Watershed Management | 2.18 (2.18 to 2.64) | 5.54 (4.00 to 5.54) | tariff |
| `us-ga-douglas-google` | Douglasville-Douglas County WSA (not researched) | 2.00 (1.50 to 2.60) | 2.50 (2.00 to 5.50) | **estimate** |
| `us-ia-altoona-meta` | City of Altoona | 1.93 (1.93 to 1.93) | 2.59 (2.59 to 2.59) | tariff |
| `us-ia-council-bluffs-google` | Council Bluffs Water Works / City of Council Bluffs | 0.83 (0.72 to 1.43) | 1.61 (1.61 to 1.61) | tariff |
| `us-ia-west-des-moines-microsoft` | West Des Moines Water Works / City of West Des Moines | 1.73 (1.73 to 1.73) | 1.67 (1.67 to 1.67) | tariff |
| `us-il-chicago-cermak` | City of Chicago | 1.29 (1.29 to 1.36) | 1.29 (1.29 to 1.36) | tariff |
| `us-il-elk-grove` | Village of Elk Grove Village (not researched) | 1.80 (1.30 to 3.00) | 1.00 (0.60 to 1.50) | **estimate** |
| `us-la-richland-meta` | Richland Parish (not researched) | 1.00 (0.60 to 1.80) | 1.20 (0.80 to 2.00) | **estimate** |
| `us-ma-boston-one-summer` | Boston Water and Sewer Commission | 3.36 (3.32 to 3.37) | 4.42 (4.33 to 4.45) | tariff |
| `us-nc-lenoir-google` | City of Lenoir (not researched) | 2.00 (1.30 to 2.80) | 2.50 (1.50 to 3.50) | **estimate** |
| `us-nc-maiden-apple` | Town of Maiden (not researched) | 2.00 (1.30 to 2.80) | 2.50 (1.50 to 3.50) | **estimate** |
| `us-ne-sarpy-meta` | Metropolitan Utilities District (water); sewer municipality not found | 0.79 (0.69 to 1.20) | 1.40 (1.00 to 2.00) | tariff, sewer **estimate** |
| `us-nj-secaucus-equinix` | Secaucus MUA / Veolia NJ (not researched) | 2.50 (1.80 to 3.50) | 2.50 (1.50 to 3.50) | **estimate** |
| `us-nv-las-vegas-switch` | Las Vegas Valley Water District + SNWA (water); Clark County WRD (sewer, not found) | 1.26 (0.90 to 1.79) | 0.80 (0.50 to 1.20) | tariff, sewer **estimate** |
| `us-nv-reno-switch` | Truckee Meadows Water Authority (water); sewer provider not found | 0.65 (0.47 to 1.08) | 1.20 (0.80 to 2.00) | tariff, sewer **estimate** |
| `us-ny-nyc-60-hudson` | NYC Water Board / DEP | 1.89 (1.89 to 1.89) | 3.01 (1.50 to 3.01) | tariff |
| `us-oh-new-albany` | City of Columbus (contract / suburban rates) | 1.67 (1.67 to 2.53) | 2.36 (2.36 to 2.36) | tariff |
| `us-ok-pryor-google` | MidAmerica Industrial Park / City of Pryor (not researched) | 1.00 (0.60 to 1.50) | 1.00 (0.60 to 1.50) | **estimate** |
| `us-or-hillsboro` | City of Hillsboro / Clean Water Services (not found) | 1.80 (1.30 to 2.50) | 2.50 (1.80 to 3.50) | **estimate** |
| `us-or-prineville-meta` | City of Prineville (not researched) | 1.50 (1.00 to 2.50) | 2.00 (1.20 to 3.00) | **estimate** |
| `us-or-the-dalles-google` | City of The Dalles (not researched) | 1.50 (1.00 to 2.50) | 2.00 (1.20 to 3.00) | **estimate** |
| `us-sc-berkeley-google` | Berkeley County Water & Sanitation (volumetric rates not found) | 1.60 (1.00 to 2.50) | 2.20 (1.50 to 3.00) | **estimate** |
| `us-tn-memphis-xai` | Memphis Light, Gas and Water (water); City of Memphis (sewer, not found) | 0.47 (0.45 to 0.58) | 1.00 (0.70 to 1.50) | tariff, sewer **estimate** |
| `us-tx-abilene-stargate` | City of Abilene (not researched) | 1.30 (0.90 to 2.00) | 1.30 (0.90 to 1.80) | **estimate** |
| `us-tx-dallas-infomart` | Dallas Water Utilities | 1.55 (1.41 to 2.27) | 1.47 (1.47 to 1.47) | tariff |
| `us-tx-midlothian-google` | City of Midlothian (not researched) | 1.30 (0.98 to 1.80) | 1.50 (1.20 to 2.00) | **estimate** |
| `us-tx-san-antonio-microsoft` | San Antonio Water System (SAWS) | 0.55 (0.52 to 1.18) | 1.15 (1.15 to 1.38) | tariff |
| `us-ut-eagle-mountain-meta` | Eagle Mountain City | 0.45 (0.41 to 0.53) | 1.22 (1.22 to 1.25) | tariff |
| `us-va-ashburn-equinix` | Loudoun Water | 1.17 (1.17 to 2.01) | 1.74 (1.74 to 1.74) | tariff |
| `us-va-boydton-microsoft` | Mecklenburg County / Town of Boydton (not researched) | 2.00 (1.20 to 3.00) | 2.50 (1.50 to 3.50) | **estimate** |
| `us-va-manassas` | Prince William Water | 1.28 (1.28 to 2.51) | 2.46 (2.46 to 2.46) | tariff |
| `us-va-sterling-digital` | Loudoun Water | 1.17 (1.17 to 2.01) | 1.74 (1.74 to 1.74) | tariff |
| `us-wa-quincy` | City of Quincy | 0.35 (0.35 to 0.35) | 4.06 (0.99 to 4.06) | tariff |
| `us-wi-mount-pleasant-microsoft` | Racine Water Utility / Racine Wastewater Utility | 0.85 (0.85 to 1.10) | 1.02 (0.67 to 1.02) | tariff |
| `us-wy-cheyenne-microsoft` | Cheyenne Board of Public Utilities (not researched) | 1.50 (1.00 to 2.20) | 1.50 (1.00 to 2.20) | **estimate** |

## Water stress (WRI Aqueduct 4.0)

`wsi_index` is the Aqueduct 4.0 baseline annual water stress score (`bws_score`, 0 to 5), the ratio
of total withdrawals to available renewable supply mapped to a 0 to 5 scale. Source: Kuzma et al.
2023, WRI, CC BY 4.0, https://www.wri.org/data/aqueduct-global-maps-40-data.

Status: `fetch_aqueduct.py` looks up the polygon that contains each site in the official Aqueduct
geodatabase. The download host (files.wri.org) is blocked in our cloud environment, so the script
has to run once on a laptop:

```
pip install geopandas pyogrio
python -m data_pipeline.fetch_aqueduct
python -c "import heatbeat_data.water as w; w.write_ranking_inputs()"
```

Until then `wsi_index` is empty (NaN) and the ranking CSV carries no `wsi_index` rows. We did not
put in guessed scores on purpose: the ranking engine uses thresholds at 2, 3.8 and 4, so a guessed
value would decide gates.

## Baseline WUE model

Two levels:

1. **Annual default per cooling profile** (`wue_profiles.csv`, used when no weather is loaded).
   Anchors: LBNL 2024 report (water-cooled chillers have the highest WUE, US average site WUE just
   over 0.36 L/kWh through 2023), Microsoft fleet WUE 0.27 L/kWh FY25 (Americas 0.34), and an arXiv
   2026 study implying about 3.7 L/kWh for water-cooled chillers without economizer and 0.12 for
   air-cooled chillers. Ranges are team assumptions within those anchors.
2. **Hourly model from weather** (`hourly_wue`, used by `get_site(...).water()`):
   - Cooling tower: every kWh of heat rejected evaporates 3600 / 2430 = 1.48 L (latent heat of water).
     Heat rejected per kWh IT is 1 plus chiller compressor heat (1/COP, COP 6) in hours where the wet
     bulb is above supply temperature minus 4 K. Blowdown multiplies by COC/(COC-1), 1.33 at 4 cycles.
   - Hybrid dry plus tower (liquid cooling): dry coolers (no water) when dry bulb is at or below the
     profile's `dry_max_db_c` (supply temperature minus about 8 K), tower otherwise. The air share of
     the heat goes through a tower on an 18 C chilled water loop.
   - Adiabatic air economizer: water only when dry bulb is above 24 C. Evaporation cools the intake
     air by min(t_db - 24, 0.85 (t_db - t_wb)) for an air flow sized for a 12 K rise across the IT.
   - Closed-loop dry: zero (used for Microsoft Mount Pleasant, which Microsoft describes as a zero
     water for cooling design).

All parameters except the latent heat are team assumptions and are module constants, so a
sensitivity run can vary them. The model ignores humidification water, drift and domestic use.

Example: an air-cooled colocation hall on towers (Ashburn, 200 MW IT) uses about 1.8 L/kWh, so
roughly 3.2 million m3 per year, about 5 million USD at Loudoun Water prices.

## Known gaps

- Aqueduct values: run `fetch_aqueduct.py` once (see above).
- 16 water and 22 sewer tariffs are estimates (listed above, flagged in the CSV).
- Some tariffs are older than 2026 (Racine 2020, MLGW 2022, Iowa survey 2024, Atlanta sewer table).
- Hourly WUE needs the site's weather, which `get_site()` fetches live from Open-Meteo.
