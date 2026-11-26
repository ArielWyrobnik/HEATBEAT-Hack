import math

import pandas as pd

import heatbeat_data as hd
from data_pipeline.fetch_gis import persson_werner_lin_density

SITES = pd.read_csv("data_pipeline/sites.csv")


def test_every_site_has_gis_row():
    gis = hd.site_gis()
    assert set(SITES.site_id) == set(gis.site_id)


def test_keys_present_with_source_and_confidence():
    gis = hd.site_gis()
    for k in hd.GIS_KEYS:
        assert k in gis.columns
        assert f"{k}_source" in gis.columns and f"{k}_confidence" in gis.columns
        assert gis[f"{k}_confidence"].dropna().isin(["high", "medium", "low", "synthetic"]).all()


def test_value_ranges():
    gis = hd.site_gis()
    assert (gis.slope_deg.between(0, 45)).all()
    for k in ("d_coast_m", "d_water_m", "dz_m", "flat_land_m2", "agri_land_m2", "d_dh_m", "rho_heat_mwh_m"):
        assert (gis[k].dropna() >= 0).all(), k
    assert gis.has_existing_dh.isin([0, 1]).all() and gis.ind_zoning.isin([0, 1]).all()
    assert (gis.agri_land_m2 <= math.pi * 2000 ** 2).all()


def test_known_geography():
    g = hd.site_gis().set_index("site_id")
    assert g.loc["us-ny-nyc-60-hudson", "d_coast_m"] < 3000          # Manhattan waterfront
    assert g.loc["us-ny-nyc-60-hudson", "has_existing_dh"] == 1       # Con Edison steam
    assert g.loc["us-az-mesa", "d_coast_m"] > 100_000                 # desert inland
    assert g.loc["il-haifa", "d_coast_m"] < 10_000


def test_gis_inputs_dict():
    d = hd.gis_inputs("us-va-ashburn-equinix")
    assert list(d) == list(hd.GIS_KEYS)
    assert hd.get_site.__module__  # accessor is importable without network


def test_persson_werner():
    # e = 1 -> w = 61.8 m, Q/L = q * 61.8
    assert abs(persson_werner_lin_density([1.0], 0.1)[0] - 6.18) < 1e-9
    assert persson_werner_lin_density([0.0], 0.1)[0] == 0


def test_ranking_export_long_format():
    df = pd.read_csv("data_pipeline/site_ranking_inputs_gis.csv")
    assert list(df.columns) == ["site_id", "key", "value", "status", "source", "note"]
    us = set(SITES.site_id[SITES.country_iso2 == "US"])
    assert set(df.site_id) == us
    assert df.status.isin(["data", "assumption"]).all()
