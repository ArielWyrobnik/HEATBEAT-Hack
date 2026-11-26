"""Compute GIS site inputs (distances, terrain, land, district heating) for every site.

Writes data_pipeline/site_gis.csv keyed by site_id. The column names follow the JSON keys of the
team Excel model (sheet 1_Site_Inputs_Schema): d_coast_m, d_water_m, dz_m, slope_deg, flat_land_m2,
agri_land_m2, campus_area_m2, d_dh_m, has_existing_dh, rho_heat_mwh_m, ind_zoning. Every field has a
<field>_source and <field>_confidence column. Method and caveats: docs/GIS.md.

All inputs are open datasets that are read straight from public cloud buckets (no API key):

* Elevation: AWS Terrain Tiles (Terrarium PNG, zoom 13, about 15 to 19 m pixels; USGS 3DEP inside
  the US, SRTM and others elsewhere). https://registry.opendata.aws/terrain-tiles/
* Land cover: ESA WorldCover 10 m v200 (2021). https://registry.opendata.aws/esa-worldcover-vito/
* Water, land use, buildings, pipelines: Overture Maps release OVERTURE_RELEASE (mostly
  OpenStreetMap). https://docs.overturemaps.org/
* Coastline fallback: Natural Earth 10 m coastline. https://www.naturalearthdata.com/
* Heating degree days: NOAA GHCN-Daily (nearest station with TMAX and TMIN, 2015 to 2024).
  https://registry.opendata.aws/noaa-ghcn/
* Known district heating systems: data_pipeline/district_heating_systems.csv (curated, approximate).

Run:  pip install -r requirements-gis.txt && python -m data_pipeline.fetch_gis [--sites id1,id2]
Downloads are cached in data/cache/gis/ (git-ignored), so a second run is fast.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import math
import os
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = ROOT / "data_pipeline"
CACHE = Path(os.getenv("HEATBEAT_DATA_DIR", ROOT / "data")) / "cache" / "gis"
OUT_CSV = PIPELINE_DIR / "site_gis.csv"

OVERTURE_RELEASE = "2026-11-18.0"
OVERTURE_ROOT = f"overturemaps-us-west-2/release/{OVERTURE_RELEASE}/"
TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
WORLDCOVER_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                  "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
NE_COAST_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
                "ne_10m_coastline.geojson")
GHCN_URL = "https://noaa-ghcn-pds.s3.amazonaws.com/"

# ---- Method parameters (team assumptions unless a source is given; see docs/GIS.md) ----
DEM_ZOOM = 13
LAND_RADIUS_M = 2000          # land and slope analysis disk around the site point
SLOPE_RADIUS_M = 1000         # slope_deg = mean slope inside this disk
FLAT_SLOPE_DEG = 5.0          # "flat" threshold; Excel KO for fish farm / greenhouse is 6 to 10 deg
GRID_M = 10                   # analysis grid (matches WorldCover resolution)
ZONING_RADIUS_M = 1000        # industrial land use within this distance -> ind_zoning = 1
BUILDING_RADIUS_M = 6000      # building heat density search radius
CELL_M = 250                  # heat density cell size
DH_LIN_MIN = 1.5              # MWh/(m yr): Excel greenfield KO for linear heat density
DH_CONNECT_M = 3000           # Excel greenfield KO distance for district heating
CIRCUITY = 1.2                # pipe / road routing factor on straight-line distance (Ballou et al. 2002, US roads ~1.2)
MIN_LAKE_M2 = 50_000          # lakes and reservoirs smaller than 5 ha are ignored for water intake
HDD_BASE_C = 18.0
Q_SPACE_KWH_M2_KD = 0.024     # space heat per m2 floor per heating degree day (team assumption, see docs)
Q_DHW_KWH_M2 = 10.0           # domestic hot water per m2 floor and year (team assumption)
STOREY_M = 3.5                # height per storey when only building height is known
CAMPUS_M2_PER_MW = 2500       # campus land per MW IT when no mapped footprint exists (team assumption)

# ESA WorldCover classes
WC_TREE, WC_SHRUB, WC_GRASS, WC_CROP, WC_BUILT, WC_BARE = 10, 20, 30, 40, 50, 60
OPEN_LAND = (WC_SHRUB, WC_GRASS, WC_CROP, WC_BARE)
SKIP_BUILDING_CLASSES = {"shed", "garage", "garages", "carport", "roof", "hut", "shelter", "kiosk",
                         "industrial", "warehouse", "data_center", "hangar", "parking", "storage_tank", "silo"}
# Unclassified footprints above this size are mostly warehouses or data halls with little space heating demand.
MAX_UNCLASSIFIED_FOOTPRINT_M2 = 5000

log = logging.getLogger("heatbeat.gis")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "heatbeat-hackathon-gis/0.1 (research, non-commercial)"


# --------------------------------------------------------------------------- helpers
def _cached_get(url: str, rel: str, timeout: int = 120) -> bytes:
    p = CACHE / rel
    if p.exists():
        return p.read_bytes()
    for attempt in range(5):
        try:
            r = SESSION.get(url, timeout=timeout)
            break
        except requests.ConnectionError:
            if attempt == 4:
                raise
            time.sleep(3 * (attempt + 1))
    r.raise_for_status()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(r.content)
    return r.content


def local_crs(lat: float, lon: float):
    from pyproj import CRS, Transformer
    crs = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m")
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return fwd, inv


def bbox_deg(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * max(0.1, math.cos(math.radians(lat))))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


# --------------------------------------------------------------------------- elevation
def _tile_xy(lat, lon, z):
    n = 2 ** z
    x = (np.asarray(lon) + 180.0) / 360.0 * n
    lr = np.radians(np.asarray(lat))
    y = (1.0 - np.log(np.tan(lr) + 1.0 / np.cos(lr)) / math.pi) / 2.0 * n
    return x, y


@lru_cache(maxsize=4096)
def _terrarium_tile(z: int, x: int, y: int) -> np.ndarray:
    from PIL import Image
    raw = _cached_get(TERRARIUM_URL.format(z=z, x=x, y=y), f"terrarium/{z}/{x}/{y}.png")
    a = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB")).astype(np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def elevation(lat, lon, z: int = DEM_ZOOM) -> np.ndarray:
    """Elevation in m (nearest pixel) for arrays of points."""
    fx, fy = _tile_xy(lat, lon, z)
    fx, fy = np.atleast_1d(fx), np.atleast_1d(fy)
    out = np.empty(fx.shape)
    tx, ty = np.floor(fx).astype(int), np.floor(fy).astype(int)
    px = np.clip(((fx - tx) * 256).astype(int), 0, 255)
    py = np.clip(((fy - ty) * 256).astype(int), 0, 255)
    for key in set(zip(tx.ravel(), ty.ravel())):
        m = (tx == key[0]) & (ty == key[1])
        out[m] = _terrarium_tile(z, key[0], key[1])[py[m], px[m]]
    return out


def slope_grid(lat0: float, lon0: float, radius_m: float, z: int = DEM_ZOOM):
    """Return a function slope(lat, lon) in degrees from a DEM mosaic around the site."""
    x0, y0, x1, y1 = bbox_deg(lat0, lon0, radius_m * 1.2)
    ax0, ay0 = _tile_xy(y1, x0, z)
    ax1, ay1 = _tile_xy(y0, x1, z)
    tx0, ty0, tx1, ty1 = int(ax0), int(ay0), int(ax1), int(ay1)
    rows = [np.hstack([_terrarium_tile(z, tx, ty) for tx in range(tx0, tx1 + 1)]) for ty in range(ty0, ty1 + 1)]
    dem = np.vstack(rows)
    pix_m = 156543.03392 / 2 ** z * math.cos(math.radians(lat0))
    gy, gx = np.gradient(dem, pix_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))

    def f(lat, lon):
        fx, fy = _tile_xy(lat, lon, z)
        c = np.clip(((fx - tx0) * 256).astype(int), 0, dem.shape[1] - 1)
        r = np.clip(((fy - ty0) * 256).astype(int), 0, dem.shape[0] - 1)
        return slope[r, c]
    return f


# --------------------------------------------------------------------------- land cover
def _wc_tile_name(lat: float, lon: float) -> str:
    la, lo = int(math.floor(lat / 3) * 3), int(math.floor(lon / 3) * 3)
    return f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"


def worldcover(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """ESA WorldCover class for arrays of points (windowed COG reads over HTTPS)."""
    import rasterio
    from rasterio.windows import from_bounds
    if os.getenv("HTTPS_PROXY") and not os.getenv("GDAL_HTTP_PROXY"):
        os.environ["GDAL_HTTP_PROXY"] = os.environ["HTTPS_PROXY"]
    out = np.zeros(lat.shape, dtype=np.uint8)
    names = np.array([_wc_tile_name(a, b) for a, b in zip(lat.ravel(), lon.ravel())]).reshape(lat.shape)
    for name in np.unique(names):
        m = names == name
        la, lo = lat[m], lon[m]
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            with rasterio.open("/vsicurl/" + WORLDCOVER_URL.format(tile=name)) as src:
                w = from_bounds(lo.min() - 1e-4, la.min() - 1e-4, lo.max() + 1e-4, la.max() + 1e-4, src.transform)
                w = w.round_offsets().round_lengths()
                a = src.read(1, window=w, boundless=True, fill_value=0)
                t = src.window_transform(w)
        c = np.clip(((lo - t.c) / t.a).astype(int), 0, a.shape[1] - 1)
        r = np.clip(((la - t.f) / t.e).astype(int), 0, a.shape[0] - 1)
        out[m] = a[r, c]
    return out


# --------------------------------------------------------------------------- overture
@lru_cache(maxsize=1)
def _s3():
    import pyarrow.fs as pafs
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    kw = {"proxy_options": proxy} if proxy else {}
    return pafs.S3FileSystem(anonymous=True, region="us-west-2", **kw)


@lru_cache(maxsize=16)
def _dataset(path: str):
    import pyarrow.dataset as ds
    return ds.dataset(OVERTURE_ROOT + path, filesystem=_s3(), format="parquet")


def overture(path: str, bbox: tuple[float, float, float, float], columns: list[str], extra=None) -> pd.DataFrame:
    """Features whose bbox intersects `bbox` (lon0, lat0, lon1, lat1). Cached as parquet."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    key = f"overture/{OVERTURE_RELEASE}/{path.replace('/', '_')}_{'_'.join(f'{v:.4f}' for v in bbox)}_{extra[0] if extra else ''}.parquet"
    p = CACHE / key
    if p.exists():
        return pq.read_table(p).to_pandas()
    x0, y0, x1, y1 = bbox
    f = ((pc.field("bbox", "xmax") >= x0) & (pc.field("bbox", "xmin") <= x1)
         & (pc.field("bbox", "ymax") >= y0) & (pc.field("bbox", "ymin") <= y1))
    if extra:
        f = f & extra[1]
    tb = _dataset(path).to_table(filter=f, columns=columns + ["geometry"])
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(tb, p)
    return tb.to_pandas()


