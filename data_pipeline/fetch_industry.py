"""Nearby industry, CO2, biomass and cold-chain offtake per US site.

Produces the five site inputs of the team Excel model (sheet 1_Site_Inputs_Schema) that describe
neighbours of a data center, keeping its exact JSON keys:

    d_pp_m      distance to a thermal power / CHP plant with a steam cycle      (input 16)
    q_fw_mw     low temperature condensate / feedwater heat sink of that plant  (input 17)
    d_co2_m     distance to CO2 storage, CO2 injection or a CO2 supplier hub    (input 15)
    d_bio_m     distance to organic / forestry waste supply                     (input 14)
    d_market_m  distance to cold storage, seafood processing or produce hub     (input 27)

Stages (each writes small point layers to data_pipeline/industry/, which are committed):

    python -m data_pipeline.fetch_industry --stage eia       # EIA-860/923 via PUDL (S3 parquet)
    python -m data_pipeline.fetch_industry --stage ghgrp     # EPA GHGRP data summary spreadsheets
    python -m data_pipeline.fetch_industry --stage agstar    # EPA AgSTAR livestock digester database
    python -m data_pipeline.fetch_industry --stage osm       # OpenStreetMap via Overpass
    python -m data_pipeline.fetch_industry --stage assemble  # -> data_pipeline/site_industry.csv

Only US sites are covered. Distances are great circle distances multiplied by a circuity factor
(see CIRCUITY), because the Excel thresholds are routing distances. See docs/INDUSTRY.md.
"""
from __future__ import annotations

import argparse
import io
import math
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .common import CACHE_DIR, PIPELINE_DIR, USER_AGENT, http_get, load_sites, log, setup_logging

LAYER_DIR = PIPELINE_DIR / "industry"
OUT_PATH = PIPELINE_DIR / "site_industry.csv"
RAW_DIR = CACHE_DIR / "industry"

# Road / pipe routing distance over straight line distance. US average road circuity is about 1.2
# (Ballou, Rahardja, Sakai 2002, Transportation Research Part A 36(9):843-848). Assumption for pipes.
CIRCUITY = 1.2

# --------------------------------------------------------------------------------------------------
# EIA-860 / EIA-923 (through the Catalyst Cooperative PUDL data release, which republishes them as
# parquet; the raw EIA site is not reachable from every environment)
# --------------------------------------------------------------------------------------------------
PUDL_GENERATORS = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/stable/out_eia__yearly_generators.parquet"
EIA_YEAR = 2025  # latest year with final EIA-860 and EIA-923 data in PUDL stable (checked 2026-11-26)

# Low temperature feedwater heat sink per MW of steam turbine capacity at full load.
# Condensate mass flow per MWe: fossil / CCGT steam cycles about 0.85 kg/s per MWe (about 3 t/h per
# MWe, typical textbook figure), light water nuclear about 1.6 kg/s per MWe (saturated steam,
# 33% efficiency). Heating condensate from 30 C to 60 C takes 4.18 kJ/kgK * 30 K = 125 kJ/kg.
# -> fossil 0.85 * 0.125 = 0.106 MW_th per MWe, nuclear 1.6 * 0.125 = 0.20 MW_th per MWe.
# Engineering estimate, not plant specific (flagged in the output).
QFW_PER_MWE = {"fossil": 0.106, "nuclear": 0.20}
STEAM_SHARE_CS = 1 / 3  # single shaft combined cycle (CS): about one third of output from steam
CF_FALLBACK = 0.5       # when EIA-923 has no capacity factor for a generator (flagged)

FOSSIL_STEAM_FUELS = {"BIT", "SUB", "LIG", "RC", "WC", "PC", "NG", "OG", "BFG", "RFO", "DFO", "PG", "SGC",
                      "TDF", "WH", "PUR", "OTH", "MSW", "WDS", "WDL", "BLQ", "AB", "OBS", "OBL", "OBG", "LFG",
                      "JF", "KER", "WO", "SLW", "SGP", "MWH"}
