"""API tests (offline: HEATBEAT_LIVE=0, stored weather only)."""
import os

os.environ.setdefault("HEATBEAT_LIVE", "0")

import pytest  # noqa: E402

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from heatbeat_api.app import MODELS, SHOWCASE, app  # noqa: E402
from heatbeat_api.models import ExcelRankingModel, SiteModel, flag_for  # noqa: E402
from heatbeat_api.schemas import ModelResult  # noqa: E402

c = TestClient(app)
SITE = "us-va-ashburn-equinix"
RK = {"model": "excel_ranking"}  # tests of the Excel ranking adapter itself


def test_health_and_models():
    h = c.get("/api/health").json()
    assert h["status"] == "ok" and h["default_model"] in h["models"]
    m = c.get("/api/models").json()
    assert {"excel_ranking"} <= {x["name"] for x in m}
    assert all(isinstance(x, SiteModel) for x in MODELS.values())


def test_sites_for_map():
    s = c.get("/api/sites", params={"scope": "all"}).json()
    assert len(s) >= 40
    for p in s:
        assert -90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180 and p["name"]
    us = c.get("/api/sites", params={"country": "us", "scope": "all"}).json()
    assert us and all(p["country"] == "US" for p in us)
    assert c.get(f"/api/sites/{SITE}").json()["site_id"] == SITE
    assert c.get("/api/sites/nope").status_code == 404


def test_default_lists_only_sites_with_verified_cooling():
    default = c.get("/api/sites").json()
    every = c.get("/api/sites", params={"scope": "all"}).json()
    assert 0 < len(default) < len(every)
    assert all(p["setup_status"] == "verified" or p["site_id"] in SHOWCASE for p in default)
    hidden = next(p for p in every if p["setup_status"] != "verified")
    assert c.get(f"/api/sites/{hidden['site_id']}").status_code == 200  # hidden, not deleted
    assert c.get("/api/sites", params={"scope": "nope"}).status_code == 422
    cfg = c.get("/api/config").json()
    assert cfg["n_sites_verified"] == len(default) and cfg["n_sites_all"] == len(every)


def test_inputs_have_flags_and_sources():
    j = c.get(f"/api/sites/{SITE}/inputs", params=RK).json()
    keys = {i["key"]: i for i in j["inputs"]}
    assert {"q_dc_mw", "p_elec_usd_kwh", "wsi_index", "ci_grid_g_kwh"} <= set(keys)
    assert all(i["flag"] in ("real", "estimated", "synthetic", "user") for i in j["inputs"])
    assert keys["p_elec_usd_kwh"]["flag"] == "real" and keys["p_elec_usd_kwh"]["unit"] == "USD/kWh"
    assert keys["q_dc_mw"]["flag"] == "estimated"  # team estimate, must never show as real
    assert sum(j["flag_counts"].values()) == len(j["inputs"])
    g = c.get(f"/api/sites/{SITE}/inputs", params={**RK, "is_greenfield": 1}).json()
    gf = next(i for i in g["inputs"] if i["key"] == "is_greenfield")
    assert gf["value"] == 1 and gf["flag"] == "user"


@pytest.mark.parametrize("mode", ["corrected", "excel"])
def test_ranking_schema(mode):
    r = c.get(f"/api/sites/{SITE}/ranking", params={**RK, "mode": mode})
    assert r.status_code == 200
    res = ModelResult.model_validate(r.json())
    assert res.mode == mode and len(res.options) == 13
    ranks = [o.rank for o in res.options if o.feasible]
    assert ranks == list(range(1, len(ranks) + 1)) or mode == "excel"
    # feasible options first, knocked out last
    feas = [o.feasible for o in res.options]
    assert feas == sorted(feas, reverse=True)
    assert all(o.ko_reasons for o in res.options if not o.feasible)
    assert res.baseline.it_energy_mwh_yr > 0 and res.baseline.pue >= 1
    if res.tornado:
        assert res.tornado.option_id == next(o.option_id for o in res.options if o.feasible)
        swings = [abs(b.metric_high - b.metric_low) for b in res.tornado.bars]
        assert swings == sorted(swings, reverse=True)