def _geoms(df: pd.DataFrame, fwd):
    import shapely
    g = shapely.from_wkb(df["geometry"].to_numpy())
    return shapely.transform(g, lambda xy: np.column_stack(fwd.transform(xy[:, 0], xy[:, 1])))


def nearest(geoms, inv) -> tuple[float, float, float] | None:
    """Nearest geometry to the origin of the local CRS: (distance_m, lat, lon)."""
    import shapely
    if len(geoms) == 0:
        return None
    origin = shapely.Point(0, 0)
    d = shapely.distance(geoms, origin)
    i = int(np.argmin(d))
    x, y = shapely.get_coordinates(shapely.shortest_line(geoms[i], origin))[0]
    lon, lat = inv.transform(x, y)
    return float(d[i]), lat, lon


# --------------------------------------------------------------------------- coastline
@lru_cache(maxsize=1)
def _ne_coast():
    import shapely
    gj = json.loads(_cached_get(NE_COAST_URL, "naturalearth/ne_10m_coastline.geojson"))
    return [shapely.geometry.shape(f["geometry"]) for f in gj["features"]]


def ne_coast_distance(lat: float, lon: float, fwd, inv):
    import shapely
    cand = []
    for radius in (400_000, 1_500_000):
        box = shapely.box(*bbox_deg(lat, lon, radius))
        cand = [g for g in _ne_coast() if g.intersects(box)]
        if cand:
            break
    if not cand:
        return None
    proj = [shapely.transform(g, lambda xy: np.column_stack(fwd.transform(xy[:, 0], xy[:, 1]))) for g in cand]
    return nearest(np.array(proj, dtype=object), inv)


