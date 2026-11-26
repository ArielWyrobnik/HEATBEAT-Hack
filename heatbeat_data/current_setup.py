"""What each data center already does today, from public evidence, with a source per field.

Why: the engineering model compares every heat chain with the site's existing cooling. If the
baseline is a guess, an "improvement" may be something the site already does (or does better).
This module holds what we could verify from operator reports, permits, utility records and press.

Files (long format, one row per site and field):

    data_pipeline/site_current_setup.csv            rows
    data_pipeline/site_current_setup_sources.csv    source_id -> title, url, published
    data_pipeline/site_current_setup_<x>.csv         more rows from other threads (same columns),
    data_pipeline/site_current_setup_<x>_sources.csv with their own sources

Columns: site_id, field, value, unit, scope, confidence, evidence, source_id, note.

    scope       site, campus, campus_legacy, cluster, area, operator_region, operator_fleet
                (fleet and area values are context, not a statement about this building)
    confidence  high (operator states it for this site), medium (press, or inferred from strong
                evidence such as water volume), low (operator typical design, area level, inference)
    evidence    operator, press, permit, third_party, inferred

Fields the engineering model reads: heat_rejection (dry / adiabatic / tower / mixed),
cooling_profile_id, pue, wue_l_kwh, already_implemented (semicolon list). The rest are shown in the UI.

    import heatbeat_data as hd
    hd.current_setup("us-tx-abilene-stargate")   # {field: {value, unit, confidence, source_url, ...}}
    hd.verification_status()                      # one row per site: verified / partial / unverified
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

_DIR = Path(__file__).resolve().parents[1] / "data_pipeline"
COLUMNS = ["site_id", "field", "value", "unit", "scope", "confidence", "evidence", "source_id", "note"]
REJECTION_TECHS = ("dry", "adiabatic", "tower")
SITE_SCOPES = ("site", "campus", "campus_legacy", "cluster", "operator_region")  # scopes that describe this site
FIELD_LABELS = {
    "status": "Status", "cooling_profile_id": "Cooling at the rack", "heat_rejection": "Heat rejection",
    "water_source": "Water source", "water_use_m3_yr": "Water use", "water_use_m3_yr_2025": "Water use 2025",
    "water_use_m3_yr_partial": "Water use (part year)", "water_use_peak_m3_day": "Peak water use",
    "water_withdrawal_m3_yr": "Water withdrawal", "wue_l_kwh": "WUE (reported)", "pue": "PUE (reported)",
    "chip_family": "Chips", "onsite_generation": "On-site generation", "heat_reuse": "Heat reuse",
    "already_implemented": "Already in place",
}
ALREADY_LABELS = {
    "dry": "zero-water heat rejection (dry coolers / air-cooled chillers)",
    "reclaimed_water": "cooling on reclaimed or recycled water",
    "free_cooling": "outside air or water-side free cooling most of the year",
    "heat_reuse_office": "server heat used for its own offices",
    "dh": "district heating", "biogas": "digester heating", "desal": "thermal desalination",
}


@lru_cache(maxsize=1)
def setup_sources() -> pd.DataFrame:
    files = sorted(_DIR.glob("site_current_setup*_sources.csv"))
    if not files:
        return pd.DataFrame(columns=["source_id", "title", "url", "published"])
    return pd.concat([pd.read_csv(p, dtype=str) for p in files]).drop_duplicates("source_id", keep="last")


@lru_cache(maxsize=1)
def current_setup_table() -> pd.DataFrame:
    """All rows of all site_current_setup*.csv files, joined with their source (url, title, date)."""
    files = [p for p in sorted(_DIR.glob("site_current_setup*.csv"))
             if not p.name.endswith("_sources.csv") and "site_id" in p.read_text().split("\n", 1)[0]]
    if not files:
        return pd.DataFrame(columns=COLUMNS + ["source_url", "source_title", "source_date"])
    df = pd.concat([pd.read_csv(p, dtype=str).assign(file=p.name) for p in files], ignore_index=True)
    for c in COLUMNS:
        if c not in df:
            df[c] = None
    src = setup_sources().rename(columns={"url": "source_url_ref", "title": "source_title", "published": "source_date"})
    df = df.merge(src, on="source_id", how="left")
    if "source_url" in df:  # rows may carry their own URL
        df["source_url"] = df["source_url"].fillna(df["source_url_ref"])
    else:
        df["source_url"] = df["source_url_ref"]
    return df.drop(columns=["source_url_ref"]).fillna("")


def _clean(v):
    return None if v == "" else v


def current_setup(site_id: str) -> dict[str, dict]:
    """Verified facts for one site: {field: {value, unit, scope, confidence, evidence, source_url, ...}}.
    Empty dict when nothing is known. If a field appears twice, the higher confidence row wins."""
    t = current_setup_table()
    t = t[t["site_id"] == site_id]
    rank = {"high": 0, "medium": 1, "low": 2}
    out: dict[str, dict] = {}
    for r in sorted(t.to_dict("records"), key=lambda r: rank.get(r["confidence"], 3), reverse=True):
        out[r["field"]] = {k: _clean(r[k]) for k in ("value", "unit", "scope", "confidence", "evidence", "note",
                                                     "source_id", "source_url", "source_title", "source_date")}
        out[r["field"]]["label"] = FIELD_LABELS.get(r["field"], r["field"])
    return out


def verified_rejection(site_id: str) -> dict | None:
    """The heat rejection the site uses today if a source states or strongly implies it for this site
    (scope site/campus/cluster/operator_region, confidence high or medium, value a model technology)."""
    r = current_setup(site_id).get("heat_rejection")
    if r and r["value"] in REJECTION_TECHS and r["confidence"] in ("high", "medium") and r["scope"] in SITE_SCOPES:
        return r
    return None


def already_implemented(site_id: str) -> list[str]:
    r = current_setup(site_id).get("already_implemented")
    return [x.strip() for x in (r["value"] or "").split(";") if x.strip()] if r else []


def verification_status() -> pd.DataFrame:
    """One row per site in the setup files: how much of today's setup is backed by a source.

    verified    heat rejection known for this site (high or medium confidence)
    partial     some site specific facts (water, PUE, cooling) but heat rejection not confirmed
    context     only operator fleet or area level facts
    """
    t = current_setup_table()
    rows = []
    for sid, g in t.groupby("site_id"):
        site_rows = g[g["scope"].isin(SITE_SCOPES) & g["confidence"].isin(["high", "medium"])]
        status = ("verified" if verified_rejection(sid) else "partial" if len(site_rows) else "context")
        rows.append({"site_id": sid, "status": status, "n_facts": len(g), "n_site_facts": len(site_rows),
                     "heat_rejection": (current_setup(sid).get("heat_rejection") or {}).get("value"),
                     "already_implemented": ";".join(already_implemented(sid)),
                     "sources": len(set(g["source_id"]))})
    return pd.DataFrame(rows)