# Biomass fuels that indicate a nearby forestry or crop residue supply chain or a digester.
BIOMASS_FUELS = {
    "WDS": "forestry (wood solids)", "WDL": "forestry (wood liquids)", "BLQ": "forestry (pulp mill black liquor)",
    "AB": "crop residue (agricultural byproducts)", "OBS": "other biomass solids", "OBL": "other biomass liquids",
    "OBG": "biogas (digester, other biomass gas)",
}
LANDFILL_FUELS = {"LFG": "landfill gas"}


def _download(url: str, dest: Path, timeout: int = 300) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    log.info("download %s", url)
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    return dest


def stage_eia() -> None:
    path = _download(PUDL_GENERATORS, RAW_DIR / "out_eia__yearly_generators.parquet")
    cols = ["plant_id_eia", "generator_id", "report_date", "plant_name_eia", "utility_name_eia", "state",
            "latitude", "longitude", "prime_mover_code", "energy_source_code_1", "technology_description",
            "operational_status", "capacity_mw", "capacity_factor", "net_generation_mwh",
            "associated_combined_heat_power", "carbon_capture"]
    g = pd.read_parquet(path, columns=cols)
    g["year"] = pd.to_datetime(g["report_date"]).dt.year
    g = g[(g["year"] == EIA_YEAR) & (g["operational_status"] == "existing")].copy()
    g = g.dropna(subset=["latitude", "longitude"])
    log.info("EIA %d existing generators: %d", EIA_YEAR, len(g))
    src = f"EIA-860/923 {EIA_YEAR} via PUDL stable ({PUDL_GENERATORS})"

    # Steam cycle plants -> d_pp_m, q_fw_mw
    steam = g[g["prime_mover_code"].isin(["ST", "CA", "CS"])
              & (g["energy_source_code_1"].isin(FOSSIL_STEAM_FUELS | {"NUC"}))].copy()
    steam["cf_missing"] = steam["capacity_factor"].isna()
    cf = steam["capacity_factor"].clip(lower=0, upper=1).fillna(CF_FALLBACK)
    kind = np.where(steam["energy_source_code_1"] == "NUC", "nuclear", "fossil")
    per_mwe = pd.Series(kind).map(QFW_PER_MWE).to_numpy()
    share = np.where(steam["prime_mover_code"] == "CS", STEAM_SHARE_CS, 1.0)
    steam["steam_mw"] = steam["capacity_mw"] * share
    steam["q_fw_full_mw"] = steam["steam_mw"] * per_mwe
    steam["q_fw_mw"] = steam["q_fw_full_mw"] * cf
    steam["is_chp"] = steam["associated_combined_heat_power"].fillna(False).astype(bool)
    agg = steam.groupby("plant_id_eia").agg(
        name=("plant_name_eia", "first"), operator=("utility_name_eia", "first"), state=("state", "first"),
        lat=("latitude", "first"), lon=("longitude", "first"),
        steam_mw=("steam_mw", "sum"), q_fw_full_mw=("q_fw_full_mw", "sum"), q_fw_mw=("q_fw_mw", "sum"),
        fuels=("energy_source_code_1", lambda s: "/".join(sorted(set(s.dropna())))),
        prime_movers=("prime_mover_code", lambda s: "/".join(sorted(set(s.dropna())))),
        is_chp=("is_chp", "any"), cf_missing=("cf_missing", "any"),
    ).reset_index()
    agg["source"] = src
    _write_layer(agg.round({"steam_mw": 1, "q_fw_full_mw": 2, "q_fw_mw": 2}), "eia_steam_plants.csv")

    # Biomass and landfill gas fuelled generators -> d_bio_m
    bio = g[g["energy_source_code_1"].isin(BIOMASS_FUELS | LANDFILL_FUELS)].copy()
    bio["kind"] = bio["energy_source_code_1"].map({**BIOMASS_FUELS, **LANDFILL_FUELS})
    bio = bio.groupby("plant_id_eia").agg(
        name=("plant_name_eia", "first"), state=("state", "first"), lat=("latitude", "first"),
        lon=("longitude", "first"), kind=("kind", "first"), capacity_mw=("capacity_mw", "sum"),
    ).reset_index()
    bio["layer"] = np.where(bio["kind"] == "landfill gas", "landfill", "biomass")
    bio["source"] = src
    _write_layer(bio.round({"capacity_mw": 1}), "eia_biomass_plants.csv")

    # Plants that report carbon capture equipment -> part of d_co2_m
    ccs = g[g["carbon_capture"].fillna(False).astype(bool)]
    ccs = ccs.groupby("plant_id_eia").agg(name=("plant_name_eia", "first"), state=("state", "first"),
                                          lat=("latitude", "first"), lon=("longitude", "first")).reset_index()
    ccs["kind"] = "power plant with carbon capture (EIA-860)"
    ccs["source"] = src
    _write_layer(ccs, "eia_ccs_plants.csv")


