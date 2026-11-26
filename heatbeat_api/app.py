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
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import clean, cooling_profiles, default_model, load_models
from .schemas import (CoolingProfile, EvaluateRequest, LeaderboardRow, ModelInfo, ModelResult, PlanDefaults,
                      PlanRequest, SiteInputs, Reference, SiteSummary, Vendor)

# HEATBEAT_LIVE=0 never fetches weather from the internet (CI, offline demo); default 1.
LIVE = os.getenv("HEATBEAT_LIVE", "1") != "0"
# Which sites the map and the picker list (GET /api/sites):
#   verified (default)  only sites whose heat rejection (cooling) is documented by a source, see
#                       heatbeat_data.verification_status(); the others stay in the database and stay
#                       reachable by id (/api/sites/{id}, /ranking), they are just not listed
#   all                 every site in the database
# Show all again:  HEATBEAT_SITES=all ./scripts/dev.sh   (or ?sites=all in the browser address)
SITES_SCOPE = os.getenv("HEATBEAT_SITES", "verified").strip().lower()
SCOPES = ("verified", "all")

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
    try:
        vs = hd.verification_status().set_index("site_id")["status"].to_dict()
    except Exception:  # noqa: BLE001
        vs = {}
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
            is_hypothetical=bool(r.get("is_hypothetical") or 0), weather_stored=r["site_id"] in stored,
            setup_status=vs.get(r["site_id"]))
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


@api.get("/config")
def config() -> dict:
    """Settings the frontend reads at runtime (set as environment variables on the host)."""
    n_all = len(_sites())
    n_ver = sum(s.setup_status == "verified" for s in _sites().values())
    return {"feedback_url": os.getenv("FEEDBACK_URL") or None, "sites_scope": SITES_SCOPE,
            "n_sites_all": n_all, "n_sites_verified": n_ver}


@api.get("/models", response_model=list[ModelInfo])
def models() -> list[ModelInfo]:
    return [m.info for m in MODELS.values()]


@api.get("/sites", response_model=list[SiteSummary])
def sites(country: str | None = Query(None, description="ISO2 filter, e.g. US"),
          scope: str | None = Query(None, description="verified (sites with documented cooling) or all; "
                                    "default from HEATBEAT_SITES, which defaults to verified")) -> list[SiteSummary]:
    scope = (scope or SITES_SCOPE).lower()
    if scope not in SCOPES:
        raise HTTPException(422, f"scope must be one of {SCOPES}")
    out = list(_sites().values())
    if scope == "verified":
        out = [s for s in out if s.setup_status == "verified"]
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
    s = _site(site_id)
    m = _model(model)
    return with_vendors(_cached_run(m.info.name, site_id, mode or m.info.default_mode, is_greenfield), s.lat, s.lon)


def with_vendors(r: ModelResult, lat: float, lon: float, cooling_profile: str | None = None) -> ModelResult:
    """Copy of r with up to 3 companies per option that can build it (heatbeat_data.vendors)."""
    import heatbeat_data as hd
    r = r.model_copy(deep=True)
    for o in r.options:
        if o.feasible:
            o.vendors = [Vendor(**v) for v in hd.vendors_for(o.components, lat, lon)]
            o.references = [Reference(**x) for x in hd.references_for(o.components)]
    for c in r.cascades:
        for st in c.stages:
            st.vendors = [Vendor(**v) for v in hd.vendors_for([st.key], lat, lon, n=1)]
            st.references = [Reference(**x) for x in hd.references_for([st.key], n=1)]
    if cooling_profile:
        r.cooling_vendors = [Vendor(**v) for v in hd.vendors_for_cooling(cooling_profile, lat, lon)]
    return r


def best_change(r: ModelResult):
    """Best feasible option that changes something at the site (not today's setup), or None."""
    return next((o for o in r.options if o.feasible and not o.is_today), None)


COOLING_COMPONENTS = {"dry_cooler", "adiabatic_cooler", "cooling_tower"}


def _npv(o, r: ModelResult) -> float | None:
    """NPV in USD, or None when the model scores options on another scale (e.g. the Excel 0 to 5 score)."""
    v = o.details.get("npv_usd")
    if v is not None:
        return float(v)
    if o.score is not None and r.score_scale.startswith("NPV"):
        return float(o.score) * 1e6
    return None


