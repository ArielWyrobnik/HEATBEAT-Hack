"""DSX evaluator (heatbeat_dsx): same numbers as the DSX engine in the frontend (v3.4), gates and API model."""
import math

import numpy as np
import pytest

from heatbeat_dsx import C, OPTIONS, evaluate
from heatbeat_ranking.climate import excel_example_t_amb
from heatbeat_ranking.inputs import us_defaults


def site(**kw):
    x = us_defaults()
    x.update(kw)
    x["baseline_evaporative"] = 1
    x["p_dac_credit_usd_ton"] = x.get("p_dac_credit_usd_ton", 180)
    return x


T = excel_example_t_amb()


def test_reference_numbers_match_the_frontend_engine():
    # computed with frontend/src/dsx/engine.ts v3.3.0 on the same inputs (fuel prices converted to heat basis)
    r = {o["key"]: o for o in evaluate(site(p_dac_credit_usd_ton=0), T)["options"]}
    assert r["biogas"]["viability"] == pytest.approx(3.22)
    assert r["fish_farm_ras"]["viability"] == pytest.approx(2.84)
    assert r["biogas"]["rank"] == 1 and r["fish_farm_ras"]["rank"] == 2
    assert all(r[k]["viability"] == 0 for k in r if k not in ("biogas", "fish_farm_ras"))


def test_weights_sum_to_one_and_score_is_weighted_sum():
    assert sum(C["weights"].values()) == pytest.approx(1) and sum(C["eco_weights"].values()) == pytest.approx(1)
    for o in evaluate(site(), T)["options"]:
        s, w = o["subscores"], C["weights"]
        raw = w["thermo"] * s["p_thermo"] + w["climate"] * s["p_climate"] + w["econ"] * s["p_econ"] + w["util"] * s["p_util"]
        assert o["viability_ungated"] == pytest.approx(raw, abs=0.02)
        assert o["viability"] == (o["viability_ungated"] if o["ko_pass"] else 0)


def test_gate_messages_name_value_and_limit():
    r = {o["key"]: o for o in evaluate(site(d_co2_m=120000), T)["options"]}
    assert r["dac"]["ko_failures"] == ["CO2 storage or user 120.0 km away (limit 50 km)"]
    assert any("only possible when designed in with a new build" in m for m in r["btes_ates"]["ko_failures"])


def test_energy_balance_and_heat_pump():
    for o in evaluate(site(is_greenfield=1, cooling_type="liquid", t_dc_base_c=45, geo_storage_score=4), T)["options"]:
        a = o["annual"]
        if o["key"] != "orc":
            assert a["q_del_mwh"] == pytest.approx(a["q_src_mwh"] + a["w_hp_mwh"], abs=0.2)
        assert a["q_src_mwh"] <= 8760 * 50 * 1.0001


def test_hot_coolant_needs_no_heat_pump_for_low_sinks():
    r = {o["key"]: o for o in evaluate(site(cooling_type="liquid", t_dc_base_c=70), T)["options"]}
    assert r["fish_farm_ras"]["annual"]["w_hp_mwh"] == 0  # 70 C >= 28 + 5 K approach
    assert r["district_heating"]["annual"]["w_hp_mwh"] == 0


def test_dac_is_paid_the_45q_credit():
    x = site(d_co2_m=10000, p_co2_usd_ton=0, p_dac_credit_usd_ton=180)
    dac = next(o for o in evaluate(x, T)["options"] if o["key"] == "dac")
    assert dac["annual"]["value_usd"] == pytest.approx(dac["annual"]["product_qty"] * 180, rel=1e-3)


def test_needs_8760_hours():
    with pytest.raises(ValueError):
        evaluate(site(), np.zeros(100))
    assert len(OPTIONS) == 13


def test_api_model_contract():
    pytest.importorskip("pydantic")
    from heatbeat_dsx.api_model import ANNUITY, MODEL
    x = us_defaults()
    prov = {k: {"status": "assumption", "source": "US default"} for k in x}
    r = MODEL._evaluate("t", x, prov, T, "as_built", True)
    assert r.model == "dsx" and len(r.options) == 13
    feas = [o for o in r.options if o.feasible]
    assert [o.rank for o in feas] == list(range(1, len(feas) + 1))
    assert [o.feasible for o in r.options] == sorted((o.feasible for o in r.options), reverse=True)
    assert all(o.ko_reasons for o in r.options if not o.feasible)
    for o in feas:
        k = o.kpis
        assert k.heat_delivered_mwh_yr == pytest.approx(k.heat_recovered_mwh_yr + k.electricity_used_mwh_yr, abs=0.2)
        assert sum(o.capex_breakdown.values()) == pytest.approx(k.capex_usd, abs=2)
        assert o.details["npv_usd"] == pytest.approx(-k.capex_usd + k.net_value_usd_yr * ANNUITY, abs=2)
        assert o.heat_loops and o.calculation and o.implementation
        # where the server heat goes: loops hold all server heat, the reuse route is the heat recovered
        assert sum(lp.mwh_yr for lp in o.heat_loops) == pytest.approx(r.baseline.it_energy_mwh_yr)
        reuse = [rt for lp in o.heat_loops for rt in lp.routes if rt.kind == "reuse"]
        assert sum(rt.mwh_yr for rt in reuse) == pytest.approx(k.heat_recovered_mwh_yr)
        assert sum(rt.mwh_yr for lp in o.heat_loops for rt in lp.routes) == pytest.approx(r.baseline.it_energy_mwh_yr)
    assert r.tornado and r.tornado.option_id == feas[0].option_id
    assert math.isclose(r.baseline.it_load_mw, x["q_dc_mw"] / 0.9, rel_tol=1e-3)
