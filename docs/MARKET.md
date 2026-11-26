# Market prices for solution outputs

`data_pipeline/market_prices.csv` holds the prices that turn each solution's physical output
(MWh of heat, kg of fish, tCO2, RNG) into money. It is keyed like `sites.csv`: `country_iso2` +
`region` (US state code). `region = "*"` is the national default used when no state row exists.

Build: `python -m data_pipeline.build_market_prices` (no network; all inputs are transcribed in
the script with their source). Access:

```python
import heatbeat_data as hd
hd.excel_inputs("us-tx-abilene-stargate")      # team Excel economics keys + p_dac_credit_usd_ton
hd.site_market("us-tx-abilene-stargate")       # every item for that site's state
hd.site_market(sid, grid_co2_g_kwh=380)         # adds ci_heat_mix_g_kwh_th incl. electric heating
hd.market_for("US", "CA", detail=True)          # value, low, high, unit, year, is_estimate, source_url, note
```

Columns: `value`, `low`, `high` (range for the tornado chart), `unit`, `year`, `category`,
`is_estimate` (1 = derived with an assumption, or synthetic), `source_id`, `source_url`, `note`.

## Why API access is not used yet

The cloud build container gets HTTP 403 from api.eia.gov, quickstats.nass.usda.gov and NOAA. All
values were therefore transcribed on 2026-11-26 from the published tables below. The EIA API
series that would replace them later: `natural-gas/pri/sum` (state prices by sector),
`petroleum/pri/wfr` (heating oil and propane, SHOPP states).

## Which solution needs which price

| Solution (catalogue id) | Revenue or saving | Items |
|---|---|---|
| district_heating_4gdh / 5gdh, domestic_hot_water, pool_heating, heat_pump_booster | displaced gas boiler heat | `p_fuel_usd_kwh`, `heat_cost_gas_*`, `district_heat_tariff_usd_mwh_th` (synthetic), `ci_fuel_g_kwh`, `ci_heat_*` |
| greenhouse_heating | displaced heat + produce | `p_fuel_usd_kwh`, `tomato_greenhouse_usd_lb`, `tomato_field_roma_usd_lb` |
| aquaculture_ras | fish sales + displaced heat | `tilapia_import_usd_lb`, `catfish_farmgate_usd_lb`, `trout_farmgate_usd_lb`, `shellfish_aquaculture_usd_lb`, `seafood_import_share_pct`, `seafood_landings_*`, `fish_local_price_premium` (synthetic) |
| anaerobic_digestion | biogas or RNG | `ng_citygate_usd_mmbtu` (commodity value), `rin_d3_usd`, `rng_d3_value_usd_mmbtu`, `lcfs_credit_usd_t` (CA, OR) |
| low_temp_drying, microalgae | dried biomass | `wood_pellet_domestic_usd_ton`, `wood_pellet_export_usd_ton` |
| dac_solid_sorbent | CO2 removal | `p_dac_credit_usd_ton` (45Q DAC 180), `credit_45q_*`, `lcfs_credit_usd_t` (CA) |
| boiler feedwater preheat (team Excel) | displaced bleed steam | `p_steam_usd_mwh` |
| adsorption / absorption chiller, orc_power, cooling options | saved electricity | from the location database (`site.grid`), not here |
| swro_feed_preheat, med_desalination, membrane_distillation | water | water price data (separate dataset) |
| all | carbon value of avoided emissions | `p_co2_usd_ton` = `co2_compliance_usd_t` (CA, WA, RGGI states, else 0) |

## Items and sources

