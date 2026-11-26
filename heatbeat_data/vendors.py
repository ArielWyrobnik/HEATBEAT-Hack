"""Companies that can build each solution, nearest and NVIDIA backed first.

Reads data_pipeline/solution_vendors.csv (hand researched, every row has a source and a `verified` status).
Method, the audit of the team's NVIDIA ecosystem Excel and the open gaps: docs/VENDORS.md.

    import heatbeat_data as hd
    hd.vendors()                                                        # DataFrame, one row per company
    hd.vendors_for(["dry_cooler", "heat_pump", "district_heating"], lat=33.4, lon=-112.0)
    hd.vendors_for_cooling("dlc_warm", lat=33.4, lon=-112.0)            # plan builder: liquid cooling + controls

Rules (team choices, not a market study):
- One company per heat chain part, most important part first (the heat use, then heat pump and storage,
  then the heat rejection), at most `n` companies, no company twice.
- Per part: companies with US projects or a US office first, then companies for which this part is their core
  business (a `~` in `roles` marks a side business), then NVIDIA tier (investment > DSX partner >
  Partner Network / Inception > GB200 product > none), then distance to the company's US base.
- Companies with no US office found are only used when nobody else covers that part, and say so.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import pandas as pd

_CSV = Path(__file__).resolve().parents[1] / "data_pipeline" / "solution_vendors.csv"

NVIDIA_TIER = {"investment": 0, "dsx_partner": 1, "partner_network": 2, "inception": 2, "product": 3, "none": 9}
NVIDIA_LABEL = {
    "investment": "NVIDIA invested",
    "dsx_partner": "NVIDIA DSX partner",
    "partner_network": "NVIDIA Partner Network",
    "inception": "NVIDIA Inception",
    "product": "built for NVIDIA GB200",
}
COVERAGE_RANK = {"us": 0, "north_america": 1, "outside_us": 5}

# heat chain part (engineering components, ranking engine option keys, cooling profiles) -> vendor role
ROLE = {
    "dry_cooler": "dry_cooler", "adiabatic_cooler": "adiabatic_cooler", "cooling_tower": "cooling_tower",
    "heat_pump": "heat_pump", "district_heating": "district_heating",
    "tank": "tank", "ates": "ates", "btes": "btes", "btes_ates": "btes",
    "biogas": "biogas", "biogas_meso": "biogas", "biogas_thermo": "biogas",
    "feedwater": "feedwater", "boiler_feedwater": "feedwater",
    "desal_med": "desal", "desal_md": "desal", "desalination": "desal",
    "orc": "orc", "adsorption": "adsorption", "absorption_cooling": "adsorption",
}
# importance when only n companies fit: heat use first, then the parts that make it work, then heat rejection
PRIORITY = ["district_heating", "biogas", "desal", "feedwater", "orc", "adsorption", "heat_pump",
            "btes", "ates", "tank", "cooling_tower", "adiabatic_cooler", "dry_cooler"]
ROLE_LABEL = {
    "dry_cooler": "dry cooler", "adiabatic_cooler": "adiabatic cooler", "cooling_tower": "cooling tower",
    "heat_pump": "heat pump", "district_heating": "district heating", "tank": "storage tank",
    "ates": "aquifer storage", "btes": "borehole storage", "biogas": "digester", "feedwater": "power plant steam cycle",
    "desal": "desalination", "orc": "ORC", "adsorption": "adsorption chiller", "liquid_cooling": "liquid cooling",
    "immersion": "immersion cooling", "two_phase": "two-phase cooling", "controls": "cooling controls",
}
COOLING_ROLES = {
    "dlc_cold": ["liquid_cooling", "two_phase"], "dlc_warm": ["liquid_cooling", "two_phase"],
    "dlc_hot": ["liquid_cooling", "two_phase"], "tpu_dlc": ["liquid_cooling"], "rear_door": ["liquid_cooling"],
    "immersion_1p": ["immersion"],
}


@lru_cache(maxsize=1)
def vendors() -> pd.DataFrame:
    df = pd.read_csv(_CSV, dtype=str, keep_default_na=False)
    df["hq_lat"] = df["hq_lat"].astype(float)
    df["hq_lon"] = df["hq_lon"].astype(float)
    parts = df["roles"].str.split(";")
    df["role_set"] = parts.map(lambda xs: {x.lstrip("~") for x in xs})
    df["side_roles"] = parts.map(lambda xs: {x[1:] for x in xs if x.startswith("~")})
    return df


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def _card(r, role: str, lat, lon) -> dict:
    km = _km(lat, lon, r.hq_lat, r.hq_lon) if lat is not None and lon is not None else None
    if r.coverage == "outside_us":
        where = f"{r.hq}, no US office found"
    elif km is not None and km < 400:
        where = f"{r.hq}, {km:,.0f} km away"
    else:
        where = f"{r.hq}, works across the US" if r.coverage == "us" else f"{r.hq}, serves North America"
    return {
        "vendor_id": r.vendor_id, "name": r.name, "role": role, "role_label": ROLE_LABEL.get(role, role),
        "one_line": r.one_line, "url": r.url, "where": where, "distance_km": None if km is None else round(km),
        "nvidia": NVIDIA_LABEL.get(r.nvidia_link), "nvidia_source": r.nvidia_source or None,
        "verified": r.verified, "source_url": r.evidence_url or r.nvidia_source or None, "note": r.evidence_note or None,
    }


def _ranked(role: str, lat, lon) -> list:
    df = vendors()
    cand = [r for r in df.itertuples() if role in r.role_set]

    def key(r):
        km = _km(lat, lon, r.hq_lat, r.hq_lon) if lat is not None and lon is not None else 0.0
        return (COVERAGE_RANK.get(r.coverage, 5) >= 5, role in r.side_roles, r.verified == "unverified",
                NVIDIA_TIER.get(r.nvidia_link, 9), km)
    cand = sorted(cand, key=key)
    local = [r for r in cand if r.coverage != "outside_us"]
    return local or cand


def vendors_for(components, lat: float | None = None, lon: float | None = None, n: int = 3) -> list[dict]:
    """Up to n companies for a heat chain, one per part, most important part first (see module doc)."""
    roles = list(dict.fromkeys(ROLE[c] for c in components if c in ROLE))
    roles.sort(key=lambda x: PRIORITY.index(x) if x in PRIORITY else len(PRIORITY))
    return _pick(roles, lat, lon, n)


def vendors_for_cooling(cooling_profile: str, lat: float | None = None, lon: float | None = None,
                        n: int = 3) -> list[dict]:
    """Plan builder: who supplies the chosen IT cooling, plus the NVIDIA backed plant controls."""
    roles = COOLING_ROLES.get(cooling_profile, [])
    if not roles:
        return []
    out = _pick(roles, lat, lon, n - 1, fill=True)
    return out + _pick(["controls"], lat, lon, 1)


def _pick(roles: list[str], lat, lon, n: int, fill: bool = True) -> list[dict]:
    out, used = [], set()
    queues = {role: _ranked(role, lat, lon) for role in roles}
    # first pass: one per part; later passes (fill) add the next best for the most important parts
    for _ in range(3 if fill else 1):
        for role in roles:
            if len(out) >= n:
                return out
            for r in queues[role]:
                if r.vendor_id in used:
                    continue
                used.add(r.vendor_id)
                out.append(_card(r, role, lat, lon))
                break
        if len(out) >= n or len(roles) >= n:
            break
    return out