def best_cooling(r: ModelResult):
    """Cooling perspective: the heat rejection change (no heat use) with the highest NPV, or None."""
    opts = [o for o in r.options if o.feasible and not o.is_today and _npv(o, r) is not None
            and len(o.components) == 1 and o.components[0] in COOLING_COMPONENTS]
    return max(opts, key=lambda o: _npv(o, r), default=None)


def best_heat(r: ModelResult):
    """Heat waste perspective: most reused heat among designs that pay off, else the best reuse NPV.

    Same rule as the site panel ("most heat with positive NPV"). Returns (option, pays_off) or (None, None).
    """
    reuse = [o for o in r.options if o.feasible and (o.kpis.heat_recovered_mwh_yr or 0) > 0]
    if not reuse:
        return None, None
    good = [o for o in reuse if (o.reuse_npv_usd or 0) > 0 and (_npv(o, r) or 0) > 0]
    if good:
        return max(good, key=lambda o: o.kpis.heat_recovered_mwh_yr or 0), True
    return max(reuse, key=lambda o: o.reuse_npv_usd if o.reuse_npv_usd is not None else -1e18), False


@lru_cache(maxsize=4)
def _leaderboard(model_name: str, scope: str) -> tuple[LeaderboardRow, ...]:
    m = MODELS[model_name]
    rows = []
    for s in sites(country=None, scope=scope):
        try:
            r = _cached_run(model_name, s.site_id, m.info.default_mode, None)
        except HTTPException:  # weather missing offline: leave the site out of the ranking
            continue
        o = best_change(r)
        k = o.kpis if o else None
        npv = (o.details.get("npv_usd") if o else None)
        if npv is None and o is not None and o.score is not None and r.score_scale.startswith("NPV"):
            npv = o.score * 1e6
        rows.append(LeaderboardRow(
            site_id=s.site_id, name=s.name, city=s.city, region=s.region, country=s.country, operator=s.operator,
            it_load_mw=r.baseline.it_load_mw, verdict_level=r.verdict_level,
            option_id=o.option_id if o else None, option_name=o.name if o else None, npv_usd=npv,
            cash_value_usd_yr=k.cash_value_usd_yr if k else None, co2_avoided_t_yr=k.co2_avoided_t_yr if k else None,
            water_saved_m3_yr=k.water_saved_m3_yr if k else None, payback_yr=k.payback_yr if k else None,
            **_perspectives(r)))
    rows.sort(key=lambda x: -(x.npv_usd if x.npv_usd is not None else -1e18))
    return tuple(rows)


def _perspectives(r: ModelResult) -> dict:
    c = best_cooling(r)
    h, pays = best_heat(r)
    it = r.baseline.it_energy_mwh_yr or 0
    heat = h.kpis.heat_recovered_mwh_yr if h else None
    return {"cooling_option_name": c.name if c else None, "cooling_npv_usd": _npv(c, r) if c else None,
            "cooling_cash_usd_yr": c.kpis.cash_value_usd_yr if c else None,
            "heat_option_name": h.name if h else None, "heat_reused_mwh_yr": heat,
            "heat_reused_share": (heat / it) if (heat is not None and it > 0) else None,
            "heat_reuse_npv_usd": h.reuse_npv_usd if h else None, "heat_npv_usd": _npv(h, r) if h else None,
            "heat_pays_off": pays}


@api.get("/leaderboard", response_model=list[LeaderboardRow])
def leaderboard(scope: str | None = Query(None, description="verified or all, default as /api/sites"),
                model: str | None = None) -> list[LeaderboardRow]:
    """Data centers ranked by how much the best improvement over today's setup is worth (NPV, best first)."""
    scope = (scope or SITES_SCOPE).lower()
    if scope not in SCOPES:
        raise HTTPException(422, f"scope must be one of {SCOPES}")
    return list(_leaderboard(_model(model).info.name, scope))


@api.post("/evaluate", response_model=ModelResult)
def evaluate(req: EvaluateRequest) -> ModelResult:
    """What-if for a database site: rerun the model with changed inputs (not cached)."""
    s = _site(req.site_id)
    return with_vendors(_run(_model(req.model), req.site_id, req.mode, req.is_greenfield, req.overrides or None, None,
                             req.tornado), s.lat, s.lon)


@api.get("/cooling-profiles", response_model=list[CoolingProfile])
def get_cooling_profiles() -> list[CoolingProfile]:
    return _cooling()