**Natural gas, 2024, per state** (`ng_citygate/residential/commercial/industrial_usd_mcf`): EIA
Natural Gas Annual 2024, [Table 22](https://www.eia.gov/naturalgas/Annual/pdf/table_022.pdf) and
[Table 23](https://www.eia.gov/naturalgas/Annual/pdf/table_023.pdf).

**Heat cost of displaced boilers** (`heat_cost_*_usd_kwh_th`, `p_fuel_usd_kwh`): fuel price divided
by heat content and boiler efficiency. Assumptions (flagged): 1.036 MMBtu per Mcf, boiler
efficiency 0.85 (range 0.80 to 0.95), heating oil 40.59 kWh per gal, propane 26.80 kWh per gal.
`p_fuel_usd_kwh` uses the commercial gas price; low and high are the min and max over industrial,
commercial and residential. US default is 0.039 USD/kWh_th, about half the 0.075 placeholder in
the team Excel.

**Steam** (`p_steam_usd_mwh`): industrial gas price / (0.3036 MWh per Mcf x 0.85).

**Propane, heating oil** (`*_residential_usd_gal`): EIA
[Winter Fuels Outlook 2026-27](https://www.eia.gov/outlooks/steo/report/perspectives/2026/10-winterfuels/article.php),
forecast for Nov 2026 to Mar 2027. Propane by Census region (West not printed, US value used);
heating oil US only.

**District heat tariff** (`district_heat_tariff_usd_mwh_th`): SYNTHETIC. No US tariff dataset;
priced at avoided commercial gas boiler cost x 1.15 (range 1.0 to 1.4).

**Heating fuel mix** (`heat_mix_*_pct`): EIA
[RECS 2020 state space heating fuels](https://www.eia.gov/consumption/residential/data/2020/state/pdf/State%20Space%20Heating%20Fuels.pdf).
Withheld cells are empty. `ci_heat_fossil_mix_g_kwh_th` weights EPA CO2 factors (gas 53.06, oil
73.96, propane 62.87 kg/MMBtu, [EPA EF Hub](https://www.epa.gov/climateleadership/ghg-emission-factors-hub))
by the fossil shares. `ci_fuel_g_kwh` (Excel key) is the gas boiler value, 213 gCO2/kWh_th.

**Carbon markets** (`co2_compliance_usd_t`, USD per metric ton):
- CA 28.32: CARB/Quebec auction Nov 2025, [summary](https://ww2.arb.ca.gov/sites/default/files/2025-11/nc-nov_2025_summary_results_report.pdf); low = reserve 25.87.
- WA 39.50: Q3 2026 auction, [EDF](https://blogs.edf.org/climate411/2026/09/09/washington-cap-and-invest-sees-lowest-prices-in-years-following-linkage-agreement-with-california-and-quebec/); high = Q4 2025 70.86.
- MA, NJ, NY 38.58: RGGI Auction 72 (Jun 2026) 35.00 USD per short ton, [RGGI](https://www.rggi.org/sites/default/files/Uploads/Auction-Materials/72/PR060526_Auction72.pdf). Power sector only.
- VA 0 (high 38.58): ESTIMATE, Virginia left RGGI end of 2023; rejoining is open.
- Other states 0.
These costs are mostly already inside gas and power prices. Use them for a separate "carbon value"
view, not on top of `p_fuel_usd_kwh`.

**45Q** (`credit_45q_*`, `p_dac_credit_usd_ton`): 85 USD/t point source, 180 USD/t DAC with geologic
storage, utilization at parity since the One Big Beautiful Bill Act,
[Global CCS Institute](https://www.globalccsinstitute.com/u-s-preserves-and-increases-45q-credit-in-one-big-beautiful-bill-act/).

**RIN and LCFS** (Dec 2025 monthly averages,
[Aegis](https://aegis-hedging.com/insights/lcfs-rin-pricing-report-through-december-22nd-2025)):
D3 2.452 USD/RIN, D5 1.119; CA LCFS 53.37 USD/t (CARB Oct 2025 average 58, CY2024 64,
[CARB](https://ww2.arb.ca.gov/sites/default/files/2025-11/October%202025%20-%20Monthly%20LCFS%20Credit%20Transfer%20Activity.pdf));
Oregon CFP 157.50 USD/t. `rng_d3_value_usd_mmbtu` = D3 x 11.727 RIN/MMBtu, only for RNG sold as
transport fuel.

**Fish**:
- Import share 86 % (range 75 to 90), per capita 19.7 lb, landings by state 2022: NOAA
  [Fisheries of the US 2022](https://fisheries.noaa.gov/s3/2024-10/FUS-2022-final.pdf), Table 4.
  Inland states are not in Table 4 and get 0.
- Tilapia import price 1.50 to 2.00 USD/lb since 2015,
  [MSU Extension](https://extension.msstate.edu/newsletters/mississippi-marketmaker/2025/vol-15-no-8-tariffs-us-tilapia-imports-direct-revenues-and-impacts-prices).
- Catfish 1.11 USD/lb live 2025, [NASS](https://esmis.nal.usda.gov/sites/default/release-files/795763/cfpd0226.pdf).
- Trout foodsize 2.40 USD/lb US 2025 (NC 2.72, UT 5.15, WI 6.65),
  [NASS](https://esmis.nal.usda.gov/sites/default/release-files/795798/trpr0226.txt).
- `fish_local_price_premium`: SYNTHETIC. Supply class from landings value (none, low, medium,
  high) mapped to +10 %, +5 %, 0, -5 %. State level is coarse: TX counts as high because of the
  Gulf coast, although the TX data center sites are inland. Refine with the site distance to
  coast from the GIS data.

**Greenhouse produce** (`tomato_greenhouse_usd_lb` 1.45, range 0.65 to 2.20; `tomato_field_roma_usd_lb` 1.25):
derived from USDA AMS [Tomato Fax](https://www.ams.usda.gov/mnreports/fvdtomf.pdf) terminal prices,
17 Nov 2025 and 22 Oct 2026. Strongly seasonal.

**Wood pellets**: domestic 239.25, export 202.74 USD per short ton, Dec 2025,
[EIA](https://www.eia.gov/biofuels/biomass/?month=12&year=2025).

**Israel**: only `co2_tax_gas_2030_usd_t` (about 19 USD/t, ESTIMATE from the 2030 rate of 192 NIS
per ton of gas, [World Bank](https://carbonpricingdashboard.worldbank.org/compliance-factsheet/Tax_IL)).

## Known gaps

- Washington Clean Fuel Standard credit price, Israel gas, fish and produce prices: not found yet.
- Shrimp and salmon import prices, monthly catfish producer price.
- No state-level fish or produce retail prices; national values plus the synthetic premium.
