"""HEATBEAT API: map pins, site inputs and model results for the frontend.

Run:  uvicorn heatbeat_api.app:app --reload --port 8000     (or ./scripts/dev.sh for API + frontend)
Docs: http://127.0.0.1:8000/docs (interactive, generated from heatbeat_api/schemas.py)

Every route lives under /api so the Vite dev server can proxy /api to this process.
"""
from __future__ import annotations

import math
import os
import threading
from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import clean, default_model, load_models
from .schemas import EvaluateRequest, ModelInfo, ModelResult, SiteInputs, SiteSummary

# HEATBEAT_LIVE=0 never fetches weather from the internet (CI, offline demo); default 1.
LIVE = os.getenv("HEATBEAT_LIVE", "1") != "0"

app = FastAPI(title="HEATBEAT API", version="0.1.0",
              description="Which waste stream solution is the most feasible at this data center?")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
api = APIRouter(prefix="/api")

MODELS = load_models()
DEFAULT_MODEL = default_model(MODELS)
_lock = threading.Lock()  # heatbeat_data opens SQLite per query; serialize model runs to keep it simple


def _model(name: str | None):
    name = name or DEFAULT_MODEL
    if name not in MODELS:
        raise HTTPException(404, f"unknown model {name!r}; available: {list(MODELS)}")
    return MODELS[name]


def _num(v):
    v = clean(v)
    return None if v is None else float(v)


def _str(v):
    v = clean(v)
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)


@lru_cache(maxsize=1)
def _sites() -> dict[str, SiteSummary]:
    import heatbeat_data as hd
    s = hd.list_sites()
    hp = hd.site_heat_profiles().set_index("site_id")
    stored = set(hd._q("SELECT DISTINCT site_id FROM weather_hourly")["site_id"])
    try:
        from data_pipeline.common import CACHE_DIR
        stored |= {p.stem for p in (CACHE_DIR / "weather").glob("*.parquet")}
    except Exception:  # noqa: BLE001
        pass
    out = {}
    for r in s.to_dict("records"):
        h = hp.loc[r["site_id"]].to_dict() if r["site_id"] in hp.index else {}
        out[r["site_id"]] = SiteSummary(
            site_id=r["site_id"], name=r["name"], lat=float(r["lat"]), lon=float(r["lon"]),
            operator=_str(r.get("operator")), city=_str(r.get("city")), region=_str(r.get("region")),
            country=_str(r.get("country_iso2")), capacity_mw=_num(r.get("capacity_mw")),
            it_load_mw=_num(h.get("it_load_mw")), cooling_type=_str(h.get("cooling_type")),
            pue=_num(h.get("pue_assumed")), grid_region=_str(r.get("grid_region_name")),
            retail_usd_mwh=_num(r.get("retail_industrial_usd_mwh")), co2_kg_mwh=_num(r.get("co2_kg_mwh")),
            is_hypothetical=bool(r.get("is_hypothetical") or 0), weather_stored=r["site_id"] in stored)
    return out


def _site(site_id: str) -> SiteSummary:
    s = _sites().get(site_id)
    if s is None:
        raise HTTPException(404, f"unknown site_id {site_id!r}")
    return s


def _run(model, site_id, mode, is_greenfield=None, overrides=None, weather=None, tornado=True) -> ModelResult:
    mode = mode or model.info.default_mode
    if mode not in model.info.modes:
        raise HTTPException(422, f"mode must be one of {model.info.modes}")
    try:
        with _lock:
            return model.run(site_id, mode, is_greenfield=is_greenfield, overrides=overrides,
                             weather=weather, tornado=tornado)
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:  # weather not stored and live fetch failed
        raise HTTPException(503, str(e)) from e


@lru_cache(maxsize=256)
def _cached_run(model_name, site_id, mode, is_greenfield) -> ModelResult:
    return _run(MODELS[model_name], site_id, mode, is_greenfield)


@api.get("/health")
def health() -> dict:
    return {"status": "ok", "models": list(MODELS), "default_model": DEFAULT_MODEL, "live_weather": LIVE}


@api.get("/models", response_model=list[ModelInfo])
def models() -> list[ModelInfo]:
    return [m.info for m in MODELS.values()]


@api.get("/sites", response_model=list[SiteSummary])
def sites(country: str | None = Query(None, description="ISO2 filter, e.g. US")) -> list[SiteSummary]:
    out = list(_sites().values())
    if country:
        out = [s for s in out if (s.country or "").upper() == country.upper()]
    return out


@api.get("/sites/{site_id}", response_model=SiteSummary)
def site(site_id: str) -> SiteSummary:
    return _site(site_id)


@api.get("/sites/{site_id}/inputs", response_model=SiteInputs)
def site_inputs(site_id: str, model: str | None = None,
                is_greenfield: int | None = Query(None, ge=0, le=1)) -> SiteInputs:
    _site(site_id)
    m = _model(model)
    with _lock:
        values = m.site_inputs(site_id, is_greenfield=is_greenfield)
        weather = {}
        try:
            import heatbeat_data as hd
            weather = {k: clean(v) for k, v in hd.get_site(site_id, live=LIVE).summary().items()}
        except Exception as e:  # noqa: BLE001  weather missing offline: inputs still useful
            weather = {"error": f"weather not available: {e}"}
    counts: dict[str, int] = {}
    for v in values:
        counts[v.flag] = counts.get(v.flag, 0) + 1
    return SiteInputs(site_id=site_id, inputs=values, weather=weather, flag_counts=counts)


@api.get("/sites/{site_id}/ranking", response_model=ModelResult)
def ranking(site_id: str, model: str | None = None, mode: str | None = None,
            is_greenfield: int | None = Query(None, ge=0, le=1)) -> ModelResult:
    _site(site_id)
    m = _model(model)
    return _cached_run(m.info.name, site_id, mode or m.info.default_mode, is_greenfield)


@api.post("/evaluate", response_model=ModelResult)
def evaluate(req: EvaluateRequest) -> ModelResult:
    """Run a model with changed inputs (what-if), or at a custom location (nearest site as template)."""
    m = _model(req.model)
    weather = None
    site_id = req.site_id
    if site_id is None:
        if req.lat is None or req.lon is None:
            raise HTTPException(422, "give site_id, or lat and lon")
        site_id = nearest_site(req.lat, req.lon).site_id
        if not LIVE:
            raise HTTPException(503, "custom coordinates need a live weather fetch (HEATBEAT_LIVE=0)")
        try:
            from data_pipeline.fetch_weather import fetch_nasa_power, fetch_open_meteo
            weather = None
            for fn in (fetch_open_meteo, fetch_nasa_power):
                try:
                    weather = fn(req.lat, req.lon)
                    break
                except Exception:  # noqa: BLE001
                    continue
            if weather is None:
                raise RuntimeError("live weather fetch failed (internet?)")
            weather.index = pd.to_datetime(weather.index, utc=True)
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
    else:
        _site(site_id)
    res = _run(m, site_id, req.mode, req.is_greenfield, req.overrides or None, weather, req.tornado)
    if req.site_id is None:
        res.warnings.insert(0, f"Custom location {req.lat:.3f}, {req.lon:.3f}: weather fetched live, all other "
                               f"inputs taken from the nearest database site {site_id} (estimated).")
    return res


def nearest_site(lat: float, lon: float) -> SiteSummary:
    def d(s):
        dlat, dlon = math.radians(s.lat - lat), math.radians(s.lon - lon)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(s.lat)) * math.sin(dlon / 2) ** 2
        return 2 * 6371 * math.asin(math.sqrt(a))
    return min(_sites().values(), key=d)


app.include_router(api)
