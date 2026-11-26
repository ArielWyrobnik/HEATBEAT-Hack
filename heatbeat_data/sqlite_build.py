"""Build the SQLite database from the committed Parquet tables (no network needed)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE sites (
    site_id TEXT PRIMARY KEY, name TEXT, operator TEXT, city TEXT, region TEXT, country_iso2 TEXT,
    lat REAL, lon REAL, coord_precision TEXT, capacity_mw REAL, capacity_note TEXT,
    grid_region_id TEXT REFERENCES grid_regions(grid_region_id), is_hypothetical INTEGER, notes TEXT
);
CREATE TABLE grid_regions (
    grid_region_id TEXT PRIMARY KEY, name TEXT, country_iso2 TEXT, country_iso3 TEXT, us_state TEXT,
    iso_rto TEXT, lmp_location TEXT, egrid_subregion TEXT, notes TEXT,
    retail_industrial_usd_mwh REAL, retail_commercial_usd_mwh REAL, retail_price_year INTEGER,
    retail_price_source TEXT REFERENCES sources(source_id), retail_price_is_synthetic INTEGER,
    co2_kg_mwh REAL, co2_year INTEGER, co2_source TEXT REFERENCES sources(source_id), co2_is_synthetic INTEGER,
    hourly_price_kind TEXT
);
CREATE TABLE weather_hourly (
    site_id TEXT REFERENCES sites(site_id), ts_utc TEXT, t_db_c REAL, rh_pct REAL, t_dew_c REAL,
    t_wb_c REAL, wind_ms REAL, ghi_wm2 REAL, source TEXT REFERENCES sources(source_id),
    PRIMARY KEY (site_id, ts_utc)
) WITHOUT ROWID;
CREATE TABLE price_hourly (
    grid_region_id TEXT REFERENCES grid_regions(grid_region_id), ts_utc TEXT, price_usd_mwh REAL,
    price_kind TEXT, is_synthetic INTEGER, source TEXT REFERENCES sources(source_id),
    PRIMARY KEY (grid_region_id, ts_utc)
) WITHOUT ROWID;
CREATE TABLE sources (source_id TEXT PRIMARY KEY, name TEXT, url TEXT, licence TEXT, is_synthetic INTEGER, notes TEXT);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

ORDER = ["sources", "grid_regions", "sites", "weather_hourly", "price_hourly", "meta"]


def build_sqlite(parquet_dir: Path | str, db_path: Path | str) -> Path:
    parquet_dir, db_path = Path(parquet_dir), Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    with sqlite3.connect(tmp) as con:
        con.executescript(SCHEMA)
        for name in ORDER:
            df = pd.read_parquet(parquet_dir / f"{name}.parquet")
            if "ts_utc" in df.columns:
                df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            df.to_sql(name, con, if_exists="append", index=False, chunksize=50_000)
        con.execute("CREATE INDEX idx_sites_region ON sites(grid_region_id)")
    with sqlite3.connect(tmp) as con:
        con.execute("VACUUM")
    tmp.replace(db_path)
    return db_path
