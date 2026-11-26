"""Companies per solution: data file contract, pick rules and API wiring."""
import os

os.environ.setdefault("HEATBEAT_LIVE", "0")

import pytest  # noqa: E402

import heatbeat_data as hd  # noqa: E402
from heatbeat_data.vendors import COVERAGE_RANK, NVIDIA_TIER, ROLE, ROLE_LABEL  # noqa: E402


def test_every_row_is_sourced_and_flagged():
    df = hd.vendors()
    assert df["vendor_id"].is_unique
    assert set(df["verified"]) <= {"verified", "partly", "unverified"}
    assert set(df["nvidia_link"]) <= set(NVIDIA_TIER)
    assert set(df["coverage"]) <= set(COVERAGE_RANK)
    for r in df.itertuples():
        assert r.url.startswith("https://"), r.vendor_id
        assert r.role_set and r.role_set <= set(ROLE_LABEL), r.vendor_id
        if r.nvidia_link != "none":  # every NVIDIA claim needs a source
            assert r.nvidia_source.startswith("https://"), r.vendor_id
        if r.verified == "verified":
            assert (r.evidence_url or r.nvidia_source).startswith("https://"), r.vendor_id
        assert "—" not in r.one_line + r.evidence_note  # no em-dashes
        assert -90 <= r.hq_lat <= 90 and -180 <= r.hq_lon <= 180


def test_every_heat_chain_part_has_a_company():
    for comp in ROLE:
        assert hd.vendors_for([comp], 40.0, -95.0), comp
    for prof in ("dlc_warm", "dlc_hot", "immersion_1p", "rear_door"):
        assert hd.vendors_for_cooling(prof, 40.0, -95.0), prof
    assert hd.vendors_for_cooling("air_chilled_legacy", 40.0, -95.0) == []


def test_pick_rules():
    v = hd.vendors_for(["dry_cooler", "heat_pump", "district_heating"], 44.9, -93.2)
    assert len(v) == 3 and len({x["vendor_id"] for x in v}) == 3
    assert v[0]["role"] == "district_heating"          # heat use first
    assert v[0]["name"] == "Ever-Green Energy"         # core business beats a side business
    assert "km away" in v[0]["where"]                  # nearby base is shown with distance
    # NVIDIA backed first among equals: liquid cooling goes to a DSX partner
    c = hd.vendors_for_cooling("dlc_warm", 39.0, -77.5)
    assert c[0]["nvidia"] and c[-1]["role"] == "controls"
    # a company without a US office only appears when nobody else covers the part, and says so
    a = hd.vendors_for(["adsorption"], 39.0, -77.5)
    assert a[0]["where"].endswith("no US office found")
    assert all("no US office" not in x["where"] for x in hd.vendors_for(["dry_cooler"], 39.0, -77.5))


def test_api_attaches_vendors():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from heatbeat_api.app import app
    c = TestClient(app)
    r = c.get("/api/sites/us-va-ashburn-equinix/ranking").json()
    feas = [o for o in r["options"] if o["feasible"]]
    assert feas and all(1 <= len(o["vendors"]) <= 3 for o in feas)
    p = c.post("/api/plan", json={"lat": 33.4, "lon": -112.0, "it_mw": 100, "cooling_profile": "dlc_warm",
                                  "tornado": False}).json()
    assert p["cooling_vendors"] and any(o["vendors"] for o in p["options"] if o["feasible"])


def test_references_have_sources_and_reach_cascade_stages():
    import heatbeat_data as hd
    df = hd.references()
    assert (df.url.str.startswith("http")).all() and df.status.isin(["operating", "pilot", "prototype", "announced"]).all()
    refs = hd.references_for(["fish"])
    assert refs and refs[0]["project"].startswith("Green Mountain")
    assert hd.references_for(["ambient"])[0]["status"] == "operating"
    assert hd.vendors_for(["greenhouse"], 40.0, -100.0, n=1)
