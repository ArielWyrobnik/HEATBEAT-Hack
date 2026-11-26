"""Per-site ecology and geology scores for the team Excel model.

Reads data_pipeline/site_ecology.csv directly (no build step, no network). The CSV is produced by
data_pipeline/ecology/fetch_features.py (GitHub Actions) and data_pipeline/ecology/score.py.
Scoring rules: docs/ECOLOGY.md.

    import heatbeat_data as hd
    hd.site_ecology()                       # DataFrame, one row per site_id
    hd.ecology("us-va-ashburn-equinix")     # one row as a dict
    hd.excel_ecology_inputs("us-va-ashburn-equinix")
    # -> {"eco_sens_index": 2, "geo_storage_score": 4, "mit_tier": "med"}

Columns that map to the Excel sheet 1_Site_Inputs_Schema:
    eco_sens_index     Input 30, int 1..5
    geo_storage_score  Input 21, int 1..5 (BTES/ATES KO gate needs >= 3)
    mit_tier           Input 31, low / med / high. A default only: a solution's design (closed RAS,
                       dry coolers, ZLD) should override it.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

_CSV = Path(__file__).resolve().parents[1] / "data_pipeline" / "site_ecology.csv"

MIT_TIERS = ("low", "med", "high")
CONFIDENCE = ("high", "medium", "low")


@lru_cache(maxsize=1)
def site_ecology() -> pd.DataFrame:
    return pd.read_csv(_CSV)


def ecology(site_id: str) -> dict:
    df = site_ecology()
    row = df[df["site_id"] == site_id]
    if row.empty:
        raise KeyError(f"unknown site_id {site_id!r} in site_ecology.csv")
    return row.iloc[0].to_dict()


def excel_ecology_inputs(site_id: str) -> dict:
    """Just the three values the Excel model takes, with Python types."""
    r = ecology(site_id)
    return {"eco_sens_index": int(r["eco_sens_index"]), "geo_storage_score": int(r["geo_storage_score"]),
            "mit_tier": str(r["mit_tier"])}
