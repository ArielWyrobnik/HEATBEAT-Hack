"""Sanity checks on the built database. Run after `python -m data_pipeline.build_db [--offline]`."""
import pytest

import heatbeat_data as hd


@pytest.fixture(scope="module")
def sites():
    return hd.list_sites()


def test_sites_complete(sites):
    assert len(sites) >= 30
    assert sites["site_id"].is_unique
    assert sites["lat"].between(-90, 90).all() and sites["lon"].between(-180, 180).all()
    assert sites["retail_industrial_usd_mwh"].notna().all()
    assert sites["co2_kg_mwh"].notna().all()


def test_every_site_has_full_year(sites):
    hours = int(hd.meta()["reference_year"]) % 4 == 0 and 8784 or 8760
    for sid in sites["site_id"]:
        s = hd.get_site(sid)
        assert len(s.weather) == hours, sid
        assert len(s.prices) == hours, sid
        assert s.weather[["t_db_c", "rh_pct", "t_wb_c"]].notna().all().all(), sid
        assert (s.weather["t_wb_c"] <= s.weather["t_db_c"] + 0.5).mean() > 0.99, sid
        assert s.prices["price_usd_mwh"].notna().all(), sid


def test_summary_is_plain_python():
    s = hd.get_site(hd.list_sites()["site_id"].iloc[0]).summary()
    assert all(isinstance(v, (int, float, str, type(None))) for v in s.values())


def test_synthetic_flags_consistent():
    src = hd.sources().set_index("source_id")
    regions = hd.list_grid_regions()
    for r in regions.itertuples():
        if r.retail_price_source:
            assert r.retail_price_source in src.index
        assert r.co2_source in src.index
