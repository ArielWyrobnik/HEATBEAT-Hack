# Heat Beat – Frontend

Landing page + world map of data centers (React, TypeScript, Vite, Leaflet).

```bash
cd frontend
npm install
npm run dev
```

## Backend (pins, rankings)

With the backend running, the map loads its pins from `GET /api/sites` and a click on a pin opens a
side panel (`src/components/SitePanel.tsx`) with baseline, ranked options, KPIs, tornado chart and
every input with its real / estimated / synthetic flag. Start both from the repo root:

```bash
./scripts/dev.sh
```

Vite proxies `/api` to `http://127.0.0.1:8000` (override with `HEATBEAT_API=...`, or set
`VITE_API_URL` for a deployed backend). API contract: `src/types/api.ts`, mirror of
`heatbeat_api/schemas.py`, see `docs/API.md`. Without a backend the map falls back to the static file below.

## Static pins (fallback without backend)

The map loads `public/datacenters.json` at runtime (currently `[]`).
Replace it with an array of objects – see `src/types/datacenter.ts`:

```json
[{ "id": "fra-1", "name": "DC Frankfurt", "lat": 50.11, "lng": 8.68,
   "operator": "…", "city": "Frankfurt", "country": "Germany", "capacityMW": 60, "pue": 1.35 }]
```

Only `name`, `lat`, `lng` are required. `{ "datacenters": [...] }` also works.
To try it out: `cp public/datacenters.sample.json public/datacenters.json`.

The search bar matches data centers by name / operator / city / country and
falls back to place search (OpenStreetMap Nominatim) to fly to any location.

## DSX evaluator model (`src/dsx/`)

A third model, **DSX evaluator v3.1 (in browser)**, sits next to "Engineering heat chain" and "Team Excel
ranking" in the Model menu of the site and plan panels. It runs entirely in the browser:

- `src/dsx/engine.ts` – the DSX Waste-Heat Recovery Evaluator v3.1.1 (same numbers as `evaluator.py`):
  8,760-h diurnal climate, 13 knock-out gates, viability 0 to 5 and a standalone eco grade A to F.
- `src/dsx/climate.ts` – 365 daily min / max temperatures from the Open-Meteo archive (2024, ERA5, no key);
  falls back to a synthetic year built from the backend's weather summary.
- `src/dsx/adapter.ts` – maps the backend's 31 inputs (`excel_ranking` inputs, same keys) to the evaluator,
  and its result to `ModelResult`: ranking, KPIs, CAPEX split, energy flows, an 8-step calculation trace
  for the "Show calculation" popup, and a tornado chart of net value.
- `src/api.ts` – `models()` adds the DSX model; `ranking()`, `inputs()` and `plan()` route it to the adapter.

Mode: `as_built` only (the site's own cooling). The 70 C upgrade scenario was removed. Reference-site prices, grid carbon, carbon price and water stress are sourced per country or state in `src/dsx/referenceSites.ts` (each value shows its source in the app).
No backend change is needed.
