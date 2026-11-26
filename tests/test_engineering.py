"""Physics and bookkeeping checks of the engineering heat chain model (heatbeat_engineering)."""
import numpy as np
import pytest

from heatbeat_engineering import defaults, evaluate_site, synthetic_site
from heatbeat_engineering import heat_pump as hp
from heatbeat_engineering.biogas import heat_demand
from heatbeat_engineering.chains import build_plans, enumerate_chains, simulate
from heatbeat_engineering.heat_rejection import reject
from heatbeat_engineering.industry import med_effects, orc_efficiency
from heatbeat_engineering.sinks import pipe

P = defaults()


def test_energy_balance_closes_for_every_chain():
    s = synthetic_site(d_coast_m=3000.0)
    plans = build_plans(s, P)
    n = 0
    for tech, uses, st in enumerate_chains(plans):
        r = simulate(s, P, tech, uses, st, plans=plans)
        if r.get("ko"):
            continue
        n += 1
        assert abs(r["balance_residual_mwh"]) < 1e-3 * r["balance_in_mwh"] / 1e6 + 1e-3, (tech, uses, st)
        assert sum(loop["mwh_yr"] for loop in r["heat_loops"]) == pytest.approx(r["it_mwh"])
        assert sum(route["mwh_yr"] for loop in r["heat_loops"] for route in loop["routes"]
                   if route["kind"] == "reuse") == pytest.approx(r["heat_recovered_mwh"])
        for loop in r["heat_loops"]:
            assert sum(route["mwh_yr"] for route in loop["routes"]) == pytest.approx(loop["mwh_yr"])
    assert n > 50


def test_adsorption_counts_drive_heat_as_reuse_and_air_load_as_cooling():
    s = synthetic_site(t_mean=18, liquid_share=0.6)
    r = simulate(s, P, "tower", ("adsorption",))
    liquid, air = r["heat_loops"]
    drive = next(route for route in liquid["routes"] if route["kind"] == "reuse")
    air_cooling = next(route for route in air["routes"] if route["name"].startswith("Adsorption chiller"))
    assert air_cooling["kind"] == "cooling"
    assert air_cooling["mwh_yr"] == pytest.approx(drive["mwh_yr"] * P["ads_cop"])
    assert r["heat_recovered_mwh"] == pytest.approx(drive["mwh_yr"])


def test_site_ranking_includes_the_most_heat_intensive_options():
    pytest.importorskip("pyarrow")
    pytest.importorskip("fastapi")
    from heatbeat_engineering.api_model import MODEL
    from heatbeat_engineering.site import load_site

    site_id = "us-ga-atlanta-qts"
    table, _, chains = evaluate_site(load_site(site_id, live=False))
    most_heat = sorted(table["chain_id"], key=lambda cid: chains[cid]["heat_recovered_mwh"], reverse=True)[:3]
    assert set(most_heat) - set(table["chain_id"].head(10))
    result = MODEL.run(site_id, tornado=False)
    assert set(most_heat) <= {o.option_id for o in result.options}


def test_district_heating_labels_screening_distance_and_user_override():
    pytest.importorskip("pyarrow")
    from heatbeat_engineering.site import load_site, set_input

    site = load_site("us-ok-pryor-google", live=False)
    assert site.prov["d_dh_m"]["status"] == "estimate"
    assert "60 km modeled network, 7.2 km line lower bound" in build_plans(site, P)["dh_60km"].label
    set_input(site, "d_dh_m", 4200)
    assert "60 km modeled network, 4.2 km specified line" in build_plans(site, P)["dh_60km"].label


