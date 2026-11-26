"""Wind radiator (heat rejection tech "wind"): physics limits, bookkeeping and integration in the chains."""
import numpy as np
import pytest

from heatbeat_engineering import defaults, evaluate_site, synthetic_site
from heatbeat_engineering.chains import build_plans, simulate, site_techs
from heatbeat_engineering.heat_rejection import capex_usd, reject, wind_panel_capex_usd, wind_passive_mw

P = defaults()
H = 8760


def test_no_wind_no_passive_heat_and_same_as_dry():
    t = np.full(H, 10.0)
    w = reject("wind", 1.0, 45, 55, t, t - 3, P, wind_ms=np.zeros(H))
    d = reject("dry", 1.0, 45, 55, t, t - 3, P)
    assert w["passive_mwh"] == pytest.approx(0, abs=1e-6)
    for k in ("fan_mwh", "chiller_mwh", "q_rejected_mwh"):
        assert w[k] == pytest.approx(d[k])


def test_passive_heat_capped_by_load_and_air_temperature():
    t = np.linspace(-10, 60, H)
    pas = wind_passive_mw(np.ones(H), 45, 55, t, np.full(H, 30.0), P, 1.0)["q_passive_mw"]
    assert (pas <= 1.0 + 1e-12).all()
    assert (pas[t >= 55] == 0).all()  # air warmer than the loop return takes no heat
    # never cools the loop below the air temperature: q <= c_w (T_ret - T_db)
    assert (pas <= 0.1 * np.clip(55 - t, 0, None) + 1e-9).all()


def test_more_wind_more_passive_heat_and_fewer_fan_hours():
    t = np.full(H, 20.0)
    lo = reject("wind", 1.0, 45, 55, t, t - 4, P, wind_ms=np.full(H, 1.0))
    hi = reject("wind", 1.0, 45, 55, t, t - 4, P, wind_ms=np.full(H, 6.0))
    assert hi["passive_mwh"] > lo["passive_mwh"]
    assert hi["fan_mwh"] <= lo["fan_mwh"]


def test_wind_needs_wind_data():
    s = synthetic_site()
    assert "wind" not in site_techs(s)
    assert simulate(s, P, "wind")["ko"]
    with pytest.raises(ValueError):
        reject("wind", 1.0, 45, 55, np.zeros(H), np.zeros(H), P)


def test_energy_balance_and_capex_on_existing_dry_site():
    s = synthetic_site(wind_ms=4.0, d_coast_m=3000.0)
    plans = build_plans(s, P)
    base = simulate(s, P, "dry", (), plans=plans)
    r = simulate(s, P, "wind", (), plans=plans, baseline=base)
    assert abs(r["balance_residual_mwh"]) < 1e-3
    assert r["details"]["wind_radiator"]["passive_share"] > 0.5
    assert r["fan_mwh"] < base["fan_mwh"]
    # dry cooler already there: only the panels are new
    q = sum(l.q_mw for l in s.loops)
    assert r["capex"]["heat_rejection"] == pytest.approx(wind_panel_capex_usd(q, P))
    assert capex_usd("wind", 1.0, P) == pytest.approx(wind_panel_capex_usd(1.0, P) + capex_usd("dry", 1.0, P))
    r2 = simulate(s, P, "wind", ("dh_5km",), plans=plans)
    assert abs(r2["balance_residual_mwh"]) < 1e-3


def test_wind_chains_ranked_with_the_others():
    df, _, res = evaluate_site(synthetic_site(wind_ms=4.0))
    assert (df["tech"] == "wind").any()
    assert all(abs(res[c]["balance_residual_mwh"]) < 1e-3 for c in df["chain_id"])
