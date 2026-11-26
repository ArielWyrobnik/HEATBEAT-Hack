# Engineering heat chain model (`heatbeat_engineering`)

For one data center (a database site or a planned one at any point and size) the model builds every
feasible **heat chain**, simulates it hour by hour for a full year with explicit component physics,
closes the energy balance and compares it with the counterfactual (the site's existing cooling, no
reuse). Output per chain: MWh, tCO2, m3 water, USD per year, CAPEX, NPV, payback, PUE, WUE, ERE,
an energy flow list for a Sankey, a plain text "how it is built here", and a tornado for the best one.

```python
from heatbeat_engineering import evaluate, best_per_use

df, base, res, case = evaluate(site_id="us-ia-council-bluffs-google")   # database site
df, base, res, case = evaluate(41.6, -93.6, 1000, "dlc_hot")            # planned 1 GW site near Des Moines
best_per_use(df)                                                        # best chain per heat use family
```

Command line: `python -m heatbeat_engineering us-tx-dallas-infomart`,
`python -m heatbeat_engineering --plan 41.6 -93.6 1000 dlc_hot`,
`python -m heatbeat_engineering --all --offline` (writes `heatbeat_engineering/results/us_sites.csv`).
API: `heatbeat_engineering/api_model.py` (`MODEL.run` for sites, `MODEL.plan` for planned sites) plugs
into `heatbeat_api` (API thread) and fills `ModelResult` including `implementation` and `capex_breakdown`.

Why this replaces the scoring approach for the pitch: the team Excel (`heatbeat_ranking`, kept for
comparison, see `heatbeat_engineering/compare.py`) scores options on a 0 to 5 scale and never sizes
the heat sink. Here every MWh is traced from the chip loop to a sink or to ambient, so each number can
be explained with physics.

## Scope (decided with Ariel, 2026-11-26)

Kept or added: heat rejection choice, large heat pumps, district heating to the nearest community,
seasonal and daily storage, adsorption chilling, biogas digester heating, boiler feedwater preheat,
desalination (MED, MD), ORC. Dropped (not engineering enough for the NVIDIA brief): fish farm,
greenhouse, biomass drying, snow melt. DAC stays in the Excel model only.

## 1. Heat source

`site.load_site` reads the data center profile (`heatbeat_data.heat_profile`, mostly team estimates):
two loops, each with heat (MW), supply and return temperature.

| Cooling profile | Liquid loop | Air side loop |
|---|---|---|
| `dlc_hot` (Rubin class) | 95 % at 55/45 C | 5 % at 26/18 C |
| `dlc_warm` | 90 % at 42/32 C | 10 % at 26/18 C |
| `tpu_dlc` | 40 % at 42/32 C | 60 % at 26/18 C |
| `air_chilled_elevated` / `_legacy` | none | 100 % at 26/18 C or 13/7 C |
| `air_economizer` | none | 100 %, exhaust 32 C, supply air 24 C |

All IT electricity becomes heat. Planned sites: `load_location(lat, lon, it_mw, cooling_profile)`.

## 2. Heat rejection ("radiator"): `heat_rejection.py`

Each technology approaches an effective air temperature:

| Technology | Leaving fluid temperature | Water |
|---|---|---|
| Dry cooler | `T_db + 6 K` | none |
| Adiabatic cooler | `T_db - 0.8 (T_db - T_wb) + 6 K` only when dry is not enough | `Q eff (T_db - T_wb) / (air range h_fg)` in wetted hours |
| Cooling tower | `T_wb + 4 K + 1.5 K (plate HX)` | evaporation `Q x 0.85 / h_fg` plus blowdown `/(cycles - 1)`, about 1.6 to 1.9 m3/MWh |

If the leaving temperature is above the loop supply temperature, a **trim chiller** removes the rest
(series economizer): chiller share = `(T_leave - T_sup)/(T_ret - T_sup)`, COP = 0.5 x Carnot, capped at 7.
**Fan power** follows the fan affinity law: air flow ~ `Q / (T_ret - T_air)`, power ~ flow cubed,
normalised to the design point (full load at the hottest hour). The cooler is always sized for the full
loop load, because it is the backup whenever the heat user is off.

This is where location matters most in the US: Atlanta (water + sewer 3.6 USD/m3) saves about
10.5 M USD/yr by going from towers to dry coolers despite more chiller hours; Mesa (WSI 5 but 1.3 USD/m3
water) keeps the tower.

## 3. Heat pump: `heat_pump.py`

`COP = 0.5 x T_cond / (T_cond - T_evap)` with `T_evap = T_source - 5 K - 2.5 K`,
`T_cond = T_sink + 2.5 K`, capped at 8 (Carnot fraction 0.4 to 0.6, Arpagaus et al. 2018).
Balance: `Q_cond = Q_evap + W`. The evaporator heat leaves the DC loop, so it is not rejected.
A plain heat exchanger is used when `T_source - 3 K >= T_sink`.

