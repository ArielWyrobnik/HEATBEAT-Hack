"""Per-site heat source data: IT load, cooling type, chip generation and coolant temperatures.

Reads the curated CSVs in data_pipeline/ directly (no build step, no network):

    cooling_profiles.csv   lookup: cooling / chip generation -> facility water temps, liquid heat share
    site_profiles.csv      one row per site_id: IT load range, PUE, chip family, cooling profile
    heat_sources.csv       citations used by both files

Main entry point for solution models:

    import heatbeat_data as hd
    hp = hd.site_heat_profiles()          # DataFrame, one row per site_id
    hd.get_site("us-tn-memphis-xai").heat_profile()   # same row as a dict

Definitions:
    it_load_mw                 mid estimate of average IT power (low/high give the range)
    facility_power_mw          reported facility figure, else it_load_mw * pue_assumed
    facility_supply_temp_c     water entering the IT side (CDU or CRAH). For air-cooled rooms on
                               chillers this is the chilled water loop; empty for outside-air rooms.
    facility_return_temp_c     warm water leaving the IT side: the temperature reusable heat comes at.
    liquid_heat_share          share (0..1) of IT heat captured into liquid at rack level
                               (cold plate, rear door, immersion). 0 for air-cooled rooms.
    recoverable_heat_mw_liquid it_load_mw * liquid_heat_share (heat at facility_return_temp_c)
    recoverable_heat_mw_air    it_load_mw * (1 - liquid_heat_share) (heat at exhaust_air_temp_c)
    is_assumed                 True if any figure in the row is a team estimate
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

_DIR = Path(__file__).resolve().parents[1] / "data_pipeline"

COOLING_TYPES = ("air_chilled", "air_economizer", "rear_door", "dlc_cold", "dlc_warm", "dlc_hot", "immersion")
CHIP_FAMILIES = ("cpu_legacy", "nvidia_hopper", "nvidia_blackwell", "nvidia_blackwell_ultra",
                 "nvidia_vera_rubin", "google_tpu", "other_accelerator", "mixed")
CONFIDENCE = ("high", "medium", "low")

_TEMP_COLS = [f"{side}_temp_c{sfx}" for side in ("facility_supply", "facility_return")
              for sfx in ("_min", "", "_max")]


@lru_cache(maxsize=1)
def cooling_profiles() -> pd.DataFrame:
    return pd.read_csv(_DIR / "cooling_profiles.csv")


@lru_cache(maxsize=1)
def heat_sources() -> pd.DataFrame:
    return pd.read_csv(_DIR / "heat_sources.csv")


@lru_cache(maxsize=1)
def _site_profiles_raw() -> pd.DataFrame:
    return pd.read_csv(_DIR / "site_profiles.csv")


@lru_cache(maxsize=1)
def site_heat_profiles() -> pd.DataFrame:
    """One row per site_id, site data joined with its cooling profile and derived heat streams."""
    s = _site_profiles_raw()
    c = cooling_profiles().rename(columns={"confidence": "profile_confidence", "source_ids": "profile_source_ids",
                                           "notes": "profile_notes",
                                           "liquid_heat_share": "profile_liquid_heat_share"})
    df = s.merge(c, on="cooling_profile_id", how="left", validate="many_to_one")
    df["liquid_heat_share"] = df["liquid_heat_share"].fillna(df["profile_liquid_heat_share"])
    df["facility_power_mw"] = df["facility_power_mw"].fillna((df["it_load_mw"] * df["pue_assumed"]).round(1))
    df["recoverable_heat_mw_liquid"] = (df["it_load_mw"] * df["liquid_heat_share"]).round(1)
    df["recoverable_heat_mw_air"] = (df["it_load_mw"] * (1 - df["liquid_heat_share"])).round(1)
    df["is_assumed"] = df["is_assumed"].astype(bool)
    # the weaker of site and profile confidence
    rank = {k: i for i, k in enumerate(CONFIDENCE)}
    df["confidence"] = [max(a, b, key=rank.get) for a, b in zip(df["confidence"], df["profile_confidence"])]
    df["source_ids"] = [";".join(dict.fromkeys(f"{a};{b}".split(";")))
                        for a, b in zip(df["source_ids"], df["profile_source_ids"])]
    cols = ["site_id", "scope", "chip_family", "cooling_type", "cooling_profile_id", "ashrae_class",
            "it_load_mw_low", "it_load_mw", "it_load_mw_high", "facility_power_mw", "pue_assumed",
            *_TEMP_COLS, "liquid_heat_share", "exhaust_air_temp_c", "rack_kw_typ",
            "recoverable_heat_mw_liquid", "recoverable_heat_mw_air",
            "data_year", "evidence", "confidence", "is_assumed", "source_ids", "notes", "profile_notes"]
    return df[cols].sort_values("site_id").reset_index(drop=True)


def heat_profile(site_id: str) -> dict:
    hp = site_heat_profiles()
    row = hp[hp["site_id"] == site_id]
    if row.empty:
        raise KeyError(f"no heat profile for {site_id!r}")
    d = row.iloc[0].to_dict()
    return {k: (None if (isinstance(v, float) and pd.isna(v)) else (v.item() if hasattr(v, "item") else v))
            for k, v in d.items()}
