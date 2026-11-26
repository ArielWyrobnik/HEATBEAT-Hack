"""Checks on the per-site heat source data. Needs no database build."""
import pandas as pd

from heatbeat_data import heat_profiles as hp

DP = hp._DIR


def test_every_site_has_one_profile():
    sites = pd.read_csv(DP / "sites.csv")
    prof = hp.site_heat_profiles()
    assert prof["site_id"].is_unique
    assert set(prof["site_id"]) == set(sites["site_id"])


def test_values_valid():
    prof = hp.site_heat_profiles()
    assert prof["cooling_type"].isin(hp.COOLING_TYPES).all()
    assert prof["chip_family"].isin(hp.CHIP_FAMILIES).all()
    assert prof["confidence"].isin(hp.CONFIDENCE).all()
    assert (prof["it_load_mw_low"] <= prof["it_load_mw"]).all()
    assert (prof["it_load_mw"] <= prof["it_load_mw_high"]).all()
    assert prof["liquid_heat_share"].between(0, 1).all()
    assert (prof["facility_power_mw"] >= prof["it_load_mw"]).all()


def test_temperatures_ordered():
    c = hp.cooling_profiles()
    w = c.dropna(subset=["facility_supply_temp_c"])
    for side in ("facility_supply", "facility_return"):
        assert (w[f"{side}_temp_c_min"] <= w[f"{side}_temp_c"]).all()
        assert (w[f"{side}_temp_c"] <= w[f"{side}_temp_c_max"]).all()
    assert (w["facility_return_temp_c"] > w["facility_supply_temp_c"]).all()


def test_generations_get_warmer():
    c = hp.cooling_profiles().set_index("cooling_profile_id")["facility_return_temp_c"]
    assert c["air_chilled_legacy"] < c["dlc_cold"] < c["dlc_warm"] < c["dlc_hot"]


def test_sources_resolve():
    ids = set(hp.heat_sources()["source_id"])
    used = pd.concat([hp._site_profiles_raw()["source_ids"], hp.cooling_profiles()["source_ids"]])
    assert {x for v in used for x in v.split(";")} <= ids


def test_heat_profile_dict_plain():
    d = hp.heat_profile("us-tn-memphis-xai")
    assert d["chip_family"] == "nvidia_hopper"
    assert all(isinstance(v, (int, float, str, bool, type(None))) for v in d.values())