# --------------------------------------------------------------------------- heating degree days
@lru_cache(maxsize=1)
def _ghcn_stations() -> pd.DataFrame:
    inv = _cached_get(GHCN_URL + "ghcnd-inventory.txt", "ghcn/ghcnd-inventory.txt").decode()
    rows = [(l[0:11], float(l[12:20]), float(l[21:30]), l[31:35], int(l[36:40]), int(l[41:45]))
            for l in inv.splitlines() if l[31:35] in ("TMAX", "TMIN")]
    df = pd.DataFrame(rows, columns=["id", "lat", "lon", "el", "y0", "y1"])
    g = df.groupby("id").agg(lat=("lat", "first"), lon=("lon", "first"), n=("el", "nunique"),
                             y0=("y0", "max"), y1=("y1", "min"))
    stn = _cached_get(GHCN_URL + "ghcnd-stations.txt", "ghcn/ghcnd-stations.txt").decode()
    elev = {l[0:11]: float(l[31:37]) for l in stn.splitlines()}
    g = g[(g.n == 2) & (g.y1 >= 2020)].reset_index()
    g["elev_m"] = g.id.map(elev).where(lambda x: x > -999)
    return g


LAPSE_K_PER_M = 0.0065  # standard atmosphere lapse rate, corrects station temperature to site elevation