# --------------------------------------------------------------------------------------------------
# EPA GHGRP (Greenhouse Gas Reporting Program) data summary spreadsheets
# --------------------------------------------------------------------------------------------------
GHGRP_PAGE = "https://www.epa.gov/ghgreporting/data-sets"


def _find_header(raw: pd.DataFrame) -> int:
    for i in range(min(15, len(raw))):
        vals = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "latitude" in vals and "longitude" in vals:
            return i
    raise ValueError("no header row with Latitude/Longitude")


def stage_ghgrp() -> None:
    html = http_get(GHGRP_PAGE, timeout=60).text
    links = sorted(set(re.findall(r'href="([^"]*data_summary_spreadsheets[^"]*\.zip)"', html)))
    if not links:
        raise RuntimeError("no data summary spreadsheet zip linked on " + GHGRP_PAGE)
    url = links[-1] if links[-1].startswith("http") else "https://www.epa.gov" + links[-1]
    log.info("GHGRP zip candidates %s -> %s", links, url)
    zpath = _download(url, RAW_DIR / "ghgrp_data_summary.zip")
    zf = zipfile.ZipFile(zpath)
    names = [n for n in zf.namelist() if re.search(r"ghgp_data_(\d{4})\.xlsx$", n, re.I)]
    if not names:
        raise RuntimeError(f"no ghgp_data_YYYY.xlsx in {zf.namelist()}")
    name = max(names, key=lambda n: int(re.search(r"(\d{4})\.xlsx$", n).group(1)))
    year = int(re.search(r"(\d{4})\.xlsx$", name).group(1))
    log.info("GHGRP workbook %s", name)
    book = pd.read_excel(io.BytesIO(zf.read(name)), sheet_name=None, header=None)
    frames = []
    for sheet, raw in book.items():
        try:
            h = _find_header(raw)
        except ValueError:
            continue
        df = raw.iloc[h + 1:].copy()
        df.columns = [str(c).strip() for c in raw.iloc[h]]
        df["sheet"] = sheet
        frames.append(df)
    allf = pd.concat(frames, ignore_index=True)
    col = {c.lower(): c for c in allf.columns}

    def pick(*cands):
        for c in cands:
            for k, v in col.items():
                if k.startswith(c):
                    return v
        return None

    c_sub, c_naics = pick("industry type (subparts)", "subparts"), pick("primary naics")
    c_name, c_state = pick("facility name"), pick("state")
    out = pd.DataFrame({
        "ghgrp_id": allf[pick("facility id")], "name": allf[c_name], "state": allf[c_state],
        "lat": pd.to_numeric(allf[pick("latitude")], errors="coerce"),
        "lon": pd.to_numeric(allf[pick("longitude")], errors="coerce"),
        "subparts": allf[c_sub].astype(str) if c_sub else "",
        "naics": allf[c_naics].astype(str).str.replace(r"\.0$", "", regex=True) if c_naics else "",
        "sheet": allf["sheet"],
    }).dropna(subset=["lat", "lon"]).drop_duplicates(["ghgrp_id", "sheet"])
    src = f"EPA GHGRP {year} data summary spreadsheets ({url})"
    sub = out["subparts"].str.upper()

    def has(code):
        return sub.str.contains(rf"(?:^|[^A-Z]){code}(?:[^A-Z]|$)", regex=True)

    co2 = out[has("RR") | has("UU") | has("PP") | out["sheet"].str.contains("injection", case=False)].copy()
    co2["kind"] = np.select(
        [has("RR")[co2.index], has("UU")[co2.index] | co2["sheet"].str.contains("injection", case=False)],
        ["geologic sequestration (GHGRP subpart RR)", "CO2 injection, e.g. EOR (GHGRP subpart UU)"],
        "CO2 supplier / capture hub (GHGRP subpart PP)")
    co2["source"] = src
    _write_layer(co2.drop_duplicates("ghgrp_id"), "ghgrp_co2.csv")

    food = out[out["naics"].str.startswith("311")].drop_duplicates("ghgrp_id").copy()
    food["kind"] = np.where(food["naics"].str.startswith("3117"), "seafood processing (GHGRP NAICS 3117)",
                            "food processing (GHGRP NAICS 311)")
    food["source"] = src
    _write_layer(food, "ghgrp_food.csv")


