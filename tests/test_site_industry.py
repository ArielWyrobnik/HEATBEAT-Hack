"""Checks for data_pipeline/site_industry.csv and its accessor (no network)."""
import pandas as pd

import heatbeat_data as hd
from data_pipeline.common import load_sites

KEYS = ["d_pp_m", "q_fw_mw", "d_co2_m", "d_bio_m", "d_market_m"]


def test_one_row_per_us_site():
    t = hd.site_industry()
    us = load_sites().query("country_iso2 == 'US'")
    assert sorted(t["site_id"]) == sorted(us["site_id"])
    assert t["site_id"].is_unique


def test_excel_keys_present_and_sane():
    t = hd.site_industry()
    assert list(t.columns[1:6]) == KEYS
    for k in ["d_pp_m", "q_fw_mw", "d_bio_m", "d_co2_m", "d_market_m"]:
        assert t[k].notna().all(), k
    for k in KEYS:
        v = t[k].dropna()
        assert (v >= 0).all(), k
    assert (t["d_pp_m"] < 500_000).all()
    assert (t["q_fw_mw"] >= 2.0).all()  # chosen plant passes the Excel 2 MW gate by construction


def test_confidence_and_source_columns():
    t = hd.site_industry()
    for block in ["pp", "co2", "bio", "market"]:
        assert t[f"{block}_confidence"].isin(["high", "medium", "low"]).all(), block
        assert t[f"{block}_source"].notna().all(), block


def test_accessor():
    d = hd.excel_industry_inputs("us-ia-council-bluffs-google")
    assert set(d) == set(KEYS)
    assert d["d_pp_m"] < 10_000  # Google Council Bluffs sits next to Walter Scott Jr Energy Center
    try:
        hd.site_industry("il-haifa")
    except KeyError:
        pass
    else:
        raise AssertionError("non-US site should raise KeyError")