def hdd(lat: float, lon: float, site_elev_m: float = float("nan")) -> tuple[float, str, float]:
    """Mean annual heating degree days (base 18 C) 2015 to 2024 from the nearest usable GHCN station.

    Station daily mean temperature is shifted to the site elevation with the standard lapse rate.
    """
    st = _ghcn_stations()
    d = np.hypot((st.lat - lat) * 111.32, (st.lon - lon) * 111.32 * math.cos(math.radians(lat)))
    for i in np.argsort(d.to_numpy())[:25]:
        sid = st.id.iloc[i]
        try:
            raw = _cached_get(f"{GHCN_URL}csv/by_station/{sid}.csv", f"ghcn/{sid}.csv", timeout=300)
        except requests.HTTPError:
            continue
        df = pd.read_csv(io.BytesIO(raw), usecols=["DATE", "ELEMENT", "DATA_VALUE", "Q_FLAG"], dtype={"Q_FLAG": str})
        df = df[df.ELEMENT.isin(["TMAX", "TMIN"]) & df.Q_FLAG.isna() & (df.DATE >= 20150101) & (df.DATE <= 20241231)]
        t = df.pivot_table(index="DATE", columns="ELEMENT", values="DATA_VALUE").dropna()
        if len(t) < 1500:  # need at least about 4 of the 10 years
            continue
        tmean = (t.TMAX + t.TMIN) / 20.0
        st_el = st.elev_m.iloc[i]
        if not (math.isnan(site_elev_m) or pd.isna(st_el)):
            tmean = tmean + LAPSE_K_PER_M * (st_el - site_elev_m)
        val = float(np.clip(HDD_BASE_C - tmean, 0, None).sum() / len(t) * 365.25)
        return val, sid, float(d.iloc[i])
    return float("nan"), "", float("nan")


# --------------------------------------------------------------------------- per-site computation
def persson_werner_lin_density(e: np.ndarray, q_mwh_m2: float) -> np.ndarray:
    """Linear heat density Q/L = e * q * w with effective width w = 61.8 * e^-0.15 (Persson & Werner 2011)."""
    e = np.asarray(e, dtype=float)
    w = np.where(e > 0, 61.8 * np.power(np.maximum(e, 1e-6), -0.15), 0.0)
    return e * q_mwh_m2 * w


