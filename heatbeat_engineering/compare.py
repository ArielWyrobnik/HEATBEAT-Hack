"""Side by side: the team Excel ranking (heatbeat_ranking) and the engineering heat chain model."""
from __future__ import annotations

import pandas as pd

from .chains import best_per_use, evaluate_site
from .site import load_site

# Excel option -> engineering heat use family (None: dropped from the engineering scope)
EXCEL_TO_ENG = {
    "district_heating": "dh", "biogas": "biogas", "absorption_cooling": "adsorption", "orc": "orc",
    "btes_ates": "dh (storage)", "boiler_feedwater": "feedwater", "desalination": "desal",
    "fish_farm": None, "greenhouse": None, "biomass": None, "drying": None, "snow_melt": None, "dac": None,
}


def compare(site_id: str, live: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(Excel ranking in corrected and excel mode, engineering best chain per heat use)."""
    from heatbeat_ranking import rank_site
    xl, _, _ = rank_site(site_id, mode="corrected", live=live)
    xe, _, _ = rank_site(site_id, mode="excel", live=live)
    df, _, _ = evaluate_site(load_site(site_id, live=live))
    return pd.concat([xl.assign(mode="corrected"), xe.assign(mode="excel")]), best_per_use(df)
