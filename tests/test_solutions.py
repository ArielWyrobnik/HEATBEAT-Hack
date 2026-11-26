import pytest

import heatbeat_solutions as hs

TEL_AVIV_SUMMARY = {  # synthetic, roughly Tel Aviv climate
    "t_db_mean_c": 21.0, "heating_degree_hours_18c": 8_000, "cooling_degree_hours_18c": 35_000,
    "price_mean_usd_mwh": 120, "price_p10_usd_mwh": 70, "price_p90_usd_mwh": 200,
}
STOCKHOLM_SUMMARY = {
    "t_db_mean_c": 7.5, "heating_degree_hours_18c": 95_000, "cooling_degree_hours_18c": 500,
    "price_mean_usd_mwh": 40, "price_p10_usd_mwh": 10, "price_p90_usd_mwh": 80,
}
RUBIN = {"cooling_type": "dlc_hot", "chip_family": "nvidia_vera_rubin", "it_load_mw": 50,
         "facility_supply_temp_c": 45, "facility_return_temp_c": 55, "liquid_heat_share": 1.0, "is_assumed": True}
AIR = {"cooling_type": "air_chilled", "chip_family": "cpu_legacy", "it_load_mw": 20,
       "facility_supply_temp_c": 10, "facility_return_temp_c": 16, "liquid_heat_share": 0.0, "is_assumed": True}


def test_catalogue_loads_and_is_consistent():
    cat = hs.load_catalogue()
    assert len(cat) >= 15
    for s in cat.values():
        assert s.source_ids
        if s.heat.needs_heat:
            assert s.heat.source_t_min_c[0] <= s.heat.source_t_ideal_c[1]


def test_no_em_dashes_in_catalogue():
    assert "—" not in hs.CATALOGUE_PATH.read_text(encoding="utf-8")


def test_heat_pump_cop():
    assert hs.heat_pump_cop(45, 80) == pytest.approx(0.5 * 353.15 / 35)
    assert hs.heat_pump_cop(60, 50) == float("inf")


def test_coastal_requirement_blocks_desalination_inland():
    rows = {r["solution_id"]: r for r in hs.screen(RUBIN, TEL_AVIV_SUMMARY, context={"country_iso2": "IL"})}
    assert rows["med_desalination"]["score"] == 0 and rows["med_desalination"]["blocked_by"] == ["coastal"]
    rows = {r["solution_id"]: r for r in hs.screen(RUBIN, TEL_AVIV_SUMMARY, context={"country_iso2": "IL", "coastal": True})}
    assert rows["med_desalination"]["score"] > 0.3


def test_israel_prefers_cooling_and_water_over_district_heating():
    rows = {r["solution_id"]: r for r in hs.screen(RUBIN, TEL_AVIV_SUMMARY, context={"country_iso2": "IL", "coastal": True})}
    assert rows["adsorption_chiller"]["score"] > rows["district_heating_4gdh"]["score"]
    assert rows["med_desalination"]["score"] > rows["district_heating_4gdh"]["score"]


def test_stockholm_prefers_district_heating():
    rows = {r["solution_id"]: r for r in hs.screen(RUBIN, STOCKHOLM_SUMMARY, context={"country_iso2": "SE"})}
    assert rows["district_heating_4gdh"]["score"] > rows["adsorption_chiller"]["score"]


def test_air_cooled_site_cannot_drive_chillers_directly():
    rows = {r["solution_id"]: r for r in hs.screen(AIR, TEL_AVIV_SUMMARY)}
    assert rows["adsorption_chiller"]["temperature"] == 0
    assert rows["aquaculture_ras"]["temperature"] > 0.5