def test_district_heating_uses_smaller_equipment_to_cover_part_of_peak():
    site = synthetic_site()
    plans = build_plans(site, P)
    full = simulate(site, P, "dry", ("dh_20km",), plans=plans)
    sized = simulate(site, P, "dry", ("dh_20km_peak35",), plans=plans)
    full_dh = full["details"]["dh_20km"]
    sized_dh = sized["details"]["dh_20km_peak35"]
    assert sized_dh["peak_mw"] == pytest.approx(full_dh["peak_mw"] * 0.35, abs=0.01)
    assert sized_dh["dn_mm"] < full_dh["dn_mm"]
    assert sized["capex"]["heat_pump"] < full["capex"]["heat_pump"]
    assert sized_dh["community_demand_mwh"] == full_dh["community_demand_mwh"]
    assert 0 < sized_dh["served_share"] < full_dh["served_share"]


def test_site_ranking_includes_the_profitable_heat_and_reuse_value_winners():
    pytest.importorskip("pyarrow")
    pytest.importorskip("fastapi")
    from heatbeat_engineering.api_model import MODEL
    from heatbeat_engineering.site import load_site

    site_id = "us-ok-pryor-google"
    _, _, results = evaluate_site(load_site(site_id, live=False))
    reuse = [r for r in results.values() if r["heat_recovered_mwh"] > 0]
    by_value = max(reuse, key=lambda r: r["reuse_npv_usd"])
    profitable = [r for r in reuse if r["reuse_npv_usd"] > 0 and r["npv_usd"] > 0]
    by_heat = max(profitable, key=lambda r: r["heat_recovered_mwh"])
    options = {o.option_id: o for o in MODEL.run(site_id, tornado=False).options}
    for winner in (by_value, by_heat):
        option = options[winner["chain_id"]]
        assert option.reuse_npv_usd == pytest.approx(winner["reuse_npv_usd"])
        assert option.kpis.heat_recovered_mwh_yr == pytest.approx(winner["heat_recovered_mwh"])


def test_heat_pump_below_carnot_and_falls_with_lift():
    c1, c2 = float(hp.cop(45, 70, P)), float(hp.cop(45, 90, P))
    assert c1 > c2 > 1
    assert c1 < float(hp.carnot_cop(45, 70))


def test_orc_is_honestly_poor_at_55c():
    eta = orc_efficiency(55, np.full(10, 15.0), P)
    carnot = 1 - (15 + P["orc_cond_above_air_k"] + 273.15) / (55 - P["hx_approach_k"] + 273.15)
    assert 0 < eta.max() < carnot
    assert eta.max() < 0.06


def test_tower_water_and_dry_cooler_has_none():
    t_db, t_wb = np.full(8760, 25.0), np.full(8760, 18.0)
    tw = reject("tower", 10.0, 32, 42, t_db, t_wb, P)
    m3_per_mwh = tw["water_m3"] / tw["q_rejected_mwh"]
    assert 1.4 < m3_per_mwh < 2.2  # 1 kg per 2.43 MJ x latent share x cycles/(cycles-1)
    assert reject("dry", 10.0, 32, 42, t_db, t_wb, P)["water_m3"] == 0


def test_dry_cooler_needs_trim_chiller_when_hot():
    hot = reject("dry", 10.0, 32, 42, np.full(8760, 35.0), np.full(8760, 22.0), P)
    cold = reject("dry", 10.0, 32, 42, np.full(8760, 5.0), np.full(8760, 2.0), P)
    assert hot["chiller_mwh"] > 0 and cold["chiller_mwh"] == 0
    assert hot["fan_mwh"] > cold["fan_mwh"]  # fan affinity law: smaller temperature difference, more air


def test_digester_needs_more_heat_in_cold_climate():
    cold, _ = heat_demand(synthetic_site(t_mean=5.0), P, 38)
    warm, _ = heat_demand(synthetic_site(t_mean=25.0), P, 38)
    assert cold.sum() > 1.5 * warm.sum()


def test_med_effects_depend_on_source_temperature():
    s = synthetic_site(t_mean=18.0)
    assert med_effects(55, s, P) >= 5
    assert med_effects(35, s, P) <= 2 < med_effects(55, s, P) - 5


def test_pipe_scales():
    a = pipe(1000, 10, 70, 40, 10, P)
    b = pipe(5000, 10, 70, 40, 10, P)
    c = pipe(1000, 50, 70, 40, 10, P)
    assert b["loss_mw"] > a["loss_mw"] and c["dn_mm"] > a["dn_mm"]


