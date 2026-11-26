"""Look up WRI Aqueduct 4.0 water stress for every site in sites.csv.

Needs internet and geopandas, so solution models never run it. The result is committed as
data_pipeline/aqueduct_sites.csv. To refresh it (for example after adding sites):

    pip install geopandas pyogrio
    python -m data_pipeline.fetch_aqueduct      # or: python data_pipeline/fetch_aqueduct.py

Downloads the official Aqueduct 4.0 zip (WRI, CC BY 4.0, about 1 GB unpacked), opens the File
Geodatabase inside and finds the polygon (basin x province x aquifer) that contains each site.

Columns written: site_id, aqueduct_version, bws_raw, bws_score, bws_cat, bws_label, pfaf_id, gid_1,
name_1, plus future water stress (business as usual 2030 / 2050) when the future layer exists.
bws_score is the 0..5 score the team Excel calls wsi_index.
"""
from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

URL = "https://files.wri.org/aqueduct/aqueduct-4-0-water-risk-data.zip"
HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / "data" / "cache" / "aqueduct"
OUT = HERE / "aqueduct_sites.csv"


def _download() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    z = CACHE / "aqueduct40.zip"
    if not z.exists():
        print(f"downloading {URL} (a few hundred MB, takes a while)", flush=True)
        req = urllib.request.Request(URL, headers={"User-Agent": "heatbeat-data-pipeline"})
        tmp = z.with_suffix(".part")
        with urllib.request.urlopen(req, timeout=1800) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.rename(z)
    print(f"zip size {z.stat().st_size / 1e6:.0f} MB", flush=True)
    return z


def _find_gdb(z: Path) -> Path:
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        gdbs = sorted({n.split(".gdb/")[0] + ".gdb" for n in names if ".gdb/" in n})
        if not gdbs:
            print(*names[:50], sep="\n")
            sys.exit("no .gdb folder in the Aqueduct zip")
        if not (CACHE / gdbs[0]).exists():
            zf.extractall(CACHE, members=[n for n in names if n.startswith(gdbs[0] + "/")])
    return CACHE / gdbs[0]


def _join(gdb: Path, layer: str, pts: gpd.GeoDataFrame, keep) -> pd.DataFrame:
    fields = [str(c) for c in pyogrio.read_info(gdb, layer=layer)["fields"]]
    cols = [c for c in fields if keep(c)]
    print(f"layer {layer}: using {cols}", flush=True)
    df = gpd.read_file(gdb, layer=layer, columns=cols, engine="pyogrio").to_crs(4326)
    j = gpd.sjoin(pts, df, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    return pd.DataFrame(j[["site_id"] + cols])


def main() -> None:
    sites = pd.read_csv(HERE / "sites.csv")
    pts = gpd.GeoDataFrame(sites[["site_id"]], geometry=gpd.points_from_xy(sites.lon, sites.lat), crs=4326)
    gdb = _find_gdb(_download())
    layers = [str(l[0]) for l in pyogrio.list_layers(gdb)]
    print("layers:", layers, flush=True)

    base = next(l for l in layers if "baseline" in l.lower() and "annual" in l.lower())
    out = _join(gdb, base, pts, lambda c: c.startswith("bws_") or c in ("pfaf_id", "gid_1", "name_1"))
    fut = [l for l in layers if "future" in l.lower() and "annual" in l.lower()]
    if fut:
        out = out.merge(_join(gdb, fut[0], pts, lambda c: c.lower().startswith(("bau30_ws_x", "bau50_ws_x"))),
                        on="site_id", how="left")
    out.insert(1, "aqueduct_version", "4.0")
    out.to_csv(OUT, index=False, float_format="%.4f")
    print(out.to_string(), flush=True)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