def compute_site(row: pd.Series, profiles: pd.DataFrame, dh: pd.DataFrame) -> dict:
    import pyarrow.compute as pc
    import shapely
    from scipy import ndimage

    lat, lon, sid = float(row.lat), float(row.lon), row.site_id
    fwd, inv = local_crs(lat, lon)
    prec = row.coord_precision
    loc_conf = {"building": "high", "campus_approx": "medium"}.get(prec, "low")
    out: dict = {"site_id": sid, "lat": lat, "lon": lon, "coord_precision": prec}

    # ---------- terrain and land cover on a 10 m grid
    n = int(LAND_RADIUS_M / GRID_M)
    ax = np.arange(-n, n + 1) * GRID_M
    gx, gy = np.meshgrid(ax, -ax)
    glon, glat = inv.transform(gx, gy)
    r = np.hypot(gx, gy)
    disk = r <= LAND_RADIUS_M
    slope_f = slope_grid(lat, lon, LAND_RADIUS_M)
    sl = slope_f(glat, glon)
    wc = worldcover(glat, glon)
    cell = GRID_M ** 2

    elev_site = float(elevation(lat, lon)[0])
    out["elev_m"] = round(elev_site, 1)
    out["slope_deg"] = round(float(sl[r <= SLOPE_RADIUS_M].mean()), 2)
    out["slope_deg_source"] = f"AWS Terrain Tiles z{DEM_ZOOM} DEM, mean slope within {SLOPE_RADIUS_M} m"
    out["slope_deg_confidence"] = "medium" if loc_conf != "low" else "low"

    def largest_patch(mask):
        lab, k = ndimage.label(mask & disk)
        if k == 0:
            return 0.0
        sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, k + 1))
        return float(sizes.max() * cell)

    flat = sl <= FLAT_SLOPE_DEG
    flat_open = flat & np.isin(wc, OPEN_LAND)
    agri = flat & (wc == WC_CROP)
    out["flat_land_m2"] = round(largest_patch(flat_open), -2)
    out["flat_land_total_m2"] = round(float((flat_open & disk).sum() * cell), -2)
    out["flat_land_m2_source"] = (f"Largest contiguous patch of open land (WorldCover shrub, grass, crop, bare) with slope <= "
                                  f"{FLAT_SLOPE_DEG} deg within {LAND_RADIUS_M} m; ESA WorldCover 2021 + DEM")
    out["flat_land_m2_confidence"] = "low"  # ownership and availability unknown
    out["agri_land_m2"] = round(largest_patch(agri), -2)
    out["agri_land_total_m2"] = round(float((agri & disk).sum() * cell), -2)
    out["agri_land_m2_source"] = (f"Largest contiguous WorldCover cropland patch with slope <= {FLAT_SLOPE_DEG} deg within "
                                  f"{LAND_RADIUS_M} m (pasture is WorldCover grassland and not counted)")
    out["agri_land_m2_confidence"] = "low"
    for k, v in {"tree": WC_TREE, "built": WC_BUILT, "grass": WC_GRASS, "crop": WC_CROP}.items():
        out[f"lc_{k}_share"] = round(float((wc[disk] == v).mean()), 3)

    # ---------- water: fresh water intake and marine
    wcols = ["subtype", "class", "is_salt", "is_intermittent"]
    fresh = marine = None
    for radius in (15_000, 60_000):
        wdf = overture("theme=base/type=water", bbox_deg(lat, lon, radius), wcols)
        if wdf.empty:
            continue
        g = _geoms(wdf, fwd)
        area = shapely.area(g)
        is_poly = np.isin(shapely.get_type_id(g), [3, 6])
        inter = wdf.is_intermittent.fillna(False).astype(bool).to_numpy()
        salt = wdf.subtype.eq("ocean").to_numpy()  # is_salt alone also marks inland salt lakes and ponds
        saline = wdf.is_salt.fillna(False).astype(bool).to_numpy()
        river_line = wdf.subtype.eq("river").to_numpy() & wdf["class"].eq("river").to_numpy() & ~is_poly
        big_water = (wdf.subtype.isin(["river", "lake", "reservoir", "water"]).to_numpy()
                     & ~wdf["class"].isin(["basin", "wastewater", "swimming_pool", "fountain"]).to_numpy()
                     & is_poly & (area >= MIN_LAKE_M2))
        fm = (river_line | big_water) & ~inter & ~salt & ~saline
        if fresh is None and fm.any():
            res = nearest(g[fm], inv)
            if res and res[0] <= radius:
                fresh = res
        if marine is None and salt.any():
            res = nearest(g[salt & is_poly] if (salt & is_poly).any() else g[salt], inv)
            if res and res[0] <= radius:
                marine = res
        if fresh is not None and marine is not None:
            break
    coast_src = "Overture Maps ocean polygons (OSM coastline)"
    if marine is None:
        marine = ne_coast_distance(lat, lon, fwd, inv)
        coast_src = "Natural Earth 10 m coastline (no OSM ocean polygon within 60 km)"
    if marine is not None:
        out["d_coast_line_m"] = round(marine[0])
        out["d_coast_m"] = round(marine[0] * CIRCUITY, -1)
        out["d_coast_m_source"] = f"{coast_src}; straight line x {CIRCUITY} routing factor; brackish aquifers not included"
        out["d_coast_m_confidence"] = "medium" if coast_src.startswith("Overture") else "low"
    out["dz_m"] = round(max(0.0, elev_site), 1)
    out["dz_m_source"] = "Site ground elevation above sea level (seawater intake at 0 m), AWS Terrain Tiles DEM"
    out["dz_m_confidence"] = "medium" if loc_conf != "low" else "low"

    cand = [c for c in (fresh, marine) if c is not None]
    if cand:
        best = min(cand, key=lambda c: c[0])
        kind = "fresh water (river, lake, reservoir)" if best is fresh else "sea water"
        out["d_water_line_m"] = round(best[0])
        out["d_water_m"] = round(best[0] * CIRCUITY, -1)
        out["d_water_kind"] = "fresh" if best is fresh else "marine"
        out["d_water_m_source"] = (f"Overture Maps water (OSM), nearest {kind}; rivers as mapped river lines, lakes >= "
                                   f"{MIN_LAKE_M2 / 1e4:.0f} ha, no intermittent water; straight line x {CIRCUITY}")
        out["d_water_m_confidence"] = "medium" if loc_conf != "low" else "low"
        out["water_elev_m"] = round(float(elevation(best[1], best[2])[0]), 1)
        out["dz_water_m"] = round(max(0.0, elev_site - out["water_elev_m"]), 1)
    if fresh is not None:
        out["d_freshwater_line_m"] = round(fresh[0])

    # ---------- industrial land use (zoning proxy)
    lu = overture("theme=base/type=land_use", bbox_deg(lat, lon, ZONING_RADIUS_M + 500), ["subtype", "class"])
    ind = lu[lu["class"].isin(["industrial", "construction", "brownfield"]) | lu.subtype.eq("developed") & lu["class"].eq("industrial")]
    d_ind = nearest(_geoms(ind, fwd), inv) if len(ind) else None
    out["d_industrial_landuse_m"] = round(d_ind[0]) if d_ind else None
    zr = 300 if prec == "building" else ZONING_RADIUS_M
    out["ind_zoning"] = int(bool(d_ind and d_ind[0] <= zr))
    out["ind_zoning_source"] = (f"Proxy: OSM landuse=industrial/construction/brownfield (Overture land_use) within "
                                f"{zr} m; not a legal zoning map")
    out["ind_zoning_confidence"] = "low"

    # ---------- buildings -> heat density and district heating
    h, st_id, st_km = hdd(lat, lon, elev_site)
    out["hdd18"] = None if math.isnan(h) else round(h)
    out["hdd18_station"] = st_id
    out["hdd18_station_km"] = round(st_km, 1)
    q_mwh_m2 = (Q_SPACE_KWH_M2_KD * h + Q_DHW_KWH_M2) / 1000 if not math.isnan(h) else float("nan")
    out["q_heat_kwh_m2"] = round(q_mwh_m2 * 1000, 1)

    bdf = overture("theme=buildings/type=building", bbox_deg(lat, lon, BUILDING_RADIUS_M),
                   ["class", "height", "num_floors", "is_underground"])
    bdf = bdf[~bdf["class"].isin(SKIP_BUILDING_CLASSES) & ~bdf.is_underground.fillna(False).astype(bool)]
    nc = int(BUILDING_RADIUS_M / CELL_M)
    fa_grid = np.zeros((2 * nc + 1, 2 * nc + 1))
    if len(bdf):
        g = _geoms(bdf, fwd)
        foot = shapely.area(g)
        keep = ~(bdf["class"].isna().to_numpy() & (foot > MAX_UNCLASSIFIED_FOOTPRINT_M2))
        bdf, g, foot = bdf[keep], g[keep], foot[keep]
        floors = bdf.num_floors.to_numpy(dtype=float)
        hgt = bdf.height.to_numpy(dtype=float)
        floors = np.where(np.isnan(floors), np.round(hgt / STOREY_M), floors)
        floors = np.where(np.isnan(floors) | (floors < 1), 1, floors)
        cen = shapely.centroid(g)
        cx, cy = shapely.get_x(cen), shapely.get_y(cen)
        ix = np.round(cx / CELL_M).astype(int) + nc
        iy = np.round(cy / CELL_M).astype(int) + nc
        ok = (ix >= 0) & (ix <= 2 * nc) & (iy >= 0) & (iy <= 2 * nc)
        np.add.at(fa_grid, (iy[ok], ix[ok]), (foot * floors)[ok])
        out["n_buildings_6km"] = int(len(bdf))
    e = ndimage.uniform_filter(fa_grid / CELL_M ** 2, size=3, mode="constant")  # plot ratio, 750 m smoothing
    qlin = persson_werner_lin_density(e, q_mwh_m2) if not math.isnan(q_mwh_m2) else np.zeros_like(e)
    cc = (np.arange(2 * nc + 1) - nc) * CELL_M
    cxg, cyg = np.meshgrid(cc, cc)
    cr = np.hypot(cxg, cyg)
    inside = cr <= BUILDING_RADIUS_M
    out["plot_ratio_site"] = round(float(e[nc, nc]), 3)
    dense = (qlin >= DH_LIN_MIN) & inside
    if dense.any():
        i = np.argmin(np.where(dense, cr, np.inf))
        d_dense = float(cr.flat[i])
        tgt = np.unravel_index(i, cr.shape)
        near_tgt = np.hypot(cxg - cxg[tgt], cyg - cyg[tgt]) <= 1000
        rho = float(qlin[near_tgt & dense].mean())
        dense_note = f"nearest {CELL_M} m cell with modelled linear heat density >= {DH_LIN_MIN} MWh/(m yr)"
    else:
        d_dense = float("nan")
        rho = float(qlin[inside].max()) if inside.any() else 0.0
        dense_note = f"no cell >= {DH_LIN_MIN} MWh/(m yr) within {BUILDING_RADIUS_M} m (value is a lower bound)"

    # known district heating systems
    dh_dist = []
    for s in dh.itertuples():
        dx, dy = fwd.transform(s.lon, s.lat)
        dh_dist.append((max(0.0, math.hypot(dx, dy) - s.service_radius_km * 1000), s))
    d_known, sys = min(dh_dist, key=lambda t: t[0]) if dh_dist else (float("inf"), None)
    # mapped heat pipelines (OSM man_made=pipeline + substance=heat/steam/hot_water)
    pipe = overture("theme=base/type=infrastructure", bbox_deg(lat, lon, DH_CONNECT_M + 1000), ["class", "source_tags"],
                    extra=("pipeline", pc.field("class") == "pipeline"))
    heat_pipe = None
    if len(pipe):
        subst = pipe.source_tags.map(lambda t: (dict(t) if t is not None else {}).get("substance", ""))
        hp = pipe[subst.isin(["heat", "hot_water", "steam"])]
        if len(hp):
            heat_pipe = nearest(_geoms(hp, fwd), inv)
    d_pipe = heat_pipe[0] if heat_pipe else float("inf")
    d_existing = min(d_known, d_pipe)
    out["d_known_dh_m"] = round(d_known) if math.isfinite(d_known) else None
    out["known_dh_system"] = sys.system_id if sys is not None and d_known <= 50_000 else ""
    out["d_osm_heat_pipe_m"] = round(d_pipe) if math.isfinite(d_pipe) else None
    out["has_existing_dh"] = int(d_existing <= DH_CONNECT_M)
    out["has_existing_dh_source"] = (f"1 if a curated DH system (district_heating_systems.csv, approximate service area) or an "
                                     f"OSM heat/steam pipeline is within {DH_CONNECT_M} m")
    out["has_existing_dh_confidence"] = "medium" if out["has_existing_dh"] else "low"

    opts = []
    if d_existing <= 50_000:
        opts.append((d_existing, "existing DH network (edge of approximate service area or mapped pipe)"))
    if not math.isnan(d_dense):
        opts.append((d_dense, dense_note))
    d_dh, how = min(opts, key=lambda t: t[0]) if opts else (float("inf"), "")
    if math.isfinite(d_dh):
        out["d_dh_m"] = round(d_dh * CIRCUITY, -1)
        out["d_dh_m_source"] = f"Min of: {how}; straight line x {CIRCUITY}. Heat density from Overture buildings"
    else:
        out["d_dh_m"] = round(BUILDING_RADIUS_M * CIRCUITY, -1)
        out["d_dh_m_source"] = f"Lower bound: {dense_note}; no known DH network within 50 km"
    out["d_dh_m_is_lower_bound"] = int(not math.isfinite(d_dh))
    out["d_dh_m_confidence"] = "low"
    out["rho_heat_mwh_m"] = round(rho, 2)
    out["rho_heat_mwh_m_source"] = (f"Persson & Werner (2011) Q/L = e*q*w, w = 61.8*e^-0.15; plot ratio e from Overture "
                                    f"building footprints x floors ({CELL_M} m cells, 750 m smoothing) at the d_dh target; "
                                    f"q = {Q_SPACE_KWH_M2_KD} kWh/(m2 K d) x HDD18 + {Q_DHW_KWH_M2} kWh/m2 (assumption)")
    out["rho_heat_mwh_m_confidence"] = "low"

    # ---------- campus area
    prof = profiles[profiles.site_id == sid]
    mw = float(prof.it_load_mw.iloc[0]) if len(prof) and pd.notna(prof.it_load_mw.iloc[0]) else float("nan")
    if not math.isnan(mw):
        out["campus_area_m2"] = round(mw * CAMPUS_M2_PER_MW, -3)
        out["campus_area_m2_source"] = (f"Synthetic: IT load {mw:g} MW (site_profiles.csv) x {CAMPUS_M2_PER_MW} m2/MW campus "
                                        "land incl. roads and yards (team assumption)")
    out["campus_area_m2_confidence"] = "synthetic"
    return out


