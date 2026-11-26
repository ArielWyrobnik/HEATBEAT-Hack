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
