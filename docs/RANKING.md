# Ranking engine (`heatbeat_ranking`)

Python port of the team Excel model "Hack data.xlsx" (v3.0-SI-Diurnal-DualGrade). For one data
center it scores 13 heat recovery options: binary knock-out gates, a techno-economic viability score
from 0 to 5 (35 % thermo COP, 30 % climate/geo, 25 % economics, 10 % utilization) and an ecological
grade A to F (40 % GHG, 30 % water, 30 % habitat).

```python
from heatbeat_ranking import evaluate, excel_example_inputs, excel_example_t_amb, rank_site

evaluate(excel_example_inputs(), excel_example_t_amb(), mode="excel")   # the Excel, exactly
df, inputs, provenance = rank_site("us-va-ashburn-equinix")             # a real site, corrected mode
```

Command line: `python -m heatbeat_ranking --excel-example` or
`python -m heatbeat_ranking us-tx-abilene-stargate --greenfield 1`.

## Two modes

| | `excel` | `corrected` (default for sites) |
|---|---|---|
| Purpose | Reproduce the team Excel cell by cell | Defensible numbers for the demo |
| Heat pump | `W = Q / COP`, COP unbounded | `W = Q_source / (COP - 1)`, 2.5 K approach, COP cap 8 |
| GHG counterfactual | always "replaces gas" | per option (chiller, grid, RO, captured CO2, gas) |
| Cooling plant baseline | not modelled | water and fan power saved by reuse |
| Outputs | score, grade, net value | plus tCO2, m3, USD/yr, CAPEX, payback, PUE/WUE/ERE |
| Ties | Excel RANK (shared ranks) | broken by net annual value |

Why each change was made: [`heatbeat_ranking/AUDIT.md`](../heatbeat_ranking/AUDIT.md).
`tests/test_ranking_excel.py` checks every output column of all 13 options against the cached
Excel values for its example site, so the port cannot drift from the Excel unnoticed.

### Excel example site: both modes

| Option | Excel rank | Excel score | Excel COP | Corrected rank | Corrected score | Corrected COP | Payback yr (unverified CAPEX) |
|---|---|---|---|---|---|---|---|
| Biomass Processing | 1 | 5.00 | 33.8 | 6 | 4.35 | 8.0 | 1.6 |
| Industrial Drying | 2 | 4.65 | 11.6 | 5 | 4.35 | 8.0 | 1.7 |
| Biogas Generator | 3 | 4.60 | no HP | 1 | 4.60 | no HP | 1.4 |
| Fish Farm | 4 | 4.35 | no HP | 2 | 4.60 | no HP | 3.1 |
| Carbon Capture / DAC | 5 | 4.15 | 6.1 | 8 | 3.75 | 5.2 | 47.0 |
| Co-Designed Greenhouse | 5 | 4.15 | no HP | 4 | 4.40 | no HP | 2.0 |
| Boiler Feedwater Preheat | 7 | 4.10 | no HP | 3 | 4.60 | no HP | 0.5 |
| District Heating | 8 | 3.85 | 33.8 | 7 | 3.80 | 8.0 | 3.3 |
| Radiant / Snow-Melt | 9 | 3.25 | no HP | 9 | 3.55 | no HP | 3.8 |
| Absorption Cooling, ORC, BTES/ATES, Desalination | KO | 0 | | KO | 0 | | |

The Excel ranked Biomass first mainly because of the unbounded COP (33.8 gives the full thermo score).
Payback numbers rest on unverified CAPEX placeholders and are not results.

## Weather

