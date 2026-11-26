# Validation against real heat reuse projects

Question: if we feed the site of a real project into our models, (a) do the models find the solution that
was actually built feasible, ideally near the top, and (b) do the model numbers match what the operator
or the press reports?

Run: `python -m heatbeat_validation` (needs the stored weather of the sites, see `docs/DATA.md`).
Output: `heatbeat_validation/results/validation_table.csv` (feasibility per model),
`heatbeat_validation/results/validation_metrics.csv` (number checks) and the generated tables in
[VALIDATION_RESULTS.md](VALIDATION_RESULTS.md).

## Reference projects and sites

13 projects, one per solution type of the team list. 9 sites were new and are added to the site list
(`data_pipeline/reference_sites.py` writes them into every per site table); 5 cases reuse a site that
already existed. Where a project is not one fixed site, a representative location was picked and is
named as such.

| # | Solution | Project | Site id | Site |
|---|---|---|---|---|
| 1 | Fish farm | Hima Seafood + Green Mountain DC2-Telemark | `no-rjukan-greenmountain` | new |
| 2 | District heating | Nebius Mantsala + Nivos | `fi-mantsala-nebius` | new |
| 3a | Biogas | Echelon DUB20 + Biocore digester (planned) | `ie-arklow-echelon` | new |
| 3b | Biogas / stranded gas | Crusoe Digital Flare Mitigation | `us-nd-williston-crusoe` | new, representative (Crusoe runs mobile modules at many well pads) |
| 4 | Absorption cooling | Syracuse University Green Data Center | `us-ny-syracuse-university` | new |
| 5 | ORC | Vertiv ORC testbed (design climate Ashburn) | `us-va-ashburn-equinix` | existing, climate only (the testbed is not at Equinix) |
| 6 | DAC | Orbital Materials + Civo pilot | `gb-slough` | existing, representative (pilot site undisclosed) |
| 7a | ATES | Equinix AM3/AM4 Science Park | `nl-amsterdam` | existing (the cluster is the Science Park) |
| 7b | ATES | NorthC Eindhoven 1, High Tech Campus | `nl-eindhoven-northc` | new |
| 8 | Feedwater | EcoDataCenter 1 + Falu Energi & Vatten CHP | `se-falun-ecodatacenter` | new |
| 9 | Desalination | Endeavour + Trevi forward osmosis | `us-hi-kona-nelha` | new, representative (Trevi seawater test at NELHA; not a data center) |
| 10 | Biomass (pellets) | EcoDataCenter 1 + pellet plant | `se-falun-ecodatacenter` | new |
| 11a | Drying | Falun sawdust drying | `se-falun-ecodatacenter` | new |
| 11b | Drying | Midwest grain bins (concept, no project found) | `us-ia-council-bluffs-google` | existing, representative |
| 12 | Radiant / snow melt | Westin Building Exchange to Amazon Doppler | `us-wa-seattle-westin` | new |
| 13 | Greenhouse | Equinix PA10 rooftop farm + heat to Olympic Aquatics Centre | `fr-paris` | existing (the cluster is Saint-Denis) |

Not found in any source: the earlier lobster pilot at Green Mountain DC1-Stavanger (not added),
the IT load of most of these sites (assumed and flagged in `site_profiles.csv`).

What each project actually runs is in `data_pipeline/site_current_setup_refs.csv` (same long format and
loader as the current setup thread, `heatbeat_data.current_setup`), sources in
`data_pipeline/site_current_setup_refs_sources.csv`.

## Data quality of the new sites

| Data | Status |
|---|---|
| Coordinates, operator, capacity, what is implemented | cited press and operator pages (32 sources) |
| Hourly weather 2024 | Open-Meteo ERA5 via the normal pipeline (build workflow) |
| Hourly prices | NYISO Zone C real day-ahead; SPP North, Hawaii and all non-US: synthetic shape (flagged) |
| Retail electricity price | ND and HI from EIA Table 2.10 (2024); NO and other non-US: rough fallback (flagged) |
| Grid CO2 | eGRID 2023 (US), Ember (non-US) |
| GIS, ecology, water, industry | HAND ESTIMATES (confidence low): the cloud container could not reach the GIS APIs. Rerun `fetch_gis.py`, `ecology/fetch_features.py`, `fetch_aqueduct.py`, `fetch_industry.py` with internet to replace them |
| Heat price outside the US | Eurostat non-household gas price per country / boiler efficiency 0.85, same definition as the US value (`data_pipeline/heat_prices_intl.csv`): FI, SE, DE, NL own value, other European countries the EU average (flagged estimate), EUR to USD 1.10 is a team estimate. Outside Europe still the 50 USD/MWh default. |

Project specific inputs that are known from the project itself are set per case in
`heatbeat_validation/cases.py` (for example the digester is co-located at Arklow, the CHP plant is next
door in Falun, the Vertiv loop runs at 58 C), each with its source or marked as an assumption.

## Method

- Engineering model (`heatbeat_engineering`): all chains of the site, best chain per heat use family
  ranked by NPV, heat rejection alone counts as one family. ATES counts as its own family (district
  heating chain with ATES storage). "Feasible" = at least one chain of that family survives the knock
  out rules.
- Excel ranking port (`heatbeat_ranking`, mode `excel`): used for the options the engineering model
  dropped after mentor feedback (fish farm, DAC, biomass, drying, snow melt, greenhouse) and as a second
  opinion for the others. Run twice: as operating site (`is_greenfield = 0`) and as new build
  (`is_greenfield = 1`), because 7 of the 13 Excel options are greenfield only.
- Number check: model / reported within 0.77 to 1.3 = "match", within 1/3 to 3 = "same order",
  otherwise "miss". Most reported figures are capacities or rounded press numbers, so "same order" is
  the realistic bar.

