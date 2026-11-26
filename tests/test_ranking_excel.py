"""The Python port must reproduce the team Excel "Hack data.xlsx" for its example site."""
import json
import math

import numpy as np
import pytest

from heatbeat_ranking import evaluate, excel_example_inputs, excel_example_t_amb
from heatbeat_ranking.climate import DATA_DIR

EXP = json.loads((DATA_DIR / "excel_example_expected.json").read_text())
FLOAT_COLS = ["t_sink_c", "heat_rec_mwh", "hp_elec_mwh", "capacity_factor", "weighted_cop",
              "net_value_usd_mwh_dc", "viability_score"]
INT_COLS = ["ko_gate", "p1_thermo", "p2_climate_geo", "p3_economics", "p4_utilization",
            "eco_ghg"]


@pytest.fixture(scope="module")
def result():
    return evaluate(excel_example_inputs(), excel_example_t_amb(), mode="excel").set_index("option")


def test_climate_matches_excel():
    t = excel_example_t_amb()
    assert len(t) == 8760
    assert t.mean() == pytest.approx(EXP["t_amb_mean_c"], abs=1e-9)
    assert t[0] == pytest.approx(-4.25)


@pytest.mark.parametrize("row", EXP["results"], ids=lambda r: r["option"])
def test_option_matches_excel(result, row):
    got = result.loc[row["option"]]
    for c in FLOAT_COLS:
        assert got[c] == pytest.approx(row[c], rel=1e-9, abs=1e-6), c
    for c in INT_COLS:
        assert int(got[c]) == int(row[c]), c
    for c in ("eco_water", "eco_local"):
        assert got[c] == pytest.approx(row[c], abs=1e-9), c
    assert got["rank"] == row["rank"]
    assert got["eco_grade"] == row["eco_grade"]
    if row["eco_score"] is None:
        assert got["eco_score"] is None or (isinstance(got["eco_score"], float) and math.isnan(got["eco_score"]))
    else:
        assert got["eco_score"] == pytest.approx(row["eco_score"], abs=1e-9)


def test_top_three(result):
    top = result[result["rank"] != "KO"].sort_values("viability_score", ascending=False).index[:3]
    assert list(top) == ["Biomass Processing", "Industrial Drying", "Biogas Generator"]


def test_corrected_mode_runs_and_keeps_energy_balance():
    df = evaluate(excel_example_inputs(), excel_example_t_amb(), mode="corrected")
    assert len(df) == 13
    # delivered heat = source heat + heat pump electricity (first law), except ORC
    hp = df[df["key"] != "orc"]
    assert np.allclose(hp["heat_delivered_mwh"], hp["heat_rec_mwh"] + hp["hp_elec_mwh"])
    # no heat pump COP above the cap
    with_hp = df[df["hp_elec_mwh"] > 0]
    assert (with_hp["weighted_cop"] <= 8.0 + 1e-9).all()
