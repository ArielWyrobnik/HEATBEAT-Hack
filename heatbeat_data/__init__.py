"""Read-only access to the HEATBEAT location database.

The committed source of truth is data/parquet/*.parquet. On first use the module builds
data/heatbeat.db (SQLite, git-ignored) from it, so SQL users can query that file directly.

Typical use by a solution model:

    import heatbeat_data as hd

    hd.list_sites()                      # DataFrame of all sites (for the map)
    site = hd.get_site("us-va-ashburn-equinix")
    site.meta                            # dict: name, lat, lon, capacity_mw, grid region, ...
    site.grid                            # dict: retail price, CO2 intensity, flags, sources
    site.weather                         # hourly DataFrame (UTC index): t_db_c, rh_pct, t_dew_c, t_wb_c, wind_ms, ghi_wm2
    site.prices                          # hourly DataFrame (UTC index): price_usd_mwh, price_kind, is_synthetic
    site.summary()                       # dict of annual indicators (free-cooling hours, mean price, ...)

All timestamps are UTC, hour-beginning. Use `site.local(df)` to convert to the site's local time.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

__all__ = ["Site", "get_site", "list_sites", "list_grid_regions", "sources", "meta", "connect", "DB_PATH", "PARQUET_DIR"]

_DATA = Path(os.getenv("HEATBEAT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DB_PATH = Path(os.getenv("HEATBEAT_DB", _DATA / "heatbeat.db"))
PARQUET_DIR = _DATA / "parquet"

_TZ = None  # filled lazily from data_pipeline.common.REGION_TZ


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    if not p.exists():
        if not (PARQUET_DIR / "sites.parquet").exists():
            raise FileNotFoundError(f"{p} and {PARQUET_DIR} not found. Pull the repo data or run "
                                    "`python -m data_pipeline.build_db`.")
        from .sqlite_build import build_sqlite
        build_sqlite(PARQUET_DIR, p)  # first use: build SQLite from the committed Parquet files
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def _q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query(sql, con, params=params)


@lru_cache(maxsize=1)
def list_sites() -> pd.DataFrame:
    """All sites joined with their grid region headline numbers."""
    return _q("""
        SELECT s.*, g.name AS grid_region_name, g.iso_rto, g.retail_industrial_usd_mwh, g.co2_kg_mwh,
               g.hourly_price_kind
        FROM sites s JOIN grid_regions g USING (grid_region_id) ORDER BY s.site_id""")


def list_grid_regions() -> pd.DataFrame:
    return _q("SELECT * FROM grid_regions ORDER BY grid_region_id")


def sources() -> pd.DataFrame:
    return _q("SELECT * FROM sources ORDER BY source_id")


def meta() -> dict:
    return dict(_q("SELECT key, value FROM meta").values)


def _hourly(table: str, key: str, value: str) -> pd.DataFrame:
    df = _q(f"SELECT * FROM {table} WHERE {key} = ? ORDER BY ts_utc", (value,))
    df.index = pd.to_datetime(df.pop("ts_utc"), utc=True)
    df.index.name = "ts_utc"
    return df.drop(columns=[key])


@dataclass
class Site:
    meta: dict
    grid: dict
    weather: pd.DataFrame = field(repr=False)
    prices: pd.DataFrame = field(repr=False)

    @property
    def site_id(self) -> str:
        return self.meta["site_id"]

    @property
    def tz(self) -> str:
        global _TZ
        if _TZ is None:
            from data_pipeline.common import REGION_TZ
            _TZ = REGION_TZ
        return _TZ[self.meta["grid_region_id"]]

    def local(self, df: pd.DataFrame) -> pd.DataFrame:
        """Copy of an hourly frame with the index converted to the site's local time zone."""
        out = df.copy()
        out.index = out.index.tz_convert(self.tz)
        return out

    def hourly(self) -> pd.DataFrame:
        """Weather and price side by side on one UTC index (convenient for models)."""
        return self.weather.join(self.prices[["price_usd_mwh", "is_synthetic"]].rename(
            columns={"is_synthetic": "price_is_synthetic"}), how="left")

    def summary(self, free_cooling_wb_c: float = 18.0, free_cooling_db_c: float = 24.0) -> dict:
        """Annual indicators. Thresholds are simple defaults; models should apply their own."""
        w, p = self.weather, self.prices["price_usd_mwh"]
        loc_p = self.local(self.prices)
        by_hour = loc_p.groupby(loc_p.index.hour)["price_usd_mwh"].mean()
        monthly_t = self.local(w).groupby(lambda t: t.month)["t_db_c"].mean()
        out = {
            "site_id": self.site_id,
            "hours": len(w),
            "t_db_mean_c": round(w["t_db_c"].mean(), 2),
            "t_db_min_c": round(w["t_db_c"].min(), 2),
            "t_db_max_c": round(w["t_db_c"].max(), 2),
            "t_wb_p99_c": round(w["t_wb_c"].quantile(0.99), 2),
            "hours_wb_below_free_cooling": int((w["t_wb_c"] < free_cooling_wb_c).sum()),
            "hours_db_below_air_economizer": int((w["t_db_c"] < free_cooling_db_c).sum()),
            "heating_degree_hours_18c": round(float((18 - w["t_db_c"]).clip(lower=0).sum()), 0),
            "cooling_degree_hours_18c": round(float((w["t_db_c"] - 18).clip(lower=0).sum()), 0),
            "wind_mean_ms": round(w["wind_ms"].mean(), 2),
            "warmest_month": int(monthly_t.idxmax()),
            "coldest_month": int(monthly_t.idxmin()),
            "price_mean_usd_mwh": round(p.mean(), 2),
            "price_p10_usd_mwh": round(p.quantile(0.10), 2),
            "price_p90_usd_mwh": round(p.quantile(0.90), 2),
            "price_peak_local_hour": int(by_hour.idxmax()),
            "price_is_synthetic_share": round(float(self.prices["is_synthetic"].mean()), 3),
            "price_kind": self.prices["price_kind"].iloc[0] if len(self.prices) else None,
            "retail_industrial_usd_mwh": self.grid.get("retail_industrial_usd_mwh"),
            "co2_kg_mwh": self.grid.get("co2_kg_mwh"),
        }
        return {k: (v.item() if hasattr(v, "item") else v) for k, v in out.items()}


