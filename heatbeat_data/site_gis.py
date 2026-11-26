"""Per-site GIS inputs: distances to water, coast and district heating, terrain and land.

Reads data_pipeline/site_gis.csv (built by `python -m data_pipeline.fetch_gis`, no network needed here).
Column names follow the JSON keys of the team Excel model (sheet 1_Site_Inputs_Schema):

    d_coast_m        routed distance to sea water (straight line x 1.2); brackish aquifers not included
    d_water_m        routed distance to the nearest river, lake >= 5 ha, reservoir or sea
    dz_m             site elevation above sea level (pumping head from a seawater intake)
    slope_deg        mean terrain slope within 1 km
    flat_land_m2     largest contiguous open, flat (<= 5 deg) patch within 2 km
    agri_land_m2     largest contiguous flat cropland patch within 2 km
    campus_area_m2   SYNTHETIC: IT MW x 2,500 m2/MW
    d_dh_m           routed distance to a known DH network or a dense heat demand area
    has_existing_dh  1 if a known DH network or mapped heat pipe is within 3 km
    rho_heat_mwh_m   modelled linear heat density at the d_dh_m target (Persson & Werner 2011)
    ind_zoning       1 if OSM industrial land use is within 1 km (proxy, not legal zoning)

Each field has <field>_source and <field>_confidence (high / medium / low / synthetic) columns.
Method and caveats: docs/GIS.md.

    import heatbeat_data as hd
    hd.site_gis()                                   # DataFrame, one row per site_id
    hd.gis_inputs("us-va-ashburn-equinix")          # dict of the 11 Excel keys only
    hd.get_site("us-va-ashburn-equinix").gis()      # full row as a dict
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

_CSV = Path(__file__).resolve().parents[1] / "data_pipeline" / "site_gis.csv"

GIS_KEYS = ("d_coast_m", "d_water_m", "dz_m", "slope_deg", "flat_land_m2", "agri_land_m2", "campus_area_m2",
            "d_dh_m", "has_existing_dh", "rho_heat_mwh_m", "ind_zoning")
_INT_KEYS = ("has_existing_dh", "ind_zoning")


def _clean(v):
    if isinstance(v, float) and pd.isna(v):
        return None
    return v.item() if hasattr(v, "item") else v


@lru_cache(maxsize=1)
def site_gis() -> pd.DataFrame:
    """All GIS columns, one row per site_id (copy it before editing)."""
    df = pd.read_csv(_CSV)
    for k in _INT_KEYS:
        df[k] = df[k].astype("Int64")
    return df


def site_gis_row(site_id: str) -> dict:
    df = site_gis()
    row = df[df["site_id"] == site_id]
    if row.empty:
        raise KeyError(f"no GIS data for {site_id!r}; run python -m data_pipeline.fetch_gis --sites {site_id}")
    return {k: _clean(v) for k, v in row.iloc[0].to_dict().items()}


def gis_inputs(site_id: str) -> dict:
    """Only the Excel model keys, ready to merge into the model input JSON."""
    row = site_gis_row(site_id)
    return {k: row.get(k) for k in GIS_KEYS}