Sites use real hourly 2024 dry bulb temperature from `heatbeat_data` (local time, 29 February
dropped so the Excel's 8760 hour thresholds still apply). `weather="daily_cosine"` rebuilds the hours
from daily min/max with the Excel cosine, to show the difference between both methods.

## Inputs: where each one comes from

`site_inputs(site_id)` returns the 31 Excel keys plus 4 corrected mode keys, and a provenance entry per
key with `status` = `data`, `assumption` or `user`. The UI should show the status next to every number.

Already wired to real data: `cooling_type`, `t_dc_base_c`, `q_dc_mw`, `pue` (data center profiles,
mostly estimates), `p_elec_usd_kwh`, `ci_grid_g_kwh` (location database), and, once PR 12 is on the
branch, `p_fuel_usd_kwh`, `p_steam_usd_mwh`, `p_co2_usd_ton`, `ci_fuel_g_kwh` from
`heatbeat_data.excel_inputs`, and `eco_sens_index`, `geo_storage_score`, `mit_tier` from
`heatbeat_data.excel_ecology_inputs` (PR 17; `mit_tier` is a rule based default and stays flagged).

Data threads hand over the rest as `data_pipeline/site_ranking_inputs_<topic>.csv`, long format:

```
site_id,key,value,status,source,note
us-va-ashburn-equinix,d_water_m,1850,data,USGS NHDPlus HR,Broad Run
```

Every such file is picked up automatically (name order, the later file wins).

### Missing inputs ranked by how much they change the result

Method: `heatbeat_ranking.input_influence`, one at a time swing of each input over its plausible US
range (`INPUT_SPEC`), all 40 US sites, corrected mode, existing (greenfield 0) and greenfield (1).
Measured: KO gates that flip, how often the top option changes, mean absolute score change.
**Caveat:** run on the offline database with synthetic weather (the cloud session cannot reach
Open-Meteo). Rerun with real weather on a machine with internet; the order may shift slightly.
Inputs that only matter together (district heating trio, power plant pair) show as zero in a one at a
time test; they are listed in tier 3 with that note.

| Tier | Input | Effect (existing / greenfield) | US source proposal | Default while missing (flagged) |
|---|---|---|---|---|
| 1 | `is_greenfield` | flips 3 gates and unlocks 7 options | UI toggle | 0 for operating sites |
| 1 | `d_bio_m` | flips biogas (and biomass); top option changes at about 3 of 4 sites | EPA AgSTAR farm database, NREL biomass resource, USDA food processing plants | 15 km |
| 1 | `wsi_index` | flips fish farm, greenhouse, absorption, desalination | WRI Aqueduct 4.0 baseline water stress | 2.0 |
| 1 | `t_dc_base_c` | top option changes at about 1 of 2 sites | already in data center profiles; refine per site | profile value |
| 1 | `d_water_m` | flips fish farm | USGS NHDPlus HR, nearest perennial river or lake | 2 km |
| 1 | `flat_land_m2` | flips fish farm | county parcel data or NLCD 2021 open land in 500 m | 10,000 m2 |
| 1 | `ind_zoning` | flips biomass and drying (greenfield) | county zoning maps | 1 (DC parcels usually industrial) |
| 1 | `d_co2_m` | flips DAC | EPA GHGRP subpart RR, Class VI permits, CO2 pipeline maps | 100 km (DAC KO) |
| 2 | `geo_storage_score` | flips BTES/ATES (greenfield) | USGS principal aquifers, state geological surveys | 3 |
| 2 | `d_coast_m` | flips desalination (greenfield) | NOAA shoreline, USGS brackish groundwater assessment 2016 | 100 km (KO) |
| 2 | `agri_land_m2` | flips greenhouse (greenfield) | USDA Cropland Data Layer in 1 km | 0 (KO) |
| 2 | `campus_area_m2` | flips snow melt (greenfield) | master plan (greenfield only) | 0 (KO) |
| 2 | `p_fuel_usd_kwh` | largest score change without a gate | EIA state natural gas prices (market thread, PR 12) | 0.035 USD/kWh_th |
| 2 | `p_elec_usd_kwh` | changes the top option at 1 of 4 greenfield sites | location database (done) | data |
| 2 | `d_market_m` | changes fish and greenhouse value | distance to food distribution hubs | 50 km |
| 3 | `has_existing_dh`, `d_dh_m`, `rho_heat_mwh_m` | only together; district heating stays KO in the US without all three | DOE / IDEA district energy list, Census urban areas, NREL ResStock/ComStock | 0, 5 km, 1.0 (KO) |
| 3 | `d_pp_m`, `q_fw_mw` | only together; boiler feedwater | EIA-860 thermal plants | 5 km, 0 MW (KO) |
| 3 | `dz_m` | only with `d_coast_m` | USGS 3DEP DEM | 50 m |
| 3 | `slope_deg` | only on hilly sites (gates at 6 to 10 degrees) | USGS 3DEP DEM, 1 km buffer | 2 degrees |
| 3 | `eco_sens_index` | eco grade only, no effect on viability | USFWS critical habitat, PAD-US | 2 |
| 3 | `p_steam_usd_mwh`, `p_water_usd_m3`, `p_co2_usd_ton`, `p_dac_credit_usd_ton` | value only, options mostly KO by default | market and water threads | see INPUT_SPEC |

## Sensitivity (tornado)

`tornado(inputs, t_amb, "fish_farm")` swings every numeric input between its low and high value and
returns the effect on one option's net annual value (or any other column via `metric=`). That is the
data for the tornado chart the brief asks for. The carbon price is in the swing list (0 to 100 USD/t).

## Known limits

- The heat sink is never sized (AUDIT finding 5): MWh, tCO2 and USD are upper bounds.
- CAPEX per option is a rough placeholder, so payback is indicative only.
- Eco water and habitat scores barely differ between options (AUDIT finding 10).
