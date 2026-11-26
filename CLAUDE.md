# HEATBEAT

Team project for the NVIDIA hackathon (November 2026). Challenge: data center waste streams, meaning waste heat, stranded power, water and unused compute.

## Purpose

We build a tool that answers one question for a given data center: which waste stream solution is the most feasible at this location?

Product flow:

1. A map frontend shows data centers (mainly US, some in Israel).
2. Clicking a data center pulls its location data from the main database: hourly weather, electricity prices and grid carbon intensity.
3. The site data is fed into the team's solution models.
4. The models are compared and ranked by feasibility.

Every solution model is a quantitative, parametric model (Python notebook or script). Each one needs:

- A baseline and a counterfactual (what happens without vs. with the solution).
- An energy balance.
- A sensitivity analysis (tornado chart).
- Data center metrics: PUE, WUE, ERE.
- Outputs in MWh, tCO2, m3 of water, money and payback time.

Synthetic data is allowed where real data is missing, but it must be flagged.

Ariel's part ("Problem One"): the energy big picture that feeds the baseline. Data center electricity use and trends, share of energy that becomes heat, locations, energy mix and projections.

Local context: Israel has low heating demand, high cooling demand, water scarcity and coastal desalination. Solutions should be judged against that context, not only against US or European conditions.

## Current state (2026-11-26)

Focus: US sites first. Israel is set aside for now (Ariel, 2026-11-26).

PRs #1 and #3 to #37 are merged into `main` (#7: US retail prices from EIA 2024 instead of 2020; #8: free cooling capped by site supply temperature; #10: demo works without stored weather; #13: DAC credit split from avoided emission carbon value). What is on `main`:

