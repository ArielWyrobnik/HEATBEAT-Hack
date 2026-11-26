"""Checks on per-site water data (tariffs, WUE model). Needs no database build or network."""
import numpy as np
import pandas as pd

from heatbeat_data import water as wt

DP = wt._DIR


def test_every_us_site_has_one_row():
    sites = pd.read_csv(DP / "sites.csv")
    us = set(sites.loc[sites["country_iso2"] == "US", "site_id"])
    t = wt.water_tariffs()
    assert t["site_id"].is_unique
    assert set(t["site_id"]) == us


def test_ranges_ordered_and_plausible():
    t = wt.water_tariffs()
    for k in ("p_water_usd_m3", "p_sewer_usd_m3"):
        assert (t[f"{k}_low"] <= t[k]).all() and (t[k] <= t[f"{k}_high"]).all()
        assert t[k].between(0.1, 10).all()
    assert t["tariff_basis"].isin(["tariff", "estimate"]).all()
    assert (t.loc[t["tariff_basis"] == "estimate", "water_is_estimated"] == 1).all()


def test_sources_resolve():
    ids = set(wt.water_sources()["source_id"])
    used = {s for col in (wt.water_tariffs()["source_ids"], wt.wue_profiles()["source_ids"])
            for v in col for s in v.split(";")}
    assert used <= ids, used - ids


def test_every_profile_has_wue():
    from heatbeat_data.heat_profiles import cooling_profiles
    prof = set(wt.wue_profiles()["cooling_profile_id"])
    assert set(cooling_profiles()["cooling_profile_id"]) <= prof
    p = wt.wue_profiles()
    assert ((p["wue_l_kwh_low"] <= p["wue_l_kwh"]) & (p["wue_l_kwh"] <= p["wue_l_kwh_high"])).all()


def _weather(t_db, t_wb):
    idx = pd.date_range("2024-01-01", periods=len(t_db), freq="h", tz="UTC")
    return pd.DataFrame({"t_db_c": t_db, "t_wb_c": t_wb}, index=idx)


def test_hourly_wue_physics():
    hot = _weather([38.0] * 24, [20.0] * 24)
    cold = _weather([-5.0] * 24, [-6.0] * 24)
    # cooling tower: about 1.48 L/kWh * 4/3 * (1 + 1/6) when chillers run
    assert np.isclose(wt.hourly_wue(hot, "air_chilled_legacy").mean(), 1.4815 * 4 / 3 * 7 / 6, rtol=1e-3)
    # dry coolers on cold hours for warm liquid cooling (liquid share only)
    assert wt.hourly_wue(cold, "dlc_hot", liquid_share=1.0).mean() == 0
    assert wt.hourly_wue(hot, "dlc_hot", liquid_share=1.0).mean() > 0
    # adiabatic economizer uses water only on hot hours
    assert wt.hourly_wue(cold, "air_economizer").mean() == 0
    assert 0.5 < wt.hourly_wue(hot, "air_economizer").mean() < 2.5
    assert wt.hourly_wue(hot, "closed_loop_dry").mean() == 0


def test_site_water_table():
    df = wt.site_water()
    assert len(df) == len(wt.water_tariffs())
    assert (df["water_m3_yr_low"] <= df["water_m3_yr"]).all()
    assert (df["water_cost_usd_yr"] >= 0).all()
    assert df["discharge_share"].between(0, 1).all()
    w = {"us-az-chandler": _weather([30.0] * 48, [18.0] * 48)}
    row = wt.site_water(w).set_index("site_id").loc["us-az-chandler"]
    assert row["wue_method"] == "hourly_weather"
