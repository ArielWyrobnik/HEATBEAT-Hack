"""Checks on the market price table. Needs no database build or network."""
import pandas as pd

import heatbeat_data as hd
from data_pipeline import build_market_prices as bmp


def test_csv_is_up_to_date():
    built = bmp.main(write=False)
    on_disk = hd.market_prices()
    assert len(built) == len(on_disk)
    assert list(built["item"]) == list(on_disk["item"])
    pd.testing.assert_series_equal(built["value"].astype(float), on_disk["value"].astype(float), check_names=False)


def test_unique_and_sourced():
    df = hd.market_prices()
    assert not df.duplicated(["country_iso2", "region", "item"]).any()
    assert df["source_id"].isin(bmp.SOURCES).all()
    assert df["is_estimate"].isin([0, 1]).all()
    rng = df.dropna(subset=["low", "high"])
    assert (rng["low"] <= rng["value"] + 1e-9).all() and (rng["value"] <= rng["high"] + 1e-9).all()


def test_every_us_site_has_excel_keys():
    sites = pd.read_csv(bmp.OUT.parent / "sites.csv")
    for sid in sites.loc[sites["country_iso2"] == "US", "site_id"]:
        x = hd.excel_inputs(sid)
        assert all(v is not None and v >= 0 for v in x.values()), (sid, x)
        assert 0.01 < x["p_fuel_usd_kwh"] < 0.2


def test_state_overrides_national():
    tx = hd.market_for("US", "TX")
    us = hd.market_for("US")
    assert tx["ng_industrial_usd_mcf"] == 2.52 and us["ng_industrial_usd_mcf"] == 4.07
    assert tx["tilapia_import_usd_lb"] == us["tilapia_import_usd_lb"]  # national fallback
    assert hd.market_for("US", "CA")["co2_compliance_usd_t"] > 0 and tx["co2_compliance_usd_t"] == 0


def test_mix_ci_with_grid():
    m = hd.site_market(pd.read_csv(bmp.OUT.parent / "sites.csv").query("region == 'MA'").site_id.iloc[0],
                       grid_co2_g_kwh=300)
    assert 150 < m["ci_heat_mix_g_kwh_th"] < 300