@lru_cache(maxsize=1)
def _cooling() -> list[CoolingProfile]:
    return cooling_profiles()


@lru_cache(maxsize=64)
def _point_weather(lat: float, lon: float) -> pd.DataFrame | None:
    """Hourly weather for any point (Open-Meteo, fallback NASA POWER). None when offline."""
    if not LIVE:
        return None
    from data_pipeline.fetch_weather import fetch_nasa_power, fetch_open_meteo
    for fn in (fetch_open_meteo, fetch_nasa_power):
        try:
            w = fn(lat, lon)
            w.index = pd.to_datetime(w.index, utc=True)
            return w
        except Exception:  # noqa: BLE001
            continue
    return None


@api.get("/plan/defaults", response_model=PlanDefaults)
def plan_defaults(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                  model: str | None = None) -> PlanDefaults:
    """Regional default inputs for any map point so the planning UI can pre-fill customizable parameters."""
    m = _model(model)
    if not hasattr(m, "plan_defaults"):
        raise HTTPException(501, f"model {m.info.name!r} does not expose plan defaults")
    with _lock:
        return m.plan_defaults(lat, lon)


@api.post("/plan", response_model=ModelResult)
def plan(req: PlanRequest) -> ModelResult:
    """A future data center anywhere on the map: location + IT size (MW) + cooling -> ranked options."""
    m = _model(req.model)
    if not hasattr(m, "plan"):
        raise HTTPException(501, f"model {m.info.name!r} cannot plan new sites")
    if req.cooling_profile not in {c.cooling_profile_id for c in _cooling()}:
        raise HTTPException(422, f"unknown cooling_profile {req.cooling_profile!r}, see /api/cooling-profiles")
    if req.mode and req.mode not in m.info.modes:
        raise HTTPException(422, f"mode must be one of {m.info.modes}")
    near, km = nearest_site(req.lat, req.lon, with_weather=True)
    weather = _point_weather(round(req.lat, 2), round(req.lon, 2))
    weather_note = None
    if weather is None:
        import heatbeat_data as hd
        weather = hd.get_site(near.site_id, live=False).weather
        weather_note = (f"Weather for this point could not be fetched (offline), so the 2024 weather of "
                        f"{near.name} ({km:.0f} km away) is used.")
    try:
        with _lock:
            res = m.plan(req, weather, near.site_id, km)
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    if weather_note:
        res.warnings.insert(0, weather_note)
    if km > 300:
        res.warnings.insert(0, f"The nearest database site is {km:.0f} km away: regional prices may not fit.")
    return with_vendors(res, req.lat, req.lon, req.cooling_profile)


def nearest_site(lat: float, lon: float, with_weather: bool = False) -> tuple[SiteSummary, float]:
    """Nearest database site and its distance in km (great circle)."""
    def d(s):
        dlat, dlon = math.radians(s.lat - lat), math.radians(s.lon - lon)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(s.lat)) * math.sin(dlon / 2) ** 2
        return 2 * 6371 * math.asin(math.sqrt(a))
    cands = [s for s in _sites().values() if s.weather_stored or not with_weather]
    best = min(cands, key=d)
    return best, d(best)


app.include_router(api)


@app.on_event("startup")
def _warm_leaderboard() -> None:
    """Fill the ranking cache in the background so the first visitor does not wait (HEATBEAT_WARM=0 skips)."""
    if os.getenv("HEATBEAT_WARM", "1") == "0":
        return

    def run():
        try:
            _leaderboard(DEFAULT_MODEL, SITES_SCOPE if SITES_SCOPE in SCOPES else "verified")
        except Exception:  # noqa: BLE001  warm up only, the endpoint computes on demand anyway
            pass
    threading.Thread(target=run, daemon=True).start()

# Production: serve the built frontend (frontend/dist) from the same process, so one free web service
# hosts the whole app. Set HEATBEAT_STATIC to another folder, or leave dist/ unbuilt for API only.
_STATIC = Path(os.getenv("HEATBEAT_STATIC", Path(__file__).resolve().parents[1] / "frontend" / "dist"))
if (_STATIC / "index.html").exists():
    from fastapi.responses import FileResponse

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        f = (_STATIC / path).resolve()
        if path and f.is_file() and _STATIC.resolve() in f.parents:
            return FileResponse(f)
        if path.startswith("api/"):
            raise HTTPException(404, "unknown API route")
        return FileResponse(_STATIC / "index.html")
