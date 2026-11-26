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

Early stage. `main` holds this file, a short README and the frontend in `frontend/`. `main` is the default branch.

| Work | Branch | Status |
|---|---|---|
| Data center location database: 59 sites, hourly 2024 weather, electricity prices, carbon intensity, `heatbeat_data` Python access module, GitHub Actions build. Docs in `docs/DATA.md`. | `claude/project-thread-n1j7gu` | In progress, open as PR #1 |
| Frontend: landing page and world map with search (React, TypeScript, Vite, Leaflet) in `frontend/`. Pins load from `frontend/public/datacenters.json`, still empty. | `main` (merged from `claude/funny-hopper-859d23`) | On main, in progress |

Not started yet: the solution models, the ranking logic, and the connection between map, database and models.

Known gaps in the database (see PR #1): PJM prices need a `PJM_API_KEY` secret, non-US retail prices and the Israel tariff mapping are unverified placeholders.

## Working rules

- English for code, docs and technical terms.
- Cite a source for every real number. Flag unverified or synthetic numbers clearly.
- Ask before building larger pieces.
- Never use em-dashes in text.