# --------------------------------------------------------------------------------------------------
# EPA AgSTAR livestock anaerobic digester database (manure)
# --------------------------------------------------------------------------------------------------
AGSTAR_PAGE = "https://www.epa.gov/agstar/livestock-anaerobic-digester-database"


def stage_agstar() -> None:
    html = http_get(AGSTAR_PAGE, timeout=60).text
    links = re.findall(r'href="([^"]+\.xlsx)"', html)
    if not links:
        raise RuntimeError("no xlsx linked on " + AGSTAR_PAGE)
    url = links[0] if links[0].startswith("http") else "https://www.epa.gov" + links[0]
    path = _download(url, RAW_DIR / "agstar.xlsx")
    book = pd.read_excel(path, sheet_name=None, header=None)
    for sheet, raw in book.items():
        try:
            h = _find_header(raw)
        except ValueError:
            continue
        df = raw.iloc[h + 1:].copy()
        df.columns = [str(c).strip() for c in raw.iloc[h]]
        cl = {c.lower(): c for c in df.columns}
        name = next((cl[k] for k in cl if k.startswith("project name")), None) or next(iter(cl.values()))
        status = next((cl[k] for k in cl if k == "status"), None)
        animal = next((cl[k] for k in cl if k.startswith("animal")), None)
        out = pd.DataFrame({
            "name": df[name], "state": df[cl.get("state")] if "state" in cl else "",
            "lat": pd.to_numeric(df[cl["latitude"]], errors="coerce"),
            "lon": pd.to_numeric(df[cl["longitude"]], errors="coerce"),
            "status": df[status] if status else "",
            "kind": ("manure digester: " + df[animal].astype(str)) if animal else "manure digester",
        }).dropna(subset=["lat", "lon"])
        if status:
            out = out[out["status"].astype(str).str.contains("operational", case=False)]
        out["source"] = f"EPA AgSTAR Livestock Anaerobic Digester Database ({url})"
        _write_layer(out, "agstar_digesters.csv")
        return
    raise RuntimeError("AgSTAR workbook has no sheet with Latitude/Longitude columns")


# --------------------------------------------------------------------------------------------------
# OpenStreetMap (Overpass API): cold storage, seafood, produce wholesale near each site
# --------------------------------------------------------------------------------------------------
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
OSM_RADIUS_M = 60_000
_OSM_FILTERS = [
    '["industrial"~"^(cold_storage|refrigerated_warehouse|fish_processing|seafood|food|food_processing|slaughterhouse|meat|dairy)$"]',
    '["building"~"^(cold_storage|refrigerated_warehouse)$"]',
    '["warehouse"~"cold|refrigerat|frozen",i]',
    '["product"~"fish|seafood|frozen|produce|vegetable|fruit",i]',
    '["amenity"="marketplace"]["wholesale"]',
    '["shop"="wholesale"]',
    '["building"]["name"~"cold storage|refrigerated|seafood|produce market|produce terminal|terminal market|lineage|americold",i]',
]


def _osm_kind(tags: dict) -> str:
    text = " ".join(f"{k}={v}" for k, v in tags.items()).lower()
    if re.search(r"cold|refrigerat|frozen|lineage|americold", text):
        return "cold storage"
    if re.search(r"fish|seafood", text):
        return "seafood"
    if re.search(r"produce|vegetable|fruit|terminal market|marketplace|wholesale", text):
        return "produce / wholesale food hub"
    return "food processing"