| Part | Where | Docs | Status |
|---|---|---|---|
| Location database: 59 sites, electricity prices, carbon intensity, `heatbeat_data` access module, GitHub Actions build. Weather is fetched live on first use (Open-Meteo, fallback NASA POWER) and cached. | `data_pipeline/`, `heatbeat_data/` | `docs/DATA.md` | Merged, data in `data/parquet/` (#25). Real hourly day-ahead prices for ERCOT, MISO, NYISO, ISO-NE; CAISO, SPP, PJM and non-market regions are synthetic shapes (`is_synthetic = 1`). Weather stored for 57 of 59 sites (restored and protected from empty rebuilds in #29), the other 2 are fetched live. |
| Heat source per site: IT load, cooling type, chip generation, coolant temperatures, `hd.site_heat_profiles()` | `data_pipeline/cooling_profiles.csv`, `site_profiles.csv`, `heat_sources.csv`, `heatbeat_data/heat_profiles.py` | `docs/HEAT_PROFILES.md` | Merged. Most site MW and chip values are team estimates (low confidence). |
| Solution catalogue: 21 solutions with ideal parameters, schema validation, `screen()` first pass ranking | `heatbeat_solutions/` | `docs/SOLUTIONS.md` | Merged. |
| US market prices per state: gas, propane, heating oil, carbon markets, 45Q, RINs, LCFS, fish, tomatoes, pellets; `hd.excel_inputs(site_id)` | `data_pipeline/market_prices.csv`, `heatbeat_data/market.py` | `docs/MARKET.md` | Merged (#12, #13). Transcribed from published tables, synthetic rows flagged. |
| US water: tariffs and sewer per site, baseline WUE model, WRI Aqueduct lookup | `data_pipeline/site_water.csv`, `wue_profiles.csv`, `heatbeat_data/water.py`, `fetch_aqueduct.py` | `docs/WATER.md` | Merged (#15, #27). `wsi_index` filled from WRI Aqueduct 4.0 (baseline plus 2030 and 2050 BAU) in `data_pipeline/aqueduct_sites.csv`. |
| Demo: Streamlit input overview with live API calls and pipeline checks, every input labelled real / estimated / synthetic | `demo/` (`streamlit run demo/app.py`) | `demo/README.md` | Merged. The `Demo pipeline check` workflow runs the live calls in CI. |
| Frontend: landing page, "How it works" section, world map (React, TypeScript, Vite, Leaflet) | `frontend/` | | Merged. Map pins load from `frontend/public/datacenters.json`. |
| Site GIS inputs for the Excel model: d_coast_m, d_water_m, dz_m, slope_deg, flat and agri land, campus area, DH distance and heat density, industrial zoning; `hd.gis_inputs(site_id)` | `data_pipeline/site_gis.csv`, `fetch_gis.py`, `heatbeat_data/site_gis.py` | `docs/GIS.md` | Merged (#20). `campus_area_m2` synthetic, `ind_zoning` is an OSM proxy, most land figures low confidence. |
| Ecology and geology scores: eco_sens_index, geo_storage_score, mit_tier; `hd.excel_ecology_inputs(site_id)` | `data_pipeline/site_ecology.csv`, `data_pipeline/ecology/` | `docs/ECOLOGY.md` | Merged (#17). Thresholds are team choices. |
| Neighbouring industry per US site: d_pp_m, q_fw_mw, d_co2_m, d_bio_m, d_market_m; `hd.excel_industry_inputs(site_id)` (named so it does not shadow the market `hd.excel_inputs`) | `data_pipeline/site_industry.csv`, `fetch_industry.py`, `heatbeat_data/site_industry.py` | `docs/INDUSTRY.md` | Merged (#23, #35). `q_fw_mw` is an engineering estimate; `d_market_m` from Overture Maps places (business listings, hint only); `ind_zoning` comes from `site_gis.csv`. |
| Ranking engine: port of the team Excel "Hack data.xlsx" (13 options, KO gates, score 0 to 5, eco grade A to F), modes `excel` (tested against the Excel) and `corrected`. Data threads hand missing site inputs over as `data_pipeline/site_ranking_inputs_<topic>.csv`. | `heatbeat_ranking/` | `docs/RANKING.md`, `heatbeat_ranking/AUDIT.md` | Merged (#14). CAPEX per option is a placeholder, heat sink not sized yet (upper bounds). |
| API between models and frontend: FastAPI with `/api/sites`, `/api/sites/{id}/inputs`, `/api/sites/{id}/ranking`, `POST /api/evaluate`, `POST /api/plan` (future data center: any map point + MW/GW + cooling); model interface `SiteModel` (auto loads `heatbeat_engineering.api_model.MODEL`); map pins from the API, side panel with baseline, ranking, KPIs, tornado and flagged inputs. Start both with `./scripts/dev.sh`. | `heatbeat_api/`, `frontend/src/components/SitePanel.tsx`, `scripts/dev.sh` | `docs/API.md` | Merged (#30, #33, #37). #37 adds a data center picker, a full screen site panel and a "Show calculation" popup per option (`heatbeat_engineering/calc_trace.py`). Default model is the engineering heat chain; the Excel ranking answers with `?model=excel_ranking`. |
| Engineering heat chain model: hourly component physics (dry / adiabatic / tower with trim chiller, heat pump, district heating pipes, tank/ATES/BTES, digester heating, feedwater, MED/MD, ORC, adsorption), closed energy balance, baseline counterfactual, PUE/WUE/ERE, NPV, tornado; database sites and planned sites (`evaluate(lat, lon, it_mw, cooling)`); API adapter `api_model.MODEL` | `heatbeat_engineering/` | `docs/ENGINEERING.md` | Merged (#32, review fixes for ORC and feedwater accounting and planned site templates), default model of the API. Replaces fish farm, greenhouse, drying, snow melt (mentor feedback). CAPEX mostly unverified assumptions. |
| Current setup per site (what sites already do): heat rejection, cooling, water source and volume, PUE/WUE, on-site power, heat reuse, "already implemented", field-level sources; engineering baseline uses it, panel shows it with overrides; model checked against reported WUE/PUE/water | `data_pipeline/site_current_setup*.csv`, `heatbeat_data/current_setup.py`, `heatbeat_engineering/validate_setup.py` | `docs/CURRENT_SETUP.md` | 28 of 40 US sites with sourced facts, 15 with documented heat rejection (2026-11-26). Inferred values flagged `evidence = inferred`. |
| Validation against 13 real reference projects (Nebius Mantsala, Green Mountain Rjukan, EcoDataCenter Falun, NorthC Eindhoven, Equinix AM3 and PA10, Echelon Arklow, Crusoe, Syracuse, Vertiv ORC, Orbital DAC, Trevi, Westin Seattle): 9 new sites with sources, implemented facts in `site_current_setup_refs.csv`, runner `python -m heatbeat_validation` | `data_pipeline/reference_sites.py`, `heatbeat_validation/` | `docs/VALIDATION.md`, `docs/VALIDATION_RESULTS.md` | Open PR. GIS, ecology, water, industry of the new sites are hand estimates (low). |

Next steps:

- Shortlist solutions and fill the per solution economics (plan in the Claude Doc "Lösungs-Ranking: Datenschema und Aufgabenverteilung").

Known gaps: PJM prices need a `PJM_API_KEY` secret, non-US retail prices and the Israel tariff mapping are unverified placeholders, no heat demand data yet.

## Working rules

- English for code, docs and technical terms.
- Cite a source for every real number. Flag unverified or synthetic numbers clearly.
- Ask before building larger pieces.
- Never use em-dashes in text.