def test_corrected_kpis_and_energy_balance():
    res = ModelResult.model_validate(c.get(f"/api/sites/{SITE}/ranking", params=RK).json())
    best = res.options[0]
    k = best.kpis
    assert k.co2_avoided_t_yr is not None and k.net_value_usd_yr is not None and k.pue_with <= k.pue_baseline
    # energy balance closes: delivered heat = recovered heat + heat pump electricity
    assert k.heat_delivered_mwh_yr == pytest.approx(k.heat_recovered_mwh_yr + (k.electricity_used_mwh_yr or 0))
    assert any("placeholder" in w for w in res.warnings)


def test_bad_requests():
    assert c.get(f"/api/sites/{SITE}/ranking", params={"mode": "nope"}).status_code == 422
    assert c.get(f"/api/sites/{SITE}/ranking", params={"model": "nope"}).status_code == 404
    assert c.get(f"/api/sites/{SITE}/ranking", params={"is_greenfield": 3}).status_code == 422
    assert c.post("/api/evaluate", json={}).status_code == 422
    assert c.post("/api/plan", json={"lat": 40, "lon": -100}).status_code == 422  # it_mw missing
    assert c.post("/api/plan", json={"lat": 40, "lon": -100, "it_mw": 50, "cooling_profile": "x"}).status_code == 422
    assert c.post("/api/plan", json={"lat": 400, "lon": -100, "it_mw": 50}).status_code == 422


def test_evaluate_overrides_change_result():
    base = c.get(f"/api/sites/{SITE}/ranking", params=RK).json()
    r = c.post("/api/evaluate", json={**RK, "site_id": SITE, "overrides": {"d_bio_m": 2000}, "tornado": False})
    assert r.status_code == 200
    j = r.json()
    assert j["tornado"] is None and j["inputs_used"]["d_bio_m"] == 2000
    biogas = lambda res: next(o for o in res["options"] if o["option_id"] == "biogas")  # noqa: E731
    assert biogas(j)["feasible"]
    assert base["inputs_used"]["d_bio_m"] != 2000


def test_cooling_profiles():
    cp = c.get("/api/cooling-profiles").json()
    ids = {p["cooling_profile_id"]: p for p in cp}
    assert {"air_chilled_legacy", "dlc_warm", "dlc_hot"} <= set(ids)
    assert ids["dlc_hot"]["cooling_type"] == "liquid" and ids["dlc_hot"]["heat_temp_c"] > ids["dlc_warm"]["heat_temp_c"]


def test_plan_future_data_center():
    """Any point, size in MW, cooling: ranking with cost and savings (offline: nearest site weather)."""
    body = {**RK, "lat": 41.6, "lon": -93.6, "it_mw": 1000, "cooling_profile": "dlc_hot"}
    r = c.post("/api/plan", json=body)
    assert r.status_code == 200, r.text
    res = ModelResult.model_validate(r.json())
    assert res.planned_site.it_mw == 1000 and res.baseline.it_load_mw == pytest.approx(1000)
    assert res.inputs_used["is_greenfield"] == 1 and res.inputs_used["cooling_type"] == "liquid"
    assert any("offline" in w for w in res.warnings) and any("nearest database site" in w for w in res.warnings)
    flags = {i.key: i.flag for i in res.inputs}
    assert flags["q_dc_mw"] == "user" and flags["d_bio_m"] == "estimated" and flags["p_elec_usd_kwh"] == "estimated"
    feas = [o for o in res.options if o.feasible]
    assert feas, "a 1 GW greenfield site should have feasible options"
    for o in feas:
        assert o.implementation
        assert sum(o.capex_breakdown.values()) == pytest.approx(o.kpis.capex_usd)
    # size scales the result
    small = c.post("/api/plan", json=dict(body, it_mw=10, tornado=False)).json()
    assert small["baseline"]["it_energy_mwh_yr"] == pytest.approx(res.baseline.it_energy_mwh_yr / 100)
    # retrofit has fewer feasible options than greenfield
    retro = c.post("/api/plan", json=dict(body, is_greenfield=0, tornado=False)).json()
    assert sum(o["feasible"] for o in retro["options"]) <= len(feas)


