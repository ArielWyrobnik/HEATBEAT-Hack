"""Fetch raw ecology and geology features for every site in data_pipeline/sites.csv.

Runs in GitHub Actions (workflow "Build site ecology and geology"): the cloud sandbox cannot reach
these hosts. Writes data_pipeline/ecology/raw_site_features.csv; score.py turns it into scores.

Sources (all public, no key):
  US sites
    padus      USGS PAD-US 4, "Protection Status by GAP Status Code" feature service (GAP 1-2 = managed
               for biodiversity). https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview
    nwi        USFWS National Wetlands Inventory map service (wetland polygons, Cowardin classes).
               https://www.fws.gov/program/national-wetlands-inventory
    crithab    USFWS ESA Final Critical Habitat feature service. https://ecos.fws.gov/ecp/report/table/critical-habitat.html
    aquifers   USGS Principal Aquifers of the US (2003) via the Esri Living Atlas "USA Aquifers" layer.
               https://water.usgs.gov/ogw/aquiferbasics/
  All sites
    macrostrat Macrostrat geologic map API, surface map unit at the point (CC-BY 4.0). https://macrostrat.org/api
    coast      Natural Earth 1:10m coastline (public domain), great-circle distance to nearest vertex.
  Non-US sites
    osm        OpenStreetMap via Overpass API (ODbL): protected areas, nature reserves, wetlands.

Run:  python -m data_pipeline.ecology.fetch_features
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

DIR = Path(__file__).resolve().parent
SITES = DIR.parent / "sites.csv"
OUT = DIR / "raw_site_features.csv"
UA = {"User-Agent": "heatbeat-hackathon-data-pipeline/0.1 (research, non-commercial)"}

PADUS = "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/PADUS_Protection_Status_by_GAP_Status_Code/FeatureServer"
NWI = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0"
CRITHAB = "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/USFWS_Critical_Habitat/FeatureServer/0"
AQUIFERS = "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/USA_Aquifers_Feature_Layer_view/FeatureServer"
MACROSTRAT = "https://macrostrat.org/api/v2/geologic_units/map"
# Mirrors: on GitHub runners overpass-api.de sometimes fails with "Network is unreachable" (IPv6 route)
OVERPASS_MIRRORS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                    "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
COAST = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_coastline.geojson"

VEGETATED_WETLANDS = ("Freshwater Emergent Wetland", "Freshwater Forested/Shrub Wetland", "Estuarine and Marine Wetland")
BUFFER_1KM_HA = math.pi * 1.0 ** 2 * 100  # 314 ha, cap per polygon so one huge polygon cannot dominate
SCALE_ORDER = {"large": 0, "medium": 1, "small": 2, "tiny": 3}


def get_json(url: str, params: dict | None = None, retries: int = 3, timeout: int = 60, post: bool = False) -> dict:
    last = None
    for i in range(retries):
        try:
            if post:
                r = requests.post(url, data=params, headers=UA, timeout=timeout)
            else:
                r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            j = r.json()
            if isinstance(j, dict) and "error" in j:
                raise RuntimeError(f"service error: {j['error']}")
            return j
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(4 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def arcgis_query(layer_url: str, lat: float, lon: float, dist_m: float, out_fields: str = "*",
                 where: str = "1=1", count_only: bool = False) -> list[dict] | int:
    params = dict(geometry=f"{lon},{lat}", geometryType="esriGeometryPoint", inSR=4326,
                  spatialRel="esriSpatialRelIntersects", distance=dist_m, units="esriSRUnit_Meter",
                  where=where, outFields=out_fields, returnGeometry="false", f="json")
    if count_only:
        params["returnCountOnly"] = "true"
        return int(get_json(f"{layer_url}/query", params).get("count", 0))
    feats, offset = [], 0
    while True:
        params.update(resultOffset=offset, resultRecordCount=1000)
        j = get_json(f"{layer_url}/query", params)
        batch = [f["attributes"] for f in j.get("features", [])]
        feats += batch
        if not j.get("exceededTransferLimit") or not batch:
            return feats
        offset += len(batch)


def find_layer(service_url: str, field_pattern: str) -> tuple[str, dict[str, str]]:
    """First layer of a FeatureServer that has a field matching field_pattern. Returns (url, fields lower->real)."""
    svc = get_json(service_url, {"f": "json"})
    for lyr in svc.get("layers", []):
        url = f"{service_url}/{lyr['id']}"
        meta = get_json(url, {"f": "json"})
        fields = {f["name"].lower(): f["name"] for f in meta.get("fields", [])}
        if any(re.search(field_pattern, k) for k in fields):
            print(f"[layer] {url} ({lyr.get('name')}): fields {list(fields.values())}")
            return url, fields
    raise RuntimeError(f"no layer with field /{field_pattern}/ in {service_url}")


def pick(fields: dict[str, str], *patterns: str) -> str | None:
    for p in patterns:
        for k, v in fields.items():
            if re.search(p, k):
                return v
    return None


# ------------------------------------------------------------------------------- coastline
def coast_points() -> np.ndarray:
    g = requests.get(COAST, headers=UA, timeout=120).json()
    pts = []
    for f in g["features"]:
        geom = f["geometry"]
        lines = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        for line in lines:
            pts.extend(line)
    return np.radians(np.array(pts))


def coast_km(pts: np.ndarray, lat: float, lon: float) -> float:
    la, lo = math.radians(lat), math.radians(lon)
    d = 2 * 6371.0 * np.arcsin(np.sqrt(np.sin((pts[:, 1] - la) / 2) ** 2
                                       + math.cos(la) * np.cos(pts[:, 1]) * np.sin((pts[:, 0] - lo) / 2) ** 2))
    return round(float(d.min()), 2)


# ------------------------------------------------------------------------------- US sources
class US:
    def __init__(self) -> None:
        self.padus_url, f = find_layer(PADUS, r"gap")
        self.padus_gap = pick(f, r"^gap_sts$", r"gap_?sts", r"gap")
        self.padus_name = pick(f, r"^unit_nm$", r"unit_?n", r"loc_nm", r"name")
        self.crit_fields = {k.lower(): k for k in
                            [x["name"] for x in get_json(CRITHAB, {"f": "json"}).get("fields", [])]}
        print(f"[layer] {CRITHAB}: fields {list(self.crit_fields.values())}")
        self.crit_name = pick(self.crit_fields, r"^comname$", r"comname", r"common", r"sciname")
        self.aq_url, f = find_layer(AQUIFERS, r"rock")
        self.aq_rock = pick(f, r"^rock_type$", r"rock_?type", r"rock")
        self.aq_rock_name = pick(f, r"^rock_name$", r"rock_?name")
        self.aq_name = pick(f, r"^aq_name$", r"aq_?name", r"aquifer")

    def padus(self, lat: float, lon: float) -> dict:
        out = {}
        for d, key in ((1000, "1km"), (5000, "5km")):
            feats = arcgis_query(self.padus_url, lat, lon, d, out_fields=f"{self.padus_gap},{self.padus_name}")
            strict = [a for a in feats if str(a.get(self.padus_gap, "")).strip()[:1] in ("1", "2")]
            out[f"prot_n_{key}"] = len(strict)
            out[f"padus_any_n_{key}"] = len(feats)
            if key == "5km":
                names = sorted({str(a.get(self.padus_name)) for a in strict if a.get(self.padus_name)})
                out["prot_names"] = "; ".join(names[:6])
        return out

    def nwi(self, lat: float, lon: float) -> dict:
        feats = arcgis_query(NWI, lat, lon, 1000, out_fields="WETLAND_TYPE,ACRES")
        ha = sum(min(float(a.get("ACRES") or 0) * 0.404686, BUFFER_1KM_HA)
                 for a in feats if a.get("WETLAND_TYPE") in VEGETATED_WETLANDS)
        est = arcgis_query(NWI, lat, lon, 5000, where="WETLAND_TYPE LIKE 'Estuarine%'", count_only=True)
        return {"wetland_ha_1km": round(ha, 1), "wetland_polys_1km": len(feats), "estuarine_n_5km": est}

    def crithab(self, lat: float, lon: float) -> dict:
        out = {}
        for d, key in ((1000, "1km"), (5000, "5km")):
            feats = arcgis_query(CRITHAB, lat, lon, d, out_fields=self.crit_name or "*")
            out[f"crithab_n_{key}"] = len(feats)
            if key == "5km":
                out["crithab_species"] = "; ".join(sorted({str(a.get(self.crit_name)) for a in feats
                                                           if self.crit_name and a.get(self.crit_name)})[:6])
        return out

    def aquifer(self, lat: float, lon: float) -> dict:
        fields = ",".join(x for x in (self.aq_rock, self.aq_rock_name, self.aq_name) if x)
        feats = arcgis_query(self.aq_url, lat, lon, 0, out_fields=fields)
        if not feats:
            return {"aquifer_name": "none mapped", "aquifer_rock_type": None, "aquifer_rock_name": None}
        a = feats[0]
        return {"aquifer_name": a.get(self.aq_name), "aquifer_rock_type": a.get(self.aq_rock),
                "aquifer_rock_name": a.get(self.aq_rock_name)}


# ------------------------------------------------------------------------------- global sources
def macrostrat(lat: float, lon: float) -> dict:
    j = get_json(MACROSTRAT, {"lat": lat, "lng": lon})
    units = j.get("success", {}).get("data", [])
    if not units:
        return {"macro_lith": None}
    units = sorted(units, key=lambda x: SCALE_ORDER.get(x.get("scale"), 9))
    u = units[0]
    return {"macro_lith": u.get("lith"), "macro_lith_all": " | ".join(x.get("lith") or "" for x in units), "macro_name": u.get("name") or u.get("strat_name"),
            "macro_age": u.get("b_int_name"), "macro_scale": u.get("scale"),
            "macro_descrip": (u.get("descrip") or "")[:300]}


def osm(lat: float, lon: float) -> dict:
    def prot(r: int) -> str:
        return (f'nwr(around:{r},{lat},{lon})[boundary=protected_area][protect_class~"^[1-4]$"];'
                f'nwr(around:{r},{lat},{lon})[leisure=nature_reserve];'
                f'nwr(around:{r},{lat},{lon})[boundary=national_park];')
    q = (f"[out:json][timeout:90];({prot(5000)})->.p5;({prot(1000)})->.p1;"
         f"nwr(around:1000,{lat},{lon})[natural=wetland]->.w;"
         ".p5 out tags; .p1 out ids; .w out ids;")
    j, last = None, None
    for url in OVERPASS_MIRRORS:
        try:
            j = get_json(url, {"data": q}, post=True, timeout=120, retries=2)
            break
        except Exception as e:  # noqa: BLE001
            last = e
    if j is None:
        raise RuntimeError(f"all Overpass mirrors failed: {last}")
    els = j.get("elements", [])
    # Output order is p5 (with tags), then p1 and w (ids only, no tags)
    p5 = [e for e in els if e.get("tags")]
    rest = [e for e in els if not e.get("tags")]
    p5_ids = {(e["type"], e["id"]) for e in p5}
    p1 = [e for e in rest if (e["type"], e["id"]) in p5_ids]
    wet = [e for e in rest if (e["type"], e["id"]) not in p5_ids]
    names = sorted({e["tags"].get("name:en") or e["tags"].get("name", "") for e in p5} - {""})
    return {"prot_n_5km": len(p5), "prot_n_1km": len(p1), "prot_names": "; ".join(names[:6]),
            # 'out ids' gives no area; one mapped wetland within 1 km counts as >= threshold (flagged in docs)
            "wetland_ha_1km": 5.0 if wet else 0.0, "wetland_polys_1km": len(wet)}


def _hav_km(la1, lo1, la2, lo2) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (la1, lo1, la2, lo2))
    return 2 * 6371 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2
                                          + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def main() -> int:
    sites = pd.read_csv(SITES)
    pts = coast_points()
    us = None
    try:
        us = US()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] US layer discovery failed: {e}")
    rows = []
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    for _, s in sites.iterrows():
        lat, lon = float(s.lat), float(s.lon)
        row = {"site_id": s.site_id, "country_iso2": s.country_iso2, "lat": lat, "lon": lon,
               "coast_km": coast_km(pts, lat, lon), "fetched_utc": now}
        failed = []
        jobs = [("macrostrat", macrostrat)]
        if s.country_iso2 == "US":
            if us is None:
                failed += ["padus", "nwi", "crithab", "aquifers"]
            else:
                jobs += [("padus", us.padus), ("nwi", us.nwi), ("crithab", us.crithab), ("aquifers", us.aquifer)]
        else:
            jobs += [("osm", osm)]
        for name, fn in jobs:
            try:
                row.update(fn(lat, lon))
            except Exception as e:  # noqa: BLE001
                print(f"[fail] {s.site_id} {name}: {e}")
                failed.append(name)
            time.sleep(1.0 if name == "osm" else 0.2)
        row["sources_failed"] = ";".join(failed)
        print(json.dumps(row, default=str)[:600])
        rows.append(row)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    n_fail = sum(1 for r in rows if r["sources_failed"])
    print(f"wrote {OUT} ({len(rows)} sites, {n_fail} with at least one failed source)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
