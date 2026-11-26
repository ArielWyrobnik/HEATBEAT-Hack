# Deploying the app

The whole app (React frontend, FastAPI backend, both models, all committed data) runs as **one
container** from the `Dockerfile`. FastAPI serves the built frontend from `frontend/dist` and the API
under `/api`, so there is one URL and no CORS setup.

## Render (free, permanent link)

`render.yaml` is a Render Blueprint for one free web service.

1. Click the **Deploy to Render** button in the README (or Render dashboard: New > Blueprint, pick this repo).
2. Sign in with GitHub, allow Render to read the repo.
3. Optional: fill `FEEDBACK_URL` (for example a Google Form link). It shows a "Give feedback" button in
   the header. Leave empty to hide it. It can be changed later under the service's Environment tab.
4. Click **Apply**. The first build takes about 5 minutes. The link is `https://heatbeat-XXXX.onrender.com`.

Every merge into `main` redeploys automatically (`autoDeploy: true`).

Free plan limits (from Render documentation, not re-verified for this PR, may change):

- The service sleeps after 15 minutes without visitors. The next visit wakes it in about a minute.
- 512 MB RAM. Measured locally: about 270 MB after running both models for all 57 sites with stored weather.
- Shared CPU, so a ranking takes a few seconds instead of under one second on a laptop.
- No persistent disk: live fetched weather (2 Israel sites, planned points) is fetched again after each restart.

## Data at runtime

The container only reads files committed to the repo: `data/parquet/*.parquet` (sites, grid regions,
hourly prices, hourly weather for 57 of 59 sites) and `data_pipeline/*.csv` (heat profiles, water,
Aqueduct, GIS, industry, ecology, market prices). The SQLite database is built from the Parquet files
during the image build. The pipeline only inputs (`agstar.xlsx`, EIA generator dump, Ember CSV) are not
needed by the app.

The only outgoing calls are Open-Meteo (fallback NASA POWER) for weather of sites without stored
weather and of planned sites. Neither needs an API key. Set `HEATBEAT_LIVE=0` to switch them off.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | 8000 | Port uvicorn listens on (Render sets it). |
| `HEATBEAT_LIVE` | 1 | 0 = never fetch weather from the internet. |
| `HEATBEAT_SITES` | verified | `all` = list every site on the map, not only those with documented cooling. |
| `FEEDBACK_URL` | empty | Link behind the "Give feedback" button. Empty hides the button. |
| `HEATBEAT_STATIC` | `frontend/dist` | Folder with the built frontend. |

## Local check of the production build

```
docker build -t heatbeat . && docker run -p 8000:8000 heatbeat
```

Then open http://localhost:8000. Without Docker: `cd frontend && npm run build`, then
`uvicorn heatbeat_api.app:app --port 8000` from the repo folder.

## Quick share from a laptop (temporary)

While `./scripts/dev.sh` runs, `cloudflared tunnel --url http://localhost:5173` gives a temporary public
`trycloudflare.com` link without an account. It stops when the terminal closes.