def test_flag_mapping():
    assert flag_for("data", "database: grid_regions") == "real"
    assert flag_for("data", "site_profiles.csv (estimate)") == "estimated"
    assert flag_for("assumption", "x") == "estimated"
    assert flag_for("data", "synthetic shape") == "synthetic"
    assert flag_for("user", "") == "user"


def test_all_us_sites_rank():
    """Every US site with stored weather returns a valid result with the default model (what the map shows)."""
    for s in c.get("/api/sites", params={"country": "US"}).json():
        if not s["weather_stored"]:
            continue
        r = c.get(f"/api/sites/{s['site_id']}/ranking")
        assert r.status_code == 200, (s["site_id"], r.text[:200])


@pytest.mark.parametrize("model", sorted(MODELS))
def test_every_model_fulfils_the_contract(model):
    """Any registered model (Excel ranking, engineering heat chain, ...) gives what the frontend reads."""
    info = MODELS[model].info
    for mode in info.modes:
        r = c.get(f"/api/sites/{SITE}/ranking", params={"model": model, "mode": mode})
        assert r.status_code == 200, (model, mode, r.text[:300])
        res = ModelResult.model_validate(r.json())
        assert res.model == model and res.options and res.baseline.it_energy_mwh_yr
        ranks = [o.rank for o in res.options if o.rank is not None]
        assert ranks == sorted(ranks)
    inp = c.get(f"/api/sites/{SITE}/inputs", params={"model": model}).json()
    assert inp["inputs"] and all(i["flag"] in ("real", "estimated", "synthetic", "user") for i in inp["inputs"])
    if hasattr(MODELS[model], "plan"):
        r = c.post("/api/plan", json={"model": model, "lat": 41.6, "lon": -93.6, "it_mw": 300,
                                      "cooling_profile": "dlc_warm", "tornado": False})
        assert r.status_code == 200, (model, r.text[:300])
        planned = ModelResult.model_validate(r.json())
        assert planned.baseline.it_load_mw == pytest.approx(300, rel=0.01)
        if model == "heat_chain":
            reuse = max((o for o in planned.options if o.feasible), key=lambda o: o.kpis.heat_recovered_mwh_yr)
            assert {loop.name for loop in reuse.heat_loops} == {"air", "liquid"}
            assert sum(loop.mwh_yr for loop in reuse.heat_loops) == pytest.approx(planned.baseline.it_energy_mwh_yr)
            routes = [route for loop in reuse.heat_loops for route in loop.routes if route.kind == "reuse"]
            assert routes and sum(route.mwh_yr for route in routes) == pytest.approx(reuse.kpis.heat_recovered_mwh_yr)


def test_adapter_is_a_site_model():
    assert isinstance(ExcelRankingModel(), SiteModel)


def test_leaderboard_ranks_sites_by_best_change():
    rows = c.get("/api/leaderboard", params={"scope": "verified"}).json()
    listed = {s["site_id"] for s in c.get("/api/sites", params={"scope": "verified"}).json()}
    assert rows and {r["site_id"] for r in rows} <= listed
    npv = [r["npv_usd"] for r in rows if r["npv_usd"] is not None]
    assert npv == sorted(npv, reverse=True)
    top = rows[0]
    assert top["option_name"] and "today's setup" not in top["option_name"]
    # the row restates the best non-today option of the site's own ranking
    res = ModelResult.model_validate(c.get(f"/api/sites/{top['site_id']}/ranking").json())
    best = next(o for o in res.options if o.feasible and not o.is_today)
    assert best.option_id == top["option_id"]
    assert abs(best.kpis.cash_value_usd_yr - top["cash_value_usd_yr"]) < 1
    assert sum(o.is_today for o in res.options) <= 1


