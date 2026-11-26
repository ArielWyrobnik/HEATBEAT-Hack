# HEATBEAT demo: input overview and pipeline check

Pick a data center (or any point on earth) and see every input the model would be fed,
each value labelled by status (real, derived, estimated, synthetic, user input) and by where it came
from (LIVE API call, stored DB, curated CSV, computed here). A second view runs checks on the data
pipeline.

## Run

From the repository root:

```bash
pip install -r requirements.txt -r demo/requirements.txt
streamlit run demo/app.py          # opens http://localhost:8501
```

Without a stored database (`data/parquet/*.parquet`) the app still runs: live weather calls and the
curated data center CSVs work, prices and carbon intensity are then missing. The real database is
committed to the branch by the GitHub Actions workflow `Build location database`; `git pull` to get it.
To test the app code with placeholders only: `python -m data_pipeline.build_db --offline`.

## What happens when you pick a site

| Input | Origin in the app | Live call (no API key) |
|---|---|---|
| Hourly weather 2024 (dry bulb, RH, dew point, wind, solar) | LIVE if the call works, else DB or local cache (the database build no longer stores weather) | Open-Meteo archive API (ERA5), same request as the pipeline |
| Elevation | LIVE | Open-Meteo elevation API |
| Weather cross-check | LIVE, optional | NASA POWER hourly API |
| Hourly electricity price | DB | optional one-week spot check via gridstatus (CAISO, MISO, NYISO, ISO-NE, SPP) |
| Retail price, carbon intensity | DB | none (EIA, eGRID, Ember are downloaded files, see docs/DATA.md) |
| IT load, chip, cooling, coolant temperatures | CSV (`data_pipeline/site_profiles.csv`, `cooling_profiles.csv`) | none, curated by the team |
| Waste heat MW and MWh/yr, emissions | computed | none |

Live results are cached for one hour per location ("Clear live cache and refetch" in the sidebar).

## Tabs

- **Model inputs**: one table with every input, value, unit, status badge, origin and source. Downloadable as CSV.
- **Weather**: annual profile (daily min, mean, max), wet bulb, typical day per month heatmap, monthly table.
  If both live and stored data exist, both are drawn.
- **Electricity price**: annual profile, month by hour heatmap, weekday and weekend daily profile.
- **Heat source**: IT load, facility power, heat in liquid and in air, coolant temperatures.
- **Pipeline check**: hours present (8784), gaps, plausible ranges, wet bulb below dry bulb, synthetic share,
  live versus stored weather (same API, must match within 0.2 C, else FAIL), NASA versus Open-Meteo (independent reanalyses, a gap above 2 C is a warning, not a failure),
  live versus stored prices, heat profile consistency.
- **API calls**: every request with full URL (clickable), HTTP status, duration, size and rows.

## Command line and CI

```bash
python -m demo.pipeline_check                          # Haifa, Santa Clara, Frankfurt
python -m demo.pipeline_check --site il-haifa --nasa   # one site plus NASA cross-check
python -m demo.pipeline_check --lat 31.25 --lon 34.79  # any point, weather only
```

The workflow `Demo pipeline check` runs this with `--nasa --price` on GitHub runners (manual or on
changes to `demo/`) and fails if a check fails.
