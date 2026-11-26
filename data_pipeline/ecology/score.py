"""Turn raw per-site ecology and geology features into the Excel model scores.

Input:  data_pipeline/ecology/raw_site_features.csv  (written by fetch_features.py in GitHub Actions)
Output: data_pipeline/site_ecology.csv                (one row per site_id, read by heatbeat_data.site_ecology_data)

Scores (rules documented in docs/ECOLOGY.md):
    eco_sens_index     1..5  local ecosystem sensitivity     (Excel 1_Site_Inputs_Schema, Input 30)
    geo_storage_score  1..5  subsurface thermal storage fit  (Excel Input 21, BTES/ATES KO gate >= 3)
    mit_tier           low / med / high  default effluent and closed-loop design tier (Excel Input 31)

Run:  python -m data_pipeline.ecology.score
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent
RAW = DIR / "raw_site_features.csv"
OUT = DIR.parent / "site_ecology.csv"

# ---------------------------------------------------------------------------------------------
# eco_sens_index
# ---------------------------------------------------------------------------------------------
# Thresholds (team choice, not taken from a standard; see docs/ECOLOGY.md):
NEAR_M = 1_000      # "on or next to the site"
VICINITY_M = 5_000  # "same watershed reach / discharge zone"
WETLAND_HA_MIN = 5  # wetland area within NEAR_M that counts as a sensitive receptor
COAST_KM = 5        # sea coast within this distance means marine or estuarine discharge is plausible


def _num(v) -> float:
    try:
        f = float(v)
        return f if not math.isnan(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _str(v) -> str:
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)


def eco_points(r: pd.Series) -> tuple[int, list[str]]:
    """Return (points 0..4, reasons). eco_sens_index = 1 + points."""
    pts, why = 0, []
    # P: strictly protected land (PAD-US GAP status 1-2, or OSM protected area / nature reserve outside the US)
    if _num(r.get("prot_n_1km")) > 0:
        pts += 2
        why.append("protected area within 1 km")
    elif _num(r.get("prot_n_5km")) > 0:
        pts += 1
        why.append("protected area within 5 km")
    # H: ESA critical habitat (US only)
    if _num(r.get("crithab_n_1km")) > 0:
        pts += 2
        why.append("ESA critical habitat within 1 km")
    elif _num(r.get("crithab_n_5km")) > 0:
        pts += 1
        why.append("ESA critical habitat within 5 km")
    # W: wetlands on or next to the site
    if _num(r.get("wetland_ha_1km")) >= WETLAND_HA_MIN:
        pts += 1
        why.append(f"wetlands >= {WETLAND_HA_MIN} ha within 1 km")
    # A: estuarine or marine receiving water
    if _num(r.get("estuarine_n_5km")) > 0 or _num(r.get("coast_km")) <= COAST_KM:
        pts += 1
        why.append("estuary or sea coast within 5 km")
    return min(pts, 4), why


# ---------------------------------------------------------------------------------------------
# geo_storage_score
# ---------------------------------------------------------------------------------------------
# Excel definition: 1 = fast-flowing groundwater or unstable soil,
#                   5 = high thermal conductivity granite/bedrock or confined low-flow aquifer.
# Lithology classes from the Macrostrat map unit at the site (keyword match, first hit wins).
LITH_CLASSES = [
    ("organic", 1, r"\b(peat|muck|organic|swamp|marsh)\b"),
    ("evaporite", 1, r"\b(salt|halite|gypsum|anhydrite|evaporite)\b"),
    ("carbonate", 2, r"\b(limestone|dolomite|dolostone|carbonate|chalk|marl|karst)\b"),
    ("volcanic", 3, r"\b(basalt|andesite|rhyolite|tuff|volcanic|lava|ash)\b"),
    ("crystalline", 5, r"\b(granite|granodiorite|gneiss|schist|quartzite|diorite|gabbro|metamorphic|plutonic|"
                       r"igneous|amphibolite|phyllite|slate|tonalite|migmatite|greenstone|metavolcanic|hornfels|granitoid|"
                       r"granitic|metagabbro|metasedimentary|porphyry)\b"),
    ("clastic_rock", 4, r"\b(sandstones?|siltstones?|shales?|mudstones?|claystones?|conglomerates?|arkose|greywacke|graywacke|"
                        r"argillite|siliciclastic|clastic)\b"),
    ("unconsolidated", 3, r"\b(alluvi\w*|sands?|sandy|gravels?|clays?|silts?|till|glacial|loess|unconsolidated|"
                          r"sediments?|diamicton|colluvium|terrace|outwash|fill|surficial|deltaic|eolian)\b"),
]

# USGS Principal Aquifers ROCK_TYPE (aquifers_us, 2003). Codes and meaning per the dataset metadata.
AQUIFER_ROCK = {
    100: "unconsolidated sand and gravel",
    200: "semiconsolidated sand",
    300: "sandstone",
    400: "sandstone and carbonate",
    500: "carbonate",
    600: "igneous and metamorphic",
    700: "other",
}


def lith_class(text: str) -> tuple[str | None, int | None]:
    t = (text or "").lower()
    if not t.strip():
        return None, None
    # Weight by where the keyword appears: Macrostrat 'lith' lists the dominant lithology first.
    best = None
    for name, score, pat in LITH_CLASSES:
        m = re.search(pat, t)
        if m and (best is None or m.start() < best[2]):
            best = (name, score, m.start())
    return (best[0], best[1]) if best else (None, None)


def geo_score(r: pd.Series) -> tuple[int | None, list[str]]:
    why: list[str] = []
    cls, s = lith_class(f"{_str(r.get('macro_lith'))} {_str(r.get('macro_name'))}")
    if s is None:  # most detailed unit too generic (e.g. "sedimentary"): try coarser map scales
        cls, s = lith_class(f"{_str(r.get('macro_descrip'))} {_str(r.get('macro_lith_all'))}")
        if s is not None:
            why.append("lithology from coarser map scale")
    if s is None:
        return None, ["no lithology returned"]
    why.append(f"surface unit {cls} ({s})")
    rock = _num(r.get("aquifer_rock_type"))
    if not math.isnan(rock):
        rock = int(rock)
        if rock == 500 or rock == 400:
            if s > 2:
                why.append(f"karst-prone principal aquifer ({AQUIFER_ROCK[rock]}): capped at 2")
            s = min(s, 2)
        elif rock == 100 and cls == "unconsolidated":
            s = 2
            why.append("productive sand and gravel aquifer, high groundwater flow risk: 2")
        elif rock == 200 and cls in ("unconsolidated", "clastic_rock"):
            s = max(s, 4)
            why.append("semiconsolidated coastal plain aquifer, mostly confined: 4 (ATES)")
        elif rock == 600 and cls != "crystalline":
            s = max(s, 4)
            why.append("crystalline bedrock aquifer below thin cover: 4 (BTES)")
    if _num(r.get("coast_km")) <= 1 and cls in ("unconsolidated", "organic"):
        s = max(1, s - 1)
        why.append("coastal soft sediments within 1 km of sea, saline intrusion risk: -1")
    return int(s), why


# ---------------------------------------------------------------------------------------------
# mit_tier default
# ---------------------------------------------------------------------------------------------
def mit_tier(eco: int) -> tuple[str, str]:
    """Default design tier a permitting agency would expect. Solution models may override it."""
    if eco >= 4:
        return "high", "eco_sens_index >= 4: regulators expect zero liquid discharge or closed loop"
    if eco >= 2:
        return "med", "standard treated discharge under an NPDES-type permit"
    return "med", "low sensitivity, but hyperscale sites rarely permit an open outfall; 'low' not used as default"


def build(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in raw.iterrows():
        pts, ewhy = eco_points(r)
        eco = 1 + pts
        geo, gwhy = geo_score(r)
        tier, twhy = mit_tier(eco)
        us = r.get("country_iso2") == "US"
        missing = [c for c in _str(r.get("sources_failed")).split(";") if c and c != "macrostrat"]
        if us:
            conf_eco = "high" if not missing else "medium"
        else:
            conf_eco = "low" if missing else "medium"
        # A 1 km test on a city centroid is weak: city-level coordinates lower eco confidence one step
        if r.get("coord_precision") == "city_approx":
            conf_eco = {"high": "medium", "medium": "low"}.get(conf_eco, conf_eco)
        geo_src = "macrostrat" + (";usgs_principal_aquifers" if us else "")
        conf_geo = "low" if geo is None else ("medium" if us and not math.isnan(_num(r.get("aquifer_rock_type"))) else "low")
        if geo is None:
            geo, gwhy = 3, ["no lithology returned; neutral default 3 (ASSUMED)"]
        eco_src = ("padus;nwi;usfws_critical_habitat;natural_earth_coast" if us
                   else "osm_overpass;natural_earth_coast")
        rows.append({
            "site_id": r["site_id"],
            "country_iso2": r.get("country_iso2"),
            "eco_sens_index": eco,
            "eco_basis": "; ".join(ewhy) or "no sensitive receptor found within 5 km",
            "eco_source_ids": eco_src,
            "eco_confidence": conf_eco,
            "geo_storage_score": geo,
            "geo_basis": "; ".join(gwhy),
            "geo_source_ids": geo_src,
            "geo_confidence": conf_geo,
            "mit_tier": tier,
            "mit_tier_basis": twhy,
            "mit_tier_is_assumed": 1,
            "coord_precision": r.get("coord_precision"),
            "coast_km": r.get("coast_km"),
            "prot_n_1km": r.get("prot_n_1km"),
            "prot_n_5km": r.get("prot_n_5km"),
            "prot_names": r.get("prot_names"),
            "crithab_n_5km": r.get("crithab_n_5km"),
            "crithab_species": r.get("crithab_species"),
            "wetland_ha_1km": r.get("wetland_ha_1km"),
            "estuarine_n_5km": r.get("estuarine_n_5km"),
            "aquifer_name": r.get("aquifer_name"),
            "aquifer_rock_type": r.get("aquifer_rock_type"),
            "macro_lith": r.get("macro_lith"),
            "macro_name": r.get("macro_name"),
            "sources_failed": r.get("sources_failed"),
            "fetched_utc": r.get("fetched_utc"),
        })
    return pd.DataFrame(rows)


def main() -> None:
    raw = pd.read_csv(RAW)
    sites = pd.read_csv(DIR.parent / "sites.csv")[["site_id", "coord_precision"]]
    raw = raw.drop(columns=["coord_precision"], errors="ignore").merge(sites, on="site_id", how="left")
    out = build(raw)
    out.to_csv(OUT, index=False)
    print(out[["site_id", "eco_sens_index", "geo_storage_score", "mit_tier", "eco_confidence", "geo_confidence"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
