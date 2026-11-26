# Heat Beat – Frontend

Landing page + world map of data centers (React, TypeScript, Vite, Leaflet).

```bash
cd frontend
npm install
npm run dev
```

## Adding the data center pins

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
