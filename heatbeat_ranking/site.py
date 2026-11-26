"""Rank the options for one data center of the HEATBEAT database."""
from __future__ import annotations

import pandas as pd

from .climate import diurnal_from_daily, daily_min_max, hourly_from_site
from .engine import evaluate
from .inputs import site_inputs


def rank_site(site_id: str, mode: str = "corrected", weather: str = "hourly",
              is_greenfield: int | None = None, overrides: dict | None = None,
              live: bool = True) -> tuple[pd.DataFrame, dict, dict]:
    """Returns (ranking table, inputs used, provenance per input).

    weather="hourly" uses the real 2024 hourly temperature; "daily_cosine" rebuilds it from the
    daily min/max with the Excel cosine (to show the difference between both methods).
    """
    import heatbeat_data as hd

    x, prov = site_inputs(site_id, is_greenfield=is_greenfield)
    for k, v in (overrides or {}).items():
        x[k] = v
        prov[k] = {"status": "user", "source": "override argument"}
    t = hourly_from_site(hd.get_site(site_id, live=live))
    if weather == "daily_cosine":
        d = daily_min_max(t)
        t = diurnal_from_daily(d["t_min_c"].to_numpy(), d["t_max_c"].to_numpy())
    elif weather != "hourly":
        raise ValueError("weather must be 'hourly' or 'daily_cosine'")
    df = evaluate(x, t, mode)
    df.attrs.update(site_id=site_id, weather=weather)
    return df, x, prov
