# DSX heat reuse evaluator (default ranking model)

`heatbeat_dsx` answers "which heat reuse pathway fits this data center best?" for every database site.
It is the default model of `/api/sites/{id}/ranking`, `/api/evaluate` and `/api/leaderboard`. The
engineering heat chain (`?model=heat_chain`) and the Excel ranking (`?model=excel_ranking`) stay
available, and the planner (`/api/plan`, `/api/plan/defaults`) keeps the heat chain as its default
because it sizes the whole design (budget, Vera Rubin racks).

## What goes in (closest to reality available)

| Input | Source |
|---|---|
| 31 site inputs (GIS, industry, water, ecology, market, cooling, IT load) | `heatbeat_ranking.site_inputs`: database values and the `site_ranking_inputs_*.csv` threads, each with status and source, US defaults flagged |
| Hourly ambient temperature | real 2024 hourly weather of the site (Open-Meteo ERA5, `heatbeat_ranking.climate.hourly_from_site`), not a daily cosine |
| Heat price and CO2 of displaced heat | `heatbeat_data.market`: EIA gas price by state and EPA factors, per kWh of heat from a 0.85 boiler |
| DAC revenue | 45Q credit for DAC with geologic storage (`p_dac_credit_usd_ton`, 180 USD/t) |
| Electricity price, grid CO2 | database grid region (EIA) |
| Baseline water | evaporative cooling unless the cooling profile is chiller free (`dlc_hot`) |

## How it scores

Per pathway (13): knock-out gates that state the site value and the limit it misses, then hourly
heat drawn, heat pump COP (Carnot based, capped), product, money and CO2, then

- viability = G x (0.30 P_thermo + 0.30 P_climate + 0.25 P_econ + 0.15 P_util), 0 to 5
- eco = 0.40 e_GHG + 0.30 e_water + 0.30 e_local, grade A >= 4.2, B >= 3.4, C >= 2.6, D >= 1.8, else F
- NPV = -CAPEX + net cash x annuity (20 years, 7 %, same convention as the engineering model)

Ranking is by viability, then eco score. All constants are DSX planning assumptions (see
`heatbeat_dsx/engine.py`); specific costs per kW and per metre are generic, so payback and NPV are
indicative.

## Checks

`tests/test_dsx.py`: the Python engine reproduces the frontend DSX engine (`frontend/src/dsx/engine.ts`,
PRs #52 to #63) on the same inputs (52 of 52 option results equal), weights, gate messages, energy
balance and the API contract. Against 11 real heat reuse deployments the DSX ranking put the real
project in its top 3 in 7 cases (Excel ranking: 1).