## Results (run 2026-11-26, 2024 weather)

Full tables: [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md). Two cases cannot be checked: 3b (Crusoe
burns flare gas to power the compute, no model has gas to power) and 11b (no real grain drying project
found). Case 4 is a "correct no": Syracuse drives its absorption chillers with gas microturbine exhaust,
not with data center heat, and both models reject absorption on data center heat at 13 C.

### (a) Feasibility: 11 of 13 built solutions pass the knock out rules (the ORC KO matches the measured net loss), 3 come out on top

| Ref | Built | Model verdict | Assessment |
|---|---|---|---|
| 1 | Fish farm, Rjukan | Excel: feasible, rank 1 of 13 | hit |
| 2 | District heating, Mantsala | Engineering: feasible, but reuse NPV -6.9 MUSD at the default heat price 50 USD/MWh; break-even 141 USD/MWh. Excel: KO as operating site (heat density 1.5 < 2.5) | partial: physics yes, economics no |
| 3a | Biogas digester, Arklow | Engineering: rank 1, reuse NPV +2.1 MUSD. Excel: rank 2 | hit |
| 4 | Absorption on gas CHP, Syracuse | KO in both (no hot enough data center heat) | correct no |
| 5 | ORC testbed, 58 C | Engineering: KO since `orc_min_source_c` = 80 C (before: feasible, about 0 NPV, 4% mean efficiency). Vertiv measured net NEGATIVE power at 58 to 63 C once fans count. Excel: KO (needs 80 C) | correct no after the fix (was a miss at 45 C) |
| 6 | DAC pilot, UK | Excel: KO, no CO2 storage distance for UK sites (default 100 km) | miss (data gap) |
| 7a, 7b | ATES, Amsterdam and Eindhoven | Engineering: ATES chain feasible but last (only modelled as seasonal storage for a district heating network, NPV -32 to -143 MUSD). Excel: KO (needs >= 1000 h above 20 C) | miss (model scope): ATES for cooling is not in either model |
| 8 | Hot water to the Falun CHP | Engineering feedwater: feasible, rank 2 of 4, NPV negative. Excel: rank 6 (greenfield) | partial |
| 9 | Desalination, Kona | Engineering: MED rank 1, NPV +1.2 MUSD per MW. Excel: KO by the hand estimated water stress 1.5 | hit (engineering) |
| 10, 11a | Pellet and sawdust drying, Falun | Excel greenfield: rank 4 of 13; operating site: KO (greenfield only option) | hit as new build |
| 12 | Westin to Amazon radiant floors | Engineering DH: feasible, last of 3, break-even 81 USD/MWh. Excel snow melt: KO (too few frost hours, and no snow melt was built) | partial |
| 13 | PA10 heat network + rooftop greenhouse | Engineering DH: feasible, rank 2, break-even 122 USD/MWh. Excel greenhouse: KO (needs 20,000 m2 farmland, PA10 has 430 m2 on the roof) | partial |

### (b) Numbers: 9 match, 7 same order, 5 miss (21 comparable figures)

- Temperatures and PUE match well: source 26 vs 28 C (PA10), 32 vs 35 to 40 C (Mantsala), supply 70 vs
  65 C; PUE within 7% at Mantsala and Amsterdam.
- District heating volume is driven by the model's generic community (5, 20, 60 km networks), not by
  the real town: 7,500 vs 20,000 MWh/yr at Mantsala, 16,700 vs 10,000 MWh/yr at PA10 (same order).
- ORC: the model's efficiency (5.5% at 58 C) is close to the measured 3 to 3.3%, but the model says the
  ORC makes net power while the Vertiv testbed made net losses in every test (condenser fan and pump).
- Desalination: the model makes about 20,700 m3 per MW and year (MED, GOR 1.7); Endeavour claims about
  276,000 m3 per MW and year for forward osmosis on brackish water, 13 times more. That claim implies
  about 32 kWh of heat per m3, far below thermal desalination of seawater; treat it as a company claim.
- Falun: the model's feedwater sink takes 3.3 MW, the project sends up to 10 MW (to pellet drying and
  district heating, not to feedwater). Fish farm: the Excel recovers 7.7 MW, matching the 8 MW phase 2
  target but not the 1.75 MW phase 1.

### What this says about the model

1. Physics and temperatures are right; the knock out rules accept almost every solution that was built.
2. Economics are the weak spot: every district heating type project that exists (Mantsala, Westin,
   PA10, NorthC, Amsterdam) is unprofitable in the model at the default 50 USD/MWh heat price. They
   become profitable at 80 to 230 USD/MWh. Real European projects are often driven by regulation (for example
   the German Energy Efficiency Act, EnEfG, not cited here), free heat deals (PA10 gives the heat away for 15 years)
   or municipal utilities, which the NPV does not capture. Per country heat prices from Eurostat are in since 2026-11-26 (see table above).
3. Missing options: ATES for cooling (not only seasonal heat storage), gas to power / stranded energy
   (Crusoe), CHP trigeneration (Syracuse).
4. ORC rule was too lax: the engineering model offered an ORC from 45 C. Vertiv found net losses even at
   58 to 63 C and states the ORC cannot work below ambient max + 40 K (about 84 C in Ashburn). Fixed in a
   follow-up PR: `orc_min_source_c` is now 80 C, so case 5 is a KO in both models (matching Vertiv). The
   model's ORC efficiency itself (5.5% at 58 C vs 3 to 3.3% measured) stays as it is.
5. Data gaps outside the US: UK CO2 storage distance, European heat prices, water stress for the new
   sites (hand estimates).