def _overpass(q: str, label: str, tries: int = 4, timeout: int = 150) -> dict | None:
    for attempt in range(tries):
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(url, data={"data": q}, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                return r.json()
            log.warning("Overpass %s HTTP %s for %s", url, r.status_code, label)
        except Exception as exc:  # noqa: BLE001
            log.warning("Overpass %s failed for %s: %s", url, label, exc)
        time.sleep(10 * (attempt + 1))
    return None


ZONING_RADIUS_M = 3_000


def stage_osm_zoning() -> None:
    """Proxy for ind_zoning: is there OSM landuse=industrial within 3 km of the site coordinate?"""
    rows = []
    for _, s in _us_sites().iterrows():
        q = (f'[out:json][timeout:90];(way(around:{ZONING_RADIUS_M},{s.lat},{s.lon})["landuse"="industrial"];'
             f'relation(around:{ZONING_RADIUS_M},{s.lat},{s.lon})["landuse"="industrial"];);out ids;')
        data = _overpass(q, s.site_id + " zoning")
        if data is None:
            continue
        rows.append({"site_id": s.site_id, "n_industrial_landuse_3km": len(data.get("elements", []))})
        time.sleep(2)
    if not rows:
        raise RuntimeError("Overpass zoning query returned nothing")
    out = pd.DataFrame(rows)
    out["source"] = "OpenStreetMap landuse=industrial via Overpass API (ODbL), queried " + time.strftime("%Y-%m-%d")
    _write_layer(out, "osm_industrial_landuse.csv")


def stage_osm() -> None:
    """One small Overpass query per site and filter (a single combined query timed out on GitHub runners)."""
    sites = _us_sites()
    rows = []
    for _, s in sites.iterrows():
        elements = []
        for f in _OSM_FILTERS:
            q = f"[out:json][timeout:90];nwr(around:{OSM_RADIUS_M},{s.lat},{s.lon}){f};out center tags;"
            data = _overpass(q, f"{s.site_id} {f[:30]}", tries=2, timeout=120)
            if data is not None:
                elements += data.get("elements", [])
            time.sleep(1)
        data = {"elements": elements}
        n = 0
        for el in data.get("elements", []):
            lat = el.get("lat", el.get("center", {}).get("lat"))
            lon = el.get("lon", el.get("center", {}).get("lon"))
            if lat is None:
                continue
            tags = el.get("tags", {})
            if tags.get("shop") == "wholesale" and not re.search(
                    r"food|produce|fish|seafood|fruit|vegetable|meat|grocer", " ".join(tags.values()), re.I):
                continue
            rows.append({"osm_id": f"{el['type']}/{el['id']}", "name": tags.get("name", ""),
                         "lat": lat, "lon": lon, "kind": _osm_kind(tags), "query_site": s.site_id})
            n += 1
        log.info("OSM %s: %d features", s.site_id, n)
        if rows:  # write after every site, so a step timeout keeps what arrived
            part = pd.DataFrame(rows).drop_duplicates("osm_id")
            part["source"] = "OpenStreetMap contributors via Overpass API (ODbL), queried " + time.strftime("%Y-%m-%d")
            _write_layer(part, "osm_market.csv")
    if not rows:
        raise RuntimeError("Overpass returned nothing for any site")
    out = pd.DataFrame(rows).drop_duplicates("osm_id")
    out["source"] = "OpenStreetMap contributors via Overpass API (ODbL), queried " + time.strftime("%Y-%m-%d")
    _write_layer(out, "osm_market.csv")


# --------------------------------------------------------------------------------------------------
# Assemble
# --------------------------------------------------------------------------------------------------
def _us_sites() -> pd.DataFrame:
    s = load_sites()
    return s[s["country_iso2"] == "US"].reset_index(drop=True)


def _write_layer(df: pd.DataFrame, name: str) -> None:
    LAYER_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(LAYER_DIR / name, index=False)
    log.info("wrote %s (%d rows)", name, len(df))


def _layer(name: str) -> pd.DataFrame | None:
    p = LAYER_DIR / name
    if not p.exists():
        log.warning("layer %s missing", name)
        return None
    return pd.read_csv(p)


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6_371_000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(np.asarray(lon2) - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def _nearest(site, pts: pd.DataFrame | None):
    if pts is None or pts.empty:
        return None
    d = haversine_m(site.lat, site.lon, pts["lat"].to_numpy(float), pts["lon"].to_numpy(float))
    i = int(np.argmin(d))
    return pts.iloc[i], float(d[i])


def _confidence(base: str, site, straight_m: float | None) -> str:
    """Downgrade when the site coordinate is only known to city level and the distance is short."""
    if straight_m is None:
        return "low"
    order = ["low", "medium", "high"]
    lvl = order.index(base)
    if site.coord_precision == "city_approx" and straight_m < 10_000:
        lvl -= 1
    elif site.coord_precision == "campus_approx" and straight_m < 2_000:
        lvl -= 1
    return order[max(lvl, 0)]


def _concat(*dfs):
    dfs = [d for d in dfs if d is not None and not d.empty]
    return pd.concat(dfs, ignore_index=True) if dfs else None


def stage_assemble() -> pd.DataFrame:
    sites = _us_sites()
    steam = _layer("eia_steam_plants.csv")
    bio_eia = _layer("eia_biomass_plants.csv")
    ccs = _layer("eia_ccs_plants.csv")
    co2 = _layer("ghgrp_co2.csv")
    food = _layer("ghgrp_food.csv")
    agstar = _layer("agstar_digesters.csv")
    osm = _layer("osm_market.csv")
    zoning = _layer("osm_industrial_landuse.csv")

    bio_main = _concat(bio_eia[bio_eia["layer"] == "biomass"] if bio_eia is not None else None,
                       agstar,
                       food[food["kind"].str.startswith("food")] if food is not None else None)
    landfill = bio_eia[bio_eia["layer"] == "landfill"] if bio_eia is not None else None
    co2_pts = _concat(co2, ccs)
    market_core = _concat(osm[osm["kind"] != "food processing"] if osm is not None else None,
                          food[food["kind"].str.startswith("seafood")] if food is not None else None)
    market_food = _concat(osm[osm["kind"] == "food processing"] if osm is not None else None)
    qualifying = steam[steam["q_fw_mw"] >= 2.0] if steam is not None else None  # Excel KO: q_fw >= 2 MW

    rows = []
    for _, s in sites.iterrows():
        r = {"site_id": s.site_id, "site_coord_precision": s.coord_precision}

        # Power plant: nearest steam cycle plant whose average sink passes the 2 MW gate
        hit = _nearest(s, qualifying)
        if hit:
            p, d = hit
            r.update(d_pp_m=round(d * CIRCUITY), d_pp_straight_m=round(d), q_fw_mw=p.q_fw_mw,
                     q_fw_full_load_mw=p.q_fw_full_mw, pp_name=p["name"], pp_eia_id=int(p.plant_id_eia),
                     pp_steam_mw=p.steam_mw, pp_fuels=p.fuels, pp_prime_movers=p.prime_movers,
                     pp_is_chp=bool(p.is_chp),
                     pp_source=p.source + "; q_fw is an engineering estimate (see docs/INDUSTRY.md)",
                     pp_confidence=_confidence("medium", s, d))
        any_hit = _nearest(s, steam)
        if any_hit:
            p, d = any_hit
            r.update(d_pp_any_m=round(d * CIRCUITY), pp_any_name=p["name"], pp_any_q_fw_mw=p.q_fw_mw)

        # CO2
        hit = _nearest(s, co2_pts)
        if hit:
            p, d = hit
            r.update(d_co2_m=round(d * CIRCUITY), d_co2_straight_m=round(d), co2_name=p["name"], co2_kind=p.kind,
                     co2_source=p.source, co2_confidence=_confidence("medium", s, d))
        else:
            r.update(co2_confidence="low", co2_source="no CO2 layer available")

        # Biomass
        hit = _nearest(s, bio_main)
        if hit:
            p, d = hit
            r.update(d_bio_m=round(d * CIRCUITY), d_bio_straight_m=round(d), bio_name=p["name"], bio_kind=p.kind,
                     bio_source=p.source, bio_confidence=_confidence("medium", s, d))
        hit = _nearest(s, landfill)
        if hit:
            p, d = hit
            r.update(d_landfill_m=round(d * CIRCUITY), landfill_name=p["name"])

        # Market / cold chain
        hit = _nearest(s, market_core)
        base = "medium"
        if hit is None or hit[1] > OSM_RADIUS_M:
            hit, base = _nearest(s, market_food), "low"
        if hit and hit[1] <= OSM_RADIUS_M:
            p, d = hit
            r.update(d_market_m=round(d * CIRCUITY), d_market_straight_m=round(d), market_name=p["name"],
                     market_kind=p.kind, market_source=p.source, market_confidence=_confidence(base, s, d))
        elif osm is not None:
            r.update(d_market_m=round(OSM_RADIUS_M * CIRCUITY), market_kind="none found within search radius",
                     market_source=f"OpenStreetMap (lower bound: nothing tagged within {OSM_RADIUS_M // 1000} km)",
                     market_confidence="low")
        else:
            r.update(market_confidence="low", market_source="no market layer available")
        # Industrial zoning proxy
        if zoning is not None and s.site_id in set(zoning["site_id"]):
            n = int(zoning.set_index("site_id").loc[s.site_id, "n_industrial_landuse_3km"])
            r.update(ind_zoning=int(n > 0), n_industrial_landuse_3km=n,
                     zoning_source=zoning["source"].iloc[0] + "; proxy, not a zoning map",
                     zoning_confidence="low")
        rows.append(r)

    out = pd.DataFrame(rows)
    lead = ["site_id", "d_pp_m", "q_fw_mw", "d_co2_m", "d_bio_m", "d_market_m"]
    for c in lead:
        if c not in out:
            out[c] = np.nan
    out = out[lead + [c for c in out.columns if c not in lead]]
    out.to_csv(OUT_PATH, index=False)
    log.info("wrote %s (%d sites)", OUT_PATH, len(out))
    _write_ranking_inputs(out)
    return out


RANKING_PATH = PIPELINE_DIR / "site_ranking_inputs_industry.csv"


def _write_ranking_inputs(t: pd.DataFrame) -> None:
    """Long format for the ranking engine (heatbeat_ranking): site_id,key,value,status,source,note."""
    spec = [  # key, block, note builder
        ("d_pp_m", "pp", lambda r: f"{r.get('pp_name')} ({r.get('pp_fuels')}, {r.get('pp_steam_mw')} MW steam); "
                                   f"routing = straight line x {CIRCUITY}; confidence {r.get('pp_confidence')}"),
        ("q_fw_mw", "pp", lambda r: f"engineering estimate for {r.get('pp_name')}: steam MW x k x 2025 capacity "
                                    f"factor (docs/INDUSTRY.md); full load {r.get('q_fw_full_load_mw')} MW"),
        ("d_co2_m", "co2", lambda r: f"{r.get('co2_name')}: {r.get('co2_kind')}; no pipeline routes; "
                                     f"confidence {r.get('co2_confidence')}"),
        ("d_bio_m", "bio", lambda r: f"{r.get('bio_name')}: {r.get('bio_kind')}; confidence {r.get('bio_confidence')}"),
        ("ind_zoning", "zoning", lambda r: f"proxy: {r.get('n_industrial_landuse_3km')} OSM landuse=industrial "
                                           f"areas within 3 km of the (approximate) site coordinate"),
        ("d_market_m", "market", lambda r: f"{r.get('market_name')}: {r.get('market_kind')}; "
                                           f"confidence {r.get('market_confidence')}"),
    ]
    rows = []
    for r in t.to_dict("records"):
        for key, block, note in spec:
            v = r.get(key)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            assumption = key in ("q_fw_mw", "ind_zoning") or "none found" in str(r.get("market_kind", "")) and key == "d_market_m"
            rows.append({"site_id": r["site_id"], "key": key, "value": v,
                         "status": "assumption" if assumption else "data",
                         "source": r.get(f"{block}_source"), "note": note(r)})
    pd.DataFrame(rows).to_csv(RANKING_PATH, index=False)
    log.info("wrote %s (%d rows)", RANKING_PATH, len(rows))


STAGES = {"eia": stage_eia, "ghgrp": stage_ghgrp, "agstar": stage_agstar, "osm": stage_osm,
          "osm_zoning": stage_osm_zoning,
          "assemble": stage_assemble}


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=list(STAGES) + ["all"], default="all")
    a = ap.parse_args()
    for name in (list(STAGES) if a.stage == "all" else [a.stage]):
        try:
            STAGES[name]()
        except Exception as exc:  # noqa: BLE001
            log.error("stage %s failed: %s", name, exc)
            if a.stage != "all":
                raise


if __name__ == "__main__":
    main()
