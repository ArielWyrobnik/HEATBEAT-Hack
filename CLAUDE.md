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

PRs #1 and #3 to #10 are merged into `main` (#7: US retail prices from EIA 2024 instead of 2020, shorter Open-Meteo timeout; #8: free cooling capped by site supply temperature; #10: demo works without stored weather). What is on `main`:

| Part | Where | Docs | Status |
|---|---|---|---|
| Location database: 59 sites, electricity prices, carbon intensity, `heatbeat_data` access module, GitHub Actions build. Weather is fetched live on first use (Open-Meteo, fallback NASA POWER) and cached. | `data_pipeline/`, `heatbeat_data/` | `docs/DATA.md` | Merged. `data/parquet/` (hourly prices, carbon) is not committed yet; the `Build location database` workflow on `main` commits it when it finishes. Until then the 4 data tests in `tests/test_database.py` fail with FileNotFoundError. |
| Heat source per site: IT load, cooling type, chip generation, coolant temperatures, `hd.site_heat_profiles()` | `data_pipeline/cooling_profiles.csv`, `site_profiles.csv`, `heat_sources.csv`, `heatbeat_data/heat_profiles.py` | `docs/HEAT_PROFILES.md` | Merged. Most site MW and chip values are team estimates (low confidence). |
| Solution catalogue: 21 solutions with ideal parameters, schema validation, `screen()` first pass ranking | `heatbeat_solutions/` | `docs/SOLUTIONS.md` | Merged. Market prices not included yet. |
| Demo: Streamlit input overview with live API calls and pipeline checks, every input labelled real / estimated / synthetic | `demo/` (`streamlit run demo/app.py`) | `demo/README.md` | Merged. The `Demo pipeline check` workflow runs the live calls in CI. |
| Frontend: landing page, "How it works" section, world map (React, TypeScript, Vite, Leaflet) | `frontend/` | | Merged. Map pins load from `frontend/public/datacenters.json`. |
| Ranking engine: port of the team Excel "Hack data.xlsx" (13 options, KO gates, score 0 to 5, eco grade A to F), modes `excel` (tested against the Excel) and `corrected`. Data threads hand missing site inputs over as `data_pipeline/site_ranking_inputs_<topic>.csv`. | `heatbeat_ranking/` | `docs/RANKING.md`, `heatbeat_ranking/AUDIT.md` | Branch `claude/project-thread-v4cogf`, PR open. |

Next steps:

- Shortlist solutions and collect economic and regional market data per solution (plan in the Claude Doc "Lösungs-Ranking: Datenschema und Aufgabenverteilung"). Regional values go into a planned `data_pipeline/market_prices.csv` keyed by `country_iso2` + `region` like `sites.csv`.
- Water prices for US regions (separate thread).
- Connect map, database and ranking engine (`heatbeat_ranking.rank_site`).

Known gaps: PJM prices need a `PJM_API_KEY` secret, non-US retail prices and the Israel tariff mapping are unverified placeholders, no water (WUE, water price) or heat demand data yet.

## Working rules

- English for code, docs and technical terms.
- Cite a source for every real number. Flag unverified or synthetic numbers clearly.
- Ask before building larger pieces.
- Never use em-dashes in text.
