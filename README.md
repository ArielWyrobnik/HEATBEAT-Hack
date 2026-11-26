# HEATBEAT

NVIDIA hackathon project on data center waste streams (waste heat, stranded power, water, unused compute).

Planned pieces:

1. **Location database** (done first): 59 data center sites (mostly US, plus Europe, Asia, and
   Israel) with a full year of hourly weather, hourly electricity prices, retail prices and grid
   carbon intensity. See [docs/DATA.md](docs/DATA.md).
2. **Solution models** (teammates): each model takes one site's data and computes feasibility of a
   solution such as heat reuse, free cooling or load shifting (MWh, tCO2, m3, money, payback).
3. **Map frontend**: shows all sites; clicking one runs the models and ranks the solutions.

## Try it online

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ArielWyrobnik/HEATBEAT-Hack)

One free web service runs the whole app (map, API, models). Setup and limits: [docs/DEPLOY.md](docs/DEPLOY.md).

## Use the data

```python
import heatbeat_data as hd

hd.list_sites()                       # all sites with lat/lon for the map
site = hd.get_site("il-tel-aviv")
site.hourly()                         # 8784 hourly rows: weather + price
site.summary()                        # annual indicators
```

Requirements: `pip install -r requirements.txt`.