FIELD_ORDER = ["d_coast_m", "d_water_m", "dz_m", "slope_deg", "flat_land_m2", "agri_land_m2", "campus_area_m2",
               "d_dh_m", "has_existing_dh", "rho_heat_mwh_m", "ind_zoning"]


RANKING_CSV = PIPELINE_DIR / "site_ranking_inputs_gis.csv"
DATASET_IDS = {
    "d_coast_m": "overture:base/water(ocean) or naturalearth:ne_10m_coastline",
    "d_water_m": "overture:base/water (OSM)",
    "dz_m": "aws:terrain-tiles (terrarium z13)",
    "slope_deg": "aws:terrain-tiles (terrarium z13)",
    "flat_land_m2": "esa:worldcover-2021-v200 + aws:terrain-tiles",
    "agri_land_m2": "esa:worldcover-2021-v200 + aws:terrain-tiles",
    "campus_area_m2": "data_pipeline/site_profiles.csv it_load_mw x team factor",
    "d_dh_m": "overture:buildings + data_pipeline/district_heating_systems.csv",
    "has_existing_dh": "data_pipeline/district_heating_systems.csv + overture:base/infrastructure",
    "rho_heat_mwh_m": "overture:buildings + noaa:ghcn-daily HDD + Persson & Werner 2011",
    "ind_zoning": "overture:base/land_use (OSM landuse)",
}


