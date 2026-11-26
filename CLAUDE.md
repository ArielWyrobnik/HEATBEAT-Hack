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

PRs #1, #3, #4, #5, #6 and #7 are merged into `main` (#7: US retail prices from EIA 2024 instead of 2020, shorter Open-Meteo timeout). What is on `main`:

| Part | Where | Docs | Status |
|---|---|---|---|
| Location database: 59 sites, electricity prices, carbon intensity, `heatbeat_data` access module, GitHub Actions build. Weather is fetched live on first use (Open-Meteo, fallback NASA POWER) and cached. | `data_pipeline/`, `heatbeat_data/` | `docs/DATA.md` | Merged. The hourly price data is not committed yet: the build workflow run on the old PR #1 branch was still running at merge time, so its data commit lands on that branch and needs a follow-up PR (or a new workflow run on `main`). Until then the 4 data tests in `tests/test_database.py` fail with FileNotFoundError. |
| Heat source per site: IT load, cooling type, chip generation, coolant temperatures, `hd.site_heat_profiles()` | `data_pipeline/cooling_profiles.csv`, `site_profiles.csv`, `heat_sources.csv`, `heatbeat_data/heat_profiles.py` | `docs/HEAT_PROFILES.md` | Merged. Most site MW and chip values are team estimates (low confidence). |
| Solution catalogue: 21 solutions with ideal parameters, schema validation, `screen()` first pass ranking | `heatbeat_solutions/` | `docs/SOLUTIONS.md` | Merged. Market prices not included yet. |
| Demo: Streamlit input overview with live API calls and pipeline checks | `demo/` | `demo/README.md` | Merged. |
| Frontend: landing page, "How it works" section, world map (React, TypeScript, Vite, Leaflet) | `frontend/` | | Merged. Map pins load from `frontend/public/datacenters.json`. |

Next steps:

- Shortlist solutions and collect economic and regional market data per solution (plan in the Claude Doc "Lösungs-Ranking: Datenschema und Aufgabenverteilung"). Regional values go into a planned `data_pipeline/market_prices.csv` keyed by `country_iso2` + `region` like `sites.csv`.
- Water prices for US regions (separate thread).
- Ranking logic and the connection between map, database and models.

Known gaps: PJM prices need a `PJM_API_KEY` secret, non-US retail prices and the Israel tariff mapping are unverified placeholders.

## Working rules

- English for code, docs and technical terms.
- Cite a source for every real number. Flag unverified or synthetic numbers clearly.
- Ask before building larger pieces.
- Never use em-dashes in text.
