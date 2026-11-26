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
    assert n > 50


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
