"""Checks on site_ecology.csv and the scoring rules. Needs no network and no database build."""
import pandas as pd

from data_pipeline.ecology import score
from heatbeat_data import site_ecology_data as eco

DP = eco._CSV.parent


def test_every_site_scored_once():
    sites = pd.read_csv(DP / "sites.csv")
    df = eco.site_ecology()
    assert df["site_id"].is_unique
    assert set(df["site_id"]) == set(sites["site_id"])


def test_value_ranges():
    df = eco.site_ecology()
    assert df["eco_sens_index"].between(1, 5).all()
    assert df["geo_storage_score"].between(1, 5).all()
    assert df["mit_tier"].isin(eco.MIT_TIERS).all()
    assert df["eco_confidence"].isin(eco.CONFIDENCE).all()
    assert df["geo_confidence"].isin(eco.CONFIDENCE).all()
    assert df["eco_source_ids"].notna().all() and df["geo_source_ids"].notna().all()


def test_excel_inputs_types():
    sid = eco.site_ecology()["site_id"].iloc[0]
    x = eco.excel_ecology_inputs(sid)
    assert set(x) == {"eco_sens_index", "geo_storage_score", "mit_tier"}
    assert isinstance(x["eco_sens_index"], int) and isinstance(x["geo_storage_score"], int)


def test_eco_rule():
    quiet = pd.Series({"prot_n_1km": 0, "prot_n_5km": 0, "crithab_n_1km": 0, "crithab_n_5km": 0,
                       "wetland_ha_1km": 0, "estuarine_n_5km": 0, "coast_km": 300})
    assert score.eco_points(quiet)[0] == 0
    loud = quiet.copy()
    loud.update({"prot_n_1km": 1, "crithab_n_1km": 1, "wetland_ha_1km": 20, "coast_km": 1})
    assert score.eco_points(loud)[0] == 4  # capped, index 5


def test_geo_rule():
    base = {"coast_km": 100, "aquifer_rock_type": None, "macro_name": ""}
    assert score.geo_score(pd.Series({**base, "macro_lith": "granite"}))[0] == 5
    assert score.geo_score(pd.Series({**base, "macro_lith": "limestone"}))[0] == 2
    assert score.geo_score(pd.Series({**base, "macro_lith": "siltstone"}))[0] == 4
    assert score.geo_score(pd.Series({**base, "macro_lith": "sandstone", "aquifer_rock_type": 500}))[0] == 2
    assert score.geo_score(pd.Series({**base, "macro_lith": "alluvium", "aquifer_rock_type": 100}))[0] == 2
    assert score.mit_tier(4)[0] == "high" and score.mit_tier(2)[0] == "med"