def _weather(site_id: str, lat: float, lon: float, live: bool) -> pd.DataFrame:
    """Stored weather if the database has the full year, else the local cache, else a live fetch.

    A live fetch (Open-Meteo, fallback NASA POWER) needs internet and is cached in
    data/cache/weather/<site_id>.parquet, so it happens once per site and machine.
    """
    w = _hourly("weather_hourly", "site_id", site_id)
    if len(w) >= 8760:
        return w
    from data_pipeline.common import CACHE_DIR  # same paths as the pipeline
    path = CACHE_DIR / "weather" / f"{site_id}.parquet"
    if path.exists():
        df = pd.read_parquet(path)
    elif live:
        from data_pipeline.fetch_weather import fetch_nasa_power, fetch_open_meteo
        df = None
        for name, fn in (("open_meteo_era5", fetch_open_meteo), ("nasa_power", fetch_nasa_power)):
            try:
                df = fn(lat, lon)
                df["source"] = name
                break
            except Exception:  # noqa: BLE001
                continue
        if df is None:
            raise RuntimeError(f"weather for {site_id} is not stored and the live fetch failed (internet?)")
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
    else:
        return w
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "ts_utc"
    return df


def get_site(site_id: str, live: bool = True) -> Site:
    """Load one site. With live=True, weather missing from the database is fetched once and cached."""
    s = _q("SELECT * FROM sites WHERE site_id = ?", (site_id,))
    if s.empty:
        raise KeyError(f"unknown site_id {site_id!r}; see list_sites()")
    m = s.iloc[0].to_dict()
    g = _q("SELECT * FROM grid_regions WHERE grid_region_id = ?", (m["grid_region_id"],)).iloc[0].to_dict()
    return Site(meta=m, grid=g, weather=_weather(site_id, m["lat"], m["lon"], live),
                prices=_hourly("price_hourly", "grid_region_id", m["grid_region_id"]))


# Heat source data per site (IT load, cooling, chips, coolant temperatures). Reads CSVs, no DB needed.
from .heat_profiles import cooling_profiles, heat_profile, heat_sources, site_heat_profiles  # noqa: E402

__all__ += ["cooling_profiles", "heat_profile", "heat_sources", "site_heat_profiles"]
Site.heat_profile = lambda self: heat_profile(self.site_id)
