# HEATBEAT API (`heatbeat_api`)

Small FastAPI backend between the models and the map frontend. The frontend only talks to this API,
and the API only talks to a model through a three method interface, so a new model (the engineering
heat chain model) plugs in without frontend changes.

```
frontend (Vite, :5173)  --/api-->  heatbeat_api (FastAPI, :8000)  -->  model (SiteModel)  -->  heatbeat_data
```

## Run

```bash
./scripts/dev.sh          # API and frontend together, opens the browser. Ctrl+C stops both.
make api                  # API only; interactive docs at http://127.0.0.1:8000/docs
python -m pytest -q tests/test_api.py
```

`scripts/dev.sh` creates `.venv` and installs `requirements.txt` + `requirements-api.txt` and the npm
packages on first run. `HEATBEAT_LIVE=0` stops all live weather fetches (CI, offline demos). The
Streamlit demo (`streamlit run demo/app.py`) is independent and still works.

## Endpoints

All routes are under `/api`; Vite proxies `/api` to the backend (`frontend/vite.config.ts`).

| Method and path | Returns | Notes |
|---|---|---|
| `GET /api/health` | status, models, default model | |
| `GET /api/models` | `ModelInfo[]` | name, label, modes, default mode |
| `GET /api/sites?country=US&scope=` | `SiteSummary[]` | map pins: coordinates, IT load, cooling, PUE, grid region. `scope=verified` (default, from `HEATBEAT_SITES`) lists only sites whose heat rejection is documented by a source (`setup_status = verified`, see `docs/CURRENT_SETUP.md`); `scope=all` lists every site. Hidden sites stay in the database and answer by id. |
| `GET /api/sites/{id}` | `SiteSummary` | |
| `GET /api/sites/{id}/inputs?model=&is_greenfield=` | `SiteInputs` | every model input with unit, flag, source, sensitivity range, plus annual weather and price indicators |
| `GET /api/sites/{id}/ranking?model=&mode=&is_greenfield=` | `ModelResult` | baseline, options best first with KPIs and energy balance, tornado of the best option, warnings. Cached per process. |
| `POST /api/evaluate` | `ModelResult` | what-if for a database site: `{"site_id", "overrides": {"d_bio_m": 2000}}` |
| `GET /api/cooling-profiles` | `CoolingProfile[]` | cooling choices for a planned site, with heat temperature and typical PUE |
| `POST /api/plan` | `ModelResult` | **future data center**: `{"lat", "lon", "it_mw", "cooling_profile", "pue"?, "is_greenfield": 1}`. See below. |
| `GET /api/leaderboard?scope=` | `LeaderboardRow[]` | Opportunity ranking: per listed site the best option that changes something (not today's setup), with NPV, $/yr, CO2, water, payback; sorted by NPV. Cached, warmed at startup (`HEATBEAT_WARM=0` skips). |

## Planning a future data center

In the map, "+ Plan a new data center", click any point, enter the IT load in MW or GW and the cooling.
`POST /api/plan` then returns the same `ModelResult` as for an existing site: baseline, ranked options
with `implementation` (how it would be built) and `capex_breakdown` (plant, heat pump, pipeline), KPIs
(MWh, tCO2, m3, USD/yr, payback, PUE, WUE, ERE), tornado, and every input with its flag.

Where the inputs come from:

| Input | Source | Flag |
|---|---|---|
| IT load, cooling type, heat temperature, greenfield | the form | user |
| PUE | form, else median `pue_assumed` of database sites with that cooling profile | user or estimated |
| Hourly weather | live for the clicked point (Open-Meteo, fallback NASA POWER); offline: nearest site's 2024 weather, with a warning | |
| Power, gas, steam and water prices, grid and fuel CO2, water stress, geology, ecology | nearest database site (distance shown in a warning, extra warning above 300 km) | estimated |
| Distances (heat users, water, coast, biomass, CO2 storage, power plant), land, zoning | US defaults from `INPUT_SPEC` until measured | estimated |

Errors: 404 unknown site or model, 422 bad mode or input, 503 weather not stored and no internet.

## Schema

Defined in `heatbeat_api/schemas.py` (pydantic), mirrored in `frontend/src/types/api.ts`. Units are in
the field names (`_mwh_yr`, `_t_yr`, `_m3_yr`, `_usd`, `_yr`).

- `ModelResult`: `site_id`, `model`, `mode`, `score_scale`, `baseline`, `options`, `tornado`, `warnings`, `inputs_used`.
- `Baseline` (site without a solution): IT and facility energy, heat rejected, PUE, WUE, water, CO2, power bill.
- `OptionResult`: one candidate (with `implementation` text and `capex_breakdown`), either a single option (Excel ranking) or a heat chain (`components`,
  e.g. `["dry_cooler", "heat_pump", "district_heating"]`). `rank`, `feasible`, `score`, `eco_grade`,
  `product`, `ko_reasons`, `kpis`, `energy_balance` (list of `{source, target, mwh_yr, kind}`), `details`.
- `OptionResult.calculation`: step by step trace (`CalcStep`: title, formula, terms with value, unit, flag and source, result). `calculation_inputs`: every input the option uses, with flag and source. The frontend shows both in the "Show calculation" popup. Filled by the engineering model (`heatbeat_engineering/calc_trace.py`); other models may leave them empty.
- `Kpis`: heat recovered and delivered, electricity used and saved (MWh/yr), CO2 avoided (t/yr),
  water saved (m3/yr), net value (USD/yr), CAPEX, payback, PUE/WUE before and after, ERE, COP,
  capacity factor. All optional, so a model fills what it computes.
- `Tornado`: `option_id`, `metric`, `unit`, `base`, `bars` (input, label, low and high value, metric at both ends, flag).

### Input flags

Every input carries one of four flags, shown as a badge in the UI:

| Flag | Meaning | Mapped from (`heatbeat_api.models.flag_for`) |
|---|---|---|
| `real` | measured or looked up for this site | status `data` without "estimate", "confidence low", "team factor" or "proxy" in the source |
| `estimated` | team estimate or a US default that is not site specific | status `assumption`, or `data` whose source says estimate |
| `synthetic` | generated data standing in for missing data | "synthetic" in status or source |
| `user` | set in the UI (greenfield toggle, overrides) | status `user` |

## Plugging in a model

A model is any object with `info` (`ModelInfo`), `site_inputs(site_id, is_greenfield, overrides)` and
`run(site_id, mode, is_greenfield, overrides, weather, tornado)` (protocol `SiteModel` in
`heatbeat_api/models.py`), plus optionally `plan(req: PlanRequest, weather, template_site_id, template_km)`
for planned sites (without it, `/api/plan` answers 501 for that model). The registry imports `heatbeat_engineering.api_model.MODEL` automatically
when that module exists; `info.default=True` makes it the model the map uses. The team Excel ranking
stays available as `?model=excel_ranking`. `ExcelRankingModel` in `models.py` is the reference adapter.

## Known limits

- The Excel ranking baseline sets heat rejected = facility energy (all electricity ends as heat), WUE
  default 1.8 L/kWh unless the profile is chiller free. Both are flagged as estimates.
- `ko_reasons` for the Excel ranking only name the failed gate, not the failing input.
- Results are cached in memory per process; restart the API after changing data files.

## Which sites the map shows

By default the map and the picker list only the sites with documented cooling (heat rejection verified by a source,
25 of 68 sites on 2026-11-26: 24 US plus Nebius Mantsala). The other sites are not deleted: they stay in the database,
in every model output and answer `/api/sites/{id}` and `/ranking` by id.

Show all sites again:

- local: `HEATBEAT_SITES=all ./scripts/dev.sh`
- in the browser, for one visit: add `?sites=all` to the address (the map header has a "show all" link)
- on Render: set the environment variable `HEATBEAT_SITES` to `all` (Dashboard, Environment), or change it in `render.yaml`

## Frontend view (2026-11-26)

The site panel and the planner show the same compact view (`frontend/src/components/Results.tsx`): one line verdict,
today's baseline in one line, the best 3 options that change something (`OptionResult.is_today` marks today's setup
and is left out). Clicking an option opens its four key numbers with definitions (money saved per year, payback,
CO2 avoided, water saved), how it is built, the investment, the calculation steps with inputs (colour = real /
estimate / synthetic, hover for the source), the tornado and all inputs with sources. The button
The map no longer shows the opportunity ranking (removed 2026-11-27 for the demo); `/api/leaderboard` still answers for scripts.
