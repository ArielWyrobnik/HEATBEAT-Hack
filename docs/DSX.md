# DSX heat reuse evaluator (Heat waste perspective)

`heatbeat_dsx` answers "which heat reuse pathway fits this data center best?". HEATBEAT shows every site
from two perspectives (frontend/src/perspectives.ts):

- **Cooling**: the engineering heat chain (default model) and its heat rejection options, unchanged.
- **Heat waste**: scored by DSX. The site panel's Heat waste tab calls `/api/sites/{id}/ranking?model=dsx`
  and lists the most viable pathways with viability 0 to 5, eco grade, "Where the server heat goes"
  (heat loops) and every knocked-out pathway with its reason. The leaderboard's heat columns
  (`heat_option_name`, `heat_reused_mwh_yr`, `heat_pays_off`, ...) come from the DSX rank 1 pathway;
  it pays off when its NPV is positive.

The planner keeps the engineering model (budget sizing, Vera Rubin racks); `?model=dsx` also plans.

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

## Investment costs

| Item | Value | Source |
|---|---|---|
| Heat pump | 700 USD/kW_th | Danish Energy Agency technology data, large electric heat pumps 0.4 to 1.0 M USD/MW (as heatbeat_engineering) |
| District heating pipe | 3,150 USD/m | DN300, 960 USD/ft 2025 planning price, City of Cambridge MA Low Carbon Energy Supply Strategy, Appendix 5 |
| Absorption chiller | 185 USD/kW heat in | 930 USD/RT at 440 RT single effect with cooling tower (US DOE data, Cornell 2020) = 264 USD/kW_cold x COP 0.7 |
| ORC | 3,000 USD/kW_e | small low temperature ORC 2,000 to 4,500 USD/kW_e, Quoilin et al. 2013 |
| ATES / BTES | 330 USD/kW | ATES about 300 EUR/kW above 2 MW, 133 systems, Herrmann et al. 2025 |
| MED desalination | 800 USD/kW_th | 2,000 USD per m3/day (Al-Karaghouli and Kazmerski 2013) at 60 kWh_th/m3 |

Still DSX planning values (unverified, named in the result warnings): fish farm, district heating plant
part, biogas, DAC, feedwater preheat, biomass processing, industrial drying, snow melt, greenhouse.

## Calibration against real deployments (v3.4)

The 11 reference pins in the DSX frontend are real heat reuse projects. With each pin's sourced inputs,
the model should put the real pathway near the top. Two changes, both physical rather than fitted:

1. BTES / ATES is charged only with surplus heat in the warm part of the year (0 at 10 C, full at 20 C)
   instead of a flat 70 % all year: a seasonal store takes summer heat and returns it in winter.
2. BTES / ATES needs a heat user to discharge to (existing heat network, or one within 3 km).

3. Fish farm and digester zoning accept industrial zoning **or** at least 2 ha of farmland within 1 km.
   The database `ind_zoning` is an OSM proxy that only sees industrial land use, so rural campuses on
   farmland (Iowa, Nebraska, Virginia) were treated as urban and lost every option.

Database sites also get two input corrections in the model: air sites on a chilled water plant use the
32 C exhaust air (team cooling profile) instead of the 13 C chilled water return as heat temperature.

Plus one data fix: High Tech Campus Eindhoven is an office and lab campus, so no industrial zoning
(same rule as Amsterdam Science Park and Saint-Denis).

| Real project | Real pathway | v3.3 rank | v3.4 rank |
|---|---|---|---|
| Green Mountain Rjukan | fish farm | 1 | 1 |
| Equinix AM3 | ATES | 1 | 1 |
| NorthC Eindhoven | ATES | 1 | 1 |
| Echelon Arklow | biogas | 1 | 1 |
| Westin Seattle | district heating | 1 | 1 |
| EcoDataCenter Falun | drying / biomass | 2 | 1 |
| Nebius Mantsala | district heating | 3 | 2 |
| Equinix PA10 | district heating | 2 | 2 |
| Civo (Orbital) | DAC | 3 | 3 |
| Syracuse University | absorption cooling (runs on microturbine exhaust, not server heat) | out | out |
| Trevi at NELHA Kona | desalination (pilot; water stress is an estimate) | out | out |

Top 1: 5 to 6 of 11, top 3: 9 of 11. Not fixed on purpose: Mantsala ranks industrial drying first
because nothing in the inputs says there is no dryer customer nearby, and Civo's real site is not
public (pin in London, default zoning).

## Checks

`tests/test_dsx.py`: the Python engine reproduces the frontend DSX engine (`frontend/src/dsx/engine.ts`,
PRs #52 to #63) on the same inputs (91 of 91 option results equal over 7 input sets), weights, gate messages, energy
balance and the API contract. Against 11 real heat reuse deployments the DSX ranking put the real
project in its top 3 in 7 cases (Excel ranking: 1).