def test_leaderboard_has_cooling_and_heat_waste_perspectives():
    rows = c.get("/api/leaderboard", params={"scope": "verified"}).json()
    assert any(r["cooling_npv_usd"] is not None for r in rows)
    assert any(r["heat_reused_mwh_yr"] for r in rows)
    for r in rows:
        if r["heat_pays_off"]:
            assert r["heat_reuse_npv_usd"] > 0 and r["heat_npv_usd"] > 0
        if r["heat_reused_share"] is not None:
            assert 0 <= r["heat_reused_share"] <= 1
    r = next(x for x in rows if x["cooling_option_name"])
    res = ModelResult.model_validate(c.get(f"/api/sites/{r['site_id']}/ranking").json())
    o = next(o for o in res.options if o.name == r["cooling_option_name"])
    assert len(o.components) == 1 and not o.is_today


def test_plan_defaults_and_budget_mode():
    d = c.get("/api/plan/defaults", params={"lat": 41.6, "lon": -93.6})
    assert d.status_code == 200
    dj = d.json()
    keys = {i["key"]: i["value"] for i in dj["inputs"]}
    assert keys["liquid_heat_share"] == pytest.approx(0.95)
    assert keys["t_liquid_supply_c"] == pytest.approx(45.0)
    assert keys["t_liquid_return_c"] == pytest.approx(55.0)
    assert keys["compute_capex_usd_mw"] == pytest.approx(25_000_000.0)

    # Default cooling_profile is Vera Rubin (dlc_hot) and budget_usd solves IT MW + rack count
    r = c.post("/api/plan", json={"lat": 41.6, "lon": -93.6, "budget_usd": 500_000_000, "tornado": False})
    assert r.status_code == 200, r.text
    res = ModelResult.model_validate(r.json())
    assert res.baseline.cooling_profile == "dlc_hot"
    assert res.budget_summary is not None
    assert res.budget_summary.budget_usd == pytest.approx(500_000_000)
    assert 10.0 <= res.budget_summary.solved_it_mw <= 16.0
    assert res.budget_summary.vera_rubin_racks > 0
    assert res.budget_summary.total_build_capex_usd <= 500_000_000 * 1.01
    feas = [o for o in res.options if o.feasible]
    assert feas and "budget_fit" in feas[0].details

    # Retrofit omits default facility shell cost so more compute fits in the same budget
    retro = c.post("/api/plan", json={"lat": 41.6, "lon": -93.6, "budget_usd": 500_000_000,
                                      "is_greenfield": 0, "tornado": False})
    assert retro.status_code == 200
    assert retro.json()["budget_summary"]["solved_it_mw"] > res.budget_summary.solved_it_mw

    # Validation: missing both it_mw and budget_usd, or tiny budget
    assert c.post("/api/plan", json={"lat": 41.6, "lon": -93.6}).status_code == 422
    assert c.post("/api/plan", json={"lat": 41.6, "lon": -93.6, "budget_usd": 500_000}).status_code == 422


def test_heat_waste_cascades_in_result():
    # heat reuse only straight from a GPU liquid loop: a chilled water site gets a liquid cooling retrofit
    r = c.get(f"/api/sites/{SITE}/ranking", params={"tornado": False})
    assert r.status_code == 200, r.text
    rc = r.json()["cascades"]
    assert rc and all(x["retrofit_capex_usd"] > 0 and x["t_top_c"] >= 35 for x in rc)
    r = c.get("/api/sites/us-or-the-dalles-google/ranking", params={"tornado": False})
    assert r.status_code == 200, r.text
    cs = r.json()["cascades"]
    assert 1 <= len(cs) <= 2
    assert all(x["t_top_c"] >= 35 for x in cs)
    assert all(x["stages"] and 0 < x["heat_used_share"] <= 1 for x in cs)
