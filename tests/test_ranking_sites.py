"""Ranking engine on database sites. Needs a built database (python -m data_pipeline.build_db --offline)."""
import pytest

import heatbeat_data as hd
from heatbeat_ranking import input_influence, rank_site, tornado
from heatbeat_ranking import inputs as ri

try:
    US = [s for s in hd.list_sites()["site_id"] if s.startswith("us-")]
except Exception:  # noqa: BLE001
    US = []
pytestmark = pytest.mark.skipif(not US, reason="no database built")


def test_site_inputs_use_data_and_flag_the_rest():
    x, prov = ri.site_inputs(US[0])
    assert set(x) == set(ri.INPUT_SPEC)
    assert prov["ci_grid_g_kwh"]["status"] == "data"
    assert prov["q_dc_mw"]["status"] == "data"
    assert prov["d_bio_m"]["status"] in ("assumption", "data")
    assert all(p["status"] in ("data", "assumption", "user") for p in prov.values())


def test_override_files_are_read(tmp_path, monkeypatch):
    (tmp_path / "site_ranking_inputs_test.csv").write_text(
        f"site_id,key,value,status,source,note\n{US[0]},d_bio_m,1234,data,unit test,\n"
        f"{US[0]},ind_zoning,0,assumption,unit test,\n")
    monkeypatch.setattr(ri, "PIPELINE_DIR", tmp_path)
    x, prov = ri.site_inputs(US[0])
    assert x["d_bio_m"] == 1234.0 and prov["d_bio_m"]["status"] == "data"
    assert x["ind_zoning"] == 0.0


@pytest.mark.parametrize("weather", ["hourly", "daily_cosine"])
def test_rank_site_both_weather_methods(weather):
    df, x, _ = rank_site(US[0], weather=weather, live=False)
    assert len(df) == 13
    assert df["rank"].iloc[0] in (1, "KO")
    assert {"co2_avoided_t", "water_saved_m3", "payback_yr", "ere"} <= set(df.columns)


def test_greenfield_toggle_unlocks_options():
    a, _, _ = rank_site(US[0], is_greenfield=0, live=False)
    b, _, _ = rank_site(US[0], is_greenfield=1, live=False)
    assert b["ko_gate"].sum() >= a["ko_gate"].sum()


def test_sensitivity_outputs():
    import heatbeat_data as hd
    from heatbeat_ranking.climate import hourly_from_site
    x, _ = ri.site_inputs(US[0])
    t = hourly_from_site(hd.get_site(US[0], live=False))
    tor = tornado(x, t, "fish_farm")
    assert "p_co2_usd_ton" in set(tor["input"])
    assert (tor["swing"] >= 0).all()
    inf = input_influence(x, t, keys=["d_bio_m", "slope_deg"])
    assert len(inf) == 2