def export_ranking_inputs(df: pd.DataFrame, country: str = "US") -> None:
    """Long format for heatbeat_ranking: site_id,key,value,status,source,note (one row per site and key)."""
    sites = pd.read_csv(PIPELINE_DIR / "sites.csv")
    ids = set(sites.site_id[sites.country_iso2 == country])
    rows = []
    for r in df[df.site_id.isin(ids)].itertuples(index=False):
        r = r._asdict()
        for k in FIELD_ORDER:
            v = r.get(k)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            conf = r.get(f"{k}_confidence", "")
            note = f"confidence={conf}; {r.get(f'{k}_source', '')}"
            if k == "d_dh_m" and r.get("d_dh_m_is_lower_bound") == 1:
                note = "LOWER BOUND; " + note
            rows.append({"site_id": r["site_id"], "key": k, "value": v,
                         "status": "assumption" if conf == "synthetic" else "data",
                         "source": DATASET_IDS[k], "note": note})
    pd.DataFrame(rows).to_csv(RANKING_CSV, index=False)
    log.info("wrote %s (%d rows)", RANKING_CSV, len(rows))


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", help="comma-separated site_ids (default: all)")
    ap.add_argument("--country", help="only sites with this country_iso2, e.g. US")
    args = ap.parse_args(argv)
    sites = pd.read_csv(PIPELINE_DIR / "sites.csv")
    profiles = pd.read_csv(PIPELINE_DIR / "site_profiles.csv")
    dh = pd.read_csv(PIPELINE_DIR / "district_heating_systems.csv")
    if args.sites:
        sites = sites[sites.site_id.isin(args.sites.split(","))]
    if args.country:
        sites = sites[sites.country_iso2 == args.country]
    old = pd.read_csv(OUT_CSV) if OUT_CSV.exists() else pd.DataFrame(columns=["site_id"])
    rows = []
    for row in sites.itertuples(index=False):
        log.info("site %s", row.site_id)
        try:
            rows.append(compute_site(pd.Series(row._asdict()), profiles, dh))
        except Exception as exc:  # keep going, report at the end
            log.exception("failed %s: %s", row.site_id, exc)
    new = pd.DataFrame(rows)
    if new.empty:
        raise SystemExit("no site computed")
    df = pd.concat([old[~old.site_id.isin(new.site_id)], new], ignore_index=True) if len(new) else old
    order = pd.read_csv(PIPELINE_DIR / "sites.csv").site_id.tolist()
    df["_o"] = df.site_id.map({s: i for i, s in enumerate(order)})
    df = df.sort_values("_o").drop(columns="_o")
    lead = ["site_id", "lat", "lon", "coord_precision"]
    keys = [c for f in FIELD_ORDER for c in (f, f"{f}_source", f"{f}_confidence") if c in df.columns]
    rest = [c for c in df.columns if c not in lead + keys]
    df = df[lead + keys + rest]
    df.to_csv(OUT_CSV, index=False)
    export_ranking_inputs(df)
    log.info("wrote %s (%d rows, %d failed)", OUT_CSV, len(df), len(sites) - len(new))


if __name__ == "__main__":
    main()
