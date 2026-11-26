"""Neighbours of each US data center: power plants, CO2 sinks, biomass and cold chain hubs.

Reads data_pipeline/site_industry.csv (built by data_pipeline/fetch_industry.py, no network needed).
The first columns use the exact JSON keys of the team Excel model (sheet 1_Site_Inputs_Schema):

    d_pp_m      routing distance to the nearest steam cycle power / CHP plant whose estimated average
                low temperature feedwater sink is at least 2 MW_th (the Excel KO threshold)
    q_fw_mw     that plant's estimated feedwater heat sink (30 C -> 60 C), MW_th, capacity factor weighted
    d_co2_m     routing distance to CO2 geologic storage, CO2 injection (EOR) or a CO2 supplier hub
    d_bio_m     routing distance to biomass / organic waste supply (biomass plants, manure digesters,
                large food processors)
    d_market_m  routing distance to cold storage, seafood processing or a produce / wholesale food hub

All distances are in meters: great circle distance times CIRCUITY (1.2). Each block has *_source and
*_confidence columns. See docs/INDUSTRY.md for sources, method and caveats.

    import heatbeat_data as hd
    hd.site_industry()                          # DataFrame, one row per US site
    hd.site_industry("us-tn-memphis-xai")       # dict for one site
    hd.excel_inputs("us-tn-memphis-xai")        # only the five Excel keys
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

_PATH = Path(__file__).resolve().parents[1] / "data_pipeline" / "site_industry.csv"
EXCEL_KEYS = ("d_pp_m", "q_fw_mw", "d_co2_m", "d_bio_m", "d_market_m")


@lru_cache(maxsize=1)
def _table() -> pd.DataFrame:
    return pd.read_csv(_PATH)


def _clean(d: dict) -> dict:
    return {k: (None if (isinstance(v, float) and pd.isna(v)) else (v.item() if hasattr(v, "item") else v))
            for k, v in d.items()}


def site_industry(site_id: str | None = None):
    """All sites as a DataFrame, or one site as a dict (KeyError if the site is not covered)."""
    t = _table()
    if site_id is None:
        return t.copy()
    row = t[t["site_id"] == site_id]
    if row.empty:
        raise KeyError(f"no industry data for {site_id!r} (only US sites are covered)")
    return _clean(row.iloc[0].to_dict())


def excel_inputs(site_id: str) -> dict:
    """The five Excel model inputs for one site, keyed by their JSON keys."""
    d = site_industry(site_id)
    return {k: d.get(k) for k in EXCEL_KEYS}