def test_adsorption_ko_below_drive_temperature():
    s = synthetic_site(t_ret=42.0, t_sup=32.0, liquid_share=0.5)
    assert build_plans(s, P)["adsorption"].ko


def test_runs_in_cold_and_hot_climate():
    best = set()
    for t_mean, water in ((2.0, 1.0), (24.0, 8.0)):
        df, _, _ = evaluate_site(synthetic_site(t_mean=t_mean, p_water_usd_m3=water, liquid_share=0.6, t_sup=32, t_ret=42))
        best.add(df.iloc[0]["tech"])
    assert len(best) >= 1  # smoke: runs for both climates
    assert df["balance_residual_mwh"].abs().max() < 1e-3


def test_real_site_and_planned_site_offline():
    pytest.importorskip("pyarrow")
    import heatbeat_data as hd
    from heatbeat_engineering import evaluate
    try:
        hd.get_site("us-tx-dallas-infomart", live=False).weather.iloc[8759]
    except (IndexError, FileNotFoundError):
        pytest.skip("no stored weather for the test site")
    df, base, res, case = evaluate(site_id="us-tx-dallas-infomart", live=False)
    assert len(df) > 10 and df["balance_residual_mwh"].abs().max() < 1e-3
    df2, _, _, c2 = evaluate(32.9, -96.9, 500, "dlc_warm", live=False)
    assert c2.it_mw == 500 and c2.x["is_greenfield"] and len(df2) > 10


def test_calculation_trace_restates_the_results():
    """Every option carries a step by step calculation whose results match its KPIs, with sourced inputs."""
    pytest.importorskip("pyarrow")
    pytest.importorskip("fastapi")
    import heatbeat_data as hd
    from heatbeat_engineering.api_model import MODEL
    try:
        hd.get_site("us-tx-dallas-infomart", live=False).weather.iloc[8759]
    except (IndexError, FileNotFoundError):
        pytest.skip("no stored weather for the test site")
    r = MODEL.run("us-tx-dallas-infomart", tornado=False)
    for o in (o for o in r.options if o.feasible):
        steps = {s.title: s for s in o.calculation}
        assert steps["NPV and payback"].result == pytest.approx(o.score * 1e6, abs=1e4)
        assert steps["Net value per year"].result == pytest.approx(o.kpis.net_value_usd_yr)
        assert steps["PUE with this solution"].result == pytest.approx(o.kpis.pue_with)
        assert abs(steps["Energy balance check"].result) < 1e-3
        assert o.calculation_inputs and all(i.source for i in o.calculation_inputs if i.flag == "real")


def test_storage_that_shifts_nothing_is_ko():
    # a small community next to a big source never has unmet demand: storage chains must not appear
    site = synthetic_site(it_mw=200.0, rho_heat_mwh_m=0.5)
    df, _, results = evaluate_site(site)
    dh = df[df["uses"].str.contains("dh_")]
    assert len(dh) > 0
    assert (dh["storage"] == "").all()


def test_biogas_capex_counts_upgrading_and_new_digester():
    P = defaults()
    near = synthetic_site(d_bio_m=500.0)
    far = synthetic_site(d_bio_m=40000.0)
    for s in (near, far):
        pl = build_plans(s, P)["biogas_meso"]
        out = pl.settle(pl.demand_mw)
        d = out["detail"]
        assert d["upgrade_capex_usd"] > 0
        if d["logistics"] == "truck feedstock to DC":
            assert d["digester_capex_usd"] > 0
        else:
            assert d["digester_capex_usd"] == 0
        assert out["capex_usd"] > d["upgrade_capex_usd"]


def test_net_value_splits_into_cash_and_water_value():
    df, _, results = evaluate_site(synthetic_site())
    for r in results.values():
        assert r["cash_value_usd_yr"] + r["water_value_usd_yr"] == pytest.approx(r["net_value_usd_yr"])
