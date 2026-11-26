"""Documented current setup per site (heatbeat_data.current_setup) and its use in the engineering baseline."""
import pandas as pd
import pytest

import heatbeat_data as hd
import importlib

cs = importlib.import_module("heatbeat_data.current_setup")

VALID_REJ = {"dry", "adiabatic", "tower"}


def test_rows_well_formed():
    t = hd.current_setup_table()
    assert len(t) > 50
    assert set(t["confidence"]) <= {"high", "medium", "low"}
    assert set(t["evidence"]) <= {"operator", "press", "permit", "third_party", "inferred"}
    assert set(t["scope"]) <= set(cs.SITE_SCOPES) | {"area", "operator_fleet"}
    assert (t["source_url"].str.startswith("https://")).all(), "every row needs a source with a URL"
    # sites.csv also lists reference sites that the stored database may not have yet
    sites = set(hd.list_sites()["site_id"]) | set(pd.read_csv(cs._DIR / "sites.csv")["site_id"])
    assert set(t["site_id"]) <= sites


def test_verified_sites():
    v = hd.verification_status().set_index("site_id")
    assert (v["status"] == "verified").sum() >= 12
    assert v.loc["us-tx-abilene-stargate", "status"] == "verified"
    assert hd.verified_rejection("us-tx-abilene-stargate")["value"] == "dry"
    # area level facts never count as verified
    assert hd.verified_rejection("us-va-ashburn-equinix") is None
    for sid in v.index:
        r = hd.verified_rejection(sid)
        assert r is None or r["value"] in VALID_REJ


def test_already_implemented():
    assert "dry" in hd.already_implemented("us-wi-mount-pleasant-microsoft")
    assert hd.already_implemented("us-il-chicago-cermak") == []


@pytest.fixture(scope="module")
def model():
    pytest.importorskip("pyarrow")
    from heatbeat_engineering.api_model import MODEL
    return MODEL


def test_baseline_uses_verified_rejection(model):
    from heatbeat_engineering.site import load_site
    s = load_site("us-tx-abilene-stargate", live=False)
    assert s.baseline_rejection == "dry"
    assert s.prov["baseline_rejection"]["status"] == "data"
    s = load_site("us-il-chicago-cermak", live=False)
    assert s.prov["baseline_rejection"]["status"] == "assumption"


def test_overrides_cooling_and_rejection(model):
    from heatbeat_engineering.site import load_site
    s = load_site("us-tx-abilene-stargate", live=False, overrides={"cooling_profile": "dlc_hot", "baseline_rejection": "tower"})
    assert s.cooling_profile == "dlc_hot" and s.baseline_rejection == "tower"
    assert s.prov["baseline_rejection"]["status"] == "user"
    with pytest.raises(ValueError):
        load_site("us-tx-abilene-stargate", live=False, overrides={"baseline_rejection": "lake"})


def test_api_result_flags_already_in_place(model):
    r = model.run("us-tx-abilene-stargate", tornado=False)
    b = r.baseline
    assert b.heat_rejection == "dry" and b.heat_rejection_flag == "real" and b.setup_status == "verified"
    assert any(f.field == "heat_rejection" and f.source_url for f in b.current_setup)
    dry = [o for o in r.options if o.option_id == "dry"]
    assert dry and dry[0].already_in_place and "today's setup" in dry[0].name
    assert all(o.already_in_place for o in r.options if o.feasible and o.option_id.startswith("dry"))


def test_unverified_site_warns(model):
    r = model.run("us-il-chicago-cermak", tornado=False)
    assert r.baseline.setup_status is None
    assert any("not documented publicly" in w for w in r.warnings)


def test_validation_table(model):
    from heatbeat_engineering.validate_setup import compare_with_reported
    df = compare_with_reported()
    sa = df.set_index("site_id").loc["us-tx-san-antonio-microsoft"]
    assert sa["reported_wue_l_kwh"] == pytest.approx(1.82)
    assert abs(sa["model_wue_l_kwh"] - 1.82) < 0.5  # tower baseline close to the measured WUE


def test_verdict_says_no_gain_where_site_already_runs_dry_cooling():
    """Abilene runs closed-loop liquid cooling with air-cooled chillers (Crusoe): nothing should beat it."""
    from heatbeat_engineering import evaluate
    from heatbeat_engineering.verdict import verdict
    df, base, _, s = evaluate(site_id="us-tx-abilene-stargate", live=False, greenfield=None)
    v = verdict(df, base, s)
    assert s.baseline_rejection == "dry" and v["level"] == "no_gain"
    assert v["alternative_npv_usd"] < 0 and "public source" in v["text"]


def test_verdict_levels_and_assumed_baseline_note():
    from heatbeat_engineering import evaluate
    from heatbeat_engineering.verdict import verdict
    df, base, _, s = evaluate(site_id="us-ga-atlanta-qts", live=False, greenfield=None)
    assert verdict(df, base, s)["level"] == "gain"
    df, base, _, s = evaluate(site_id="us-il-chicago-cermak", live=False, greenfield=None)
    v = verdict(df, base, s)
    assert s.prov["baseline_rejection"]["status"] == "assumption" and "not documented" in v["text"]


def test_api_result_carries_verdict():
    pytest.importorskip("fastapi")
    from heatbeat_engineering.api_model import MODEL
    r = MODEL.run("us-wi-mount-pleasant-microsoft", tornado=False)
    assert r.verdict_level == "no_gain" and r.verdict