## 4. Heat uses

| Use | Physics in the model | Site data used | KO rule |
|---|---|---|---|
| District heating (`district_heating.py`) | Demand = linear heat density x network length (5, 20 or 60 km), split over heating degree hours (base 16 C) plus 20 % flat hot water. Twin pre-insulated line: DN from 2 m/s, `U' = 0.12 + 0.0008 DN` W/mK per pipe, loss `U' L (T_s + T_r - 2 T_g)`, pumps `V dp / eta` with 100 Pa/m, distribution loss 12 %. 70/40 C (4GDH). | `d_dh_m`, `rho_heat_mwh_m`, local gas heat cost | line > 20 km |
| Storage (`district_heating.shift`) | Daily tank (eta 0.95) or seasonal ATES (0.75) / BTES (0.55): heat pump output in hours with spare source heat goes to hours with unmet demand, charge rate limited by the heat pump size. | `geo_storage_score` | score < 3 for ATES/BTES; no unmet demand |
| Biogas digester (`biogas.py`) | `Q = m cp (T_dig - T_feed) + U A (T_dig - T_air)`, hourly, mesophilic 38 C or thermophilic 55 C. Two cases. **Existing digester** (EIA digester gas plant): size from its generator capacity (CF 0.7, 35 % electrical), heat line, DC heat frees the biogas its boiler burns, sold as RNG (gas + D3 RIN + LCFS in CA, OR, WA). **New plant** (food processing waste, manure): size optimised per site over 50 to 3000 t/day and heat line vs trucking, by plant NPV with DC heat. Economies of scale: digester CAPEX ~ size^0.7, upgrading ~ size^0.6 (Bauer et al. 2013). Limit: feed beyond the 300 t/day anchor is collected regionally (0.1 t/day per km2), so trucking grows with size and the radius must stay below 50 km. The chain counts only what the DC heat adds: the counterfactual is the same plant heating itself, so digester CAPEX cancels; plant NPV with and without DC is in the details. All sizing inputs UNVERIFIED. | `d_bio_m`, feedstock kind and EIA capacity, RIN/LCFS, climate | > 50 km; forestry feedstock |
| Adsorption chiller (in `chains.py`) | Liquid loop drives silica gel adsorption (COP 0.55, drive >= 50 C), cold replaces trim chiller load of the air loop, recooler must stay below 29 C. LiBr needs 75 C: the model shows that a heat pump driven LiBr gives less cold per kWh than an electric chiller. | loop temperatures, climate | drive < 53 C, no air side load |
| Boiler feedwater (`industry.py`) | Preheats condensate to 50 C, replaces LP extraction steam: +0.15 MWh_e per MWh_th turbine output at the hourly market price. | `d_pp_m`, `q_fw_mw` (EIA-860) | > 15 km |
| Desalination MED / MD (`industry.py`) | MED effects `n = (T_steam - T_sea - 5)/3 K`, GOR 0.85 n, heat `647 kWh/m3 / GOR`; MD GOR 2. Counterfactual SWRO 3.5 kWh_e/m3. | `d_coast_m`, water tariff | coast > 10 km; < 2 effects |
| ORC (`industry.py`) | `eta = 0.4 (1 - T_cond/T_hot)`, `T_cond = T_db + 10 K`, only in hours with > 20 K difference. About 3 to 5 % at 55 C, the honest answer. | climate | source < 80 C (Vertiv testbed: net loss at 58 to 63 C, see docs/VALIDATION.md); never 20 K above condenser |

## 5. Chains, balance, counterfactual: `chains.py`

A chain is one heat rejection technology plus up to two uses (plus storage with district heating):
about 100 to 450 chains per site, about 0.5 s per site. Uses with a fixed demand take heat first,
desalination and ORC take what is left. The energy balance is checked in every run:

`IT heat + heat pump work + chiller work = heat rejected + heat delivered + pipe and storage losses + adsorber recooling`

The residual is below 1e-8 MWh for every chain at every US site (tested in `tests/test_engineering.py`).

The **baseline** is the same simulator with the existing technology of the cooling profile
(`site.BASELINE_REJECTION`, team assumption) and no uses. Every chain reports differences to it:

- `net_value_usd_yr` = baseline cost minus chain cost (electricity, water + sewer, water scarcity
  shadow price `WSI x 0.5 USD/m3`, carbon price where a state market exists, O&M) plus revenues.
  It is split into `cash_value_usd_yr` (real money) and `water_value_usd_yr` (the shadow price part,
  not cash); the panel shows both
- `delta_capex_usd`: new equipment; a different cooler is only charged when it differs from the
  existing one (operating sites) or always on greenfield sites
- `npv_usd` (7 %, 20 years), `payback_yr`, `co2_avoided_t_yr`, `water_saved_m3_yr`
- `reuse_npv_usd`: NPV of the heat use alone (chain minus the same cooler without a use)
- PUE = (IT + cooling + hall fans + 6 % overhead) / IT; WUE = site water / IT;
  ERE = (facility + reuse plant electricity - reused energy) / IT (The Green Grid definition)

