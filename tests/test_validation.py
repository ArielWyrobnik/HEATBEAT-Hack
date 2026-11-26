"""Checks on the reference validation cases. Needs no network and no weather."""
import pandas as pd

from data_pipeline.reference_sites import REFS, SETUP, SOURCES
from heatbeat_validation.cases import CASES
from heatbeat_validation.run import _verdict

SITES = set(pd.read_csv("data_pipeline/sites.csv")["site_id"])
SRC = {s[0] for s in SOURCES}


def test_reference_sites_are_in_the_site_list_once():
    ids = [r["site_id"] for r in REFS]
    assert len(ids) == len(set(ids))
    assert set(ids) <= SITES
    assert pd.read_csv("data_pipeline/sites.csv")["site_id"].is_unique


def test_cases_point_to_known_sites_and_sources():
    for c in CASES:
        assert c["site_id"] in SITES, c["ref"]
        assert set(c["engines"]) <= {"engineering", "excel"}
        if "engineering" in c["engines"]:
            assert c["family"] in ("dh", "biogas", "desal", "feedwater", "orc", "adsorption", "ates")
        for _m, _v, _u, src, _n in c["reported"]:
            assert src in SRC, (c["ref"], src)


def test_current_setup_rows_cite_sources():
    for row in SETUP:
        assert row[0] in SITES
        assert row[7] in SRC, row


def test_verdict_bands():
    assert _verdict(1.2, 1.0)[1] == "match"
    assert _verdict(2.5, 1.0)[1] == "same order"
    assert _verdict(10, 1.0)[1] == "miss"
    assert _verdict(-1, 1.0)[1] == "miss (opposite sign)"
    assert _verdict(None, 1.0)[1] == "no model value"