## 6. Sensitivity: `sensitivity.py`

`tornado(case, tech, uses, storage)` swings the 22 core parameters over their ranges from
`params.py` and the main site inputs by +/- 30 %, re-simulating chain and baseline each time.
The API returns it for the best chain.

## 6b. Heat waste cascade: `cascade.py`

The "Heat waste" tab optimizes for heat used and water saved, not money. A separate heat-use loop runs through
several users in series, hottest first: biogas digester (about 45 C supply), greenhouse (40 to 30 C), warm water
fish farm (33 to 29 C, makeup water and hall losses) and an ambient (5GDH) heat network (20 to 10 C) when a
community is within reach. Each user cools the loop to its own return temperature plus an approach. The return
water is reheated directly from the DC loops where they are hot enough, a booster heat pump does the rest, and
whatever heat is left goes to the baseline heat rejection, so less water evaporates and fans run less.
Every subset of users is simulated; the panel shows the top 2: "Most heat used" and "Most heat used that pays
off". Temperatures shown are those at the design hour (largest delivery).

Limits: greenhouse area is capped by flat land (site_gis.csv, low confidence) and `gh_max_ha`; fish farm size and
all host parameters are assumptions (`params.py`). CAPEX of the host businesses (greenhouse, fish farm halls) is
not counted, only heat exchangers, pipes, heat pump and network. Salmon farms are left out: cold water RAS needs
cooling, not heat. At large sites (300 to 800 MW) local demand limits use to about 1 to 3 % of the server heat;
small urban sites reach 20 to 60 %.

## 7. What the results say (US sites, offline weather 2024, 2026-11-26)

`heatbeat_engineering/results/us_sites.csv` has the best chain for all 40 US sites.

- The largest lever in the US is the **heat rejection choice**: 26 sites are best with adiabatic
  coolers, 9 with dry coolers, 5 keep towers. It depends on water + sewer tariff, water stress, wet
  bulb hours and coolant temperature, so the answer differs by site.
- The best heat use is mostly **digester heating** (small heat, high value: RNG with D3 RIN is worth
  about 110 USD/MWh). Since upgrading and new digester costs are counted (2026-11-26) its own NPV is
  positive at only 5 of 40 sites (Quincy, Memphis, Pryor, Hillsboro, Miami), strongly dependent on
  climate, feedstock distance and whether a digester already exists at the feedstock site.
- **District heating** does not pay at any US site with cheap gas (heat sells at about 40 to 55
  USD/MWh) and the community network charged to the project. It would with a utility owning the network
  (`capex_dist_network_usd_m` in the tornado) or in Europe.
- **ORC** and **feedwater preheat** lose money at 42 to 55 C. **Adsorption** is only feasible at
  Richland (55 C drive) and still loses money: the recooler must stay below 29 C, so it runs only in
  mild hours when the trim chiller is cheap anyway.

## Parameters and sources

All 99 parameters with value, range, unit, status and source are in `heatbeat_engineering/params.py`
(`params.table()`): 4 physics, 38 literature, 57 assumptions. Every CAPEX is screening level
(+/- 40 %) and most are UNVERIFIED team assumptions. Literature values are quoted from the named
handbooks and catalogues (ASHRAE Handbook HVAC Systems and Equipment, Danish Energy Agency technology
catalogues, Frederiksen and Werner 2013, Lund et al. 2014, Arpagaus et al. 2018, Fleuchaus et al. 2018,
Metcalf and Eddy, El-Dessouky and Ettouney 2002, Al-Karaghouli and Kazmerski 2013, Quoilin et al. 2013);
the edition was not re-checked in this session, so they are marked "check edition" where relevant.

## Known limits

- Data center loads, cooling profiles and coolant temperatures are mostly estimates (low confidence).
- Biogas: the feedstock quantity per site is not in the data. New plants are sized from an assumed anchor
  supply (300 t/day) plus regional collection (0.1 t/day per km2); with these defaults every new plant ends
  at 800 t/day, the largest size whose collection radius stays below 50 km. The size is set by feedstock,
  not by the data center: a 800 t/day digester needs only about 2 MW of heat at peak. Existing digesters
  are sized from EIA capacity and assumed to be heated by a biogas boiler today (if they use CHP waste
  heat, the DC heat is worth less). A site with an existing digester is not offered a second, new plant.
- Planned sites take prices, water, distances and storage geology from the nearest database site
  (distances plus the offset, an upper bound), flagged "estimate". Weather is fetched live for the
  point; without internet the nearest site's weather is used and flagged "synthetic".
- Hourly electricity prices are not used for the DC itself (retail flat rate), only the mean
  wholesale price for exported power.
- Ground temperature = annual mean air (clipped 5 to 20 C), seawater = air + 2 K.
- One heat rejection technology for all loops of a site; no hybrid towers.
