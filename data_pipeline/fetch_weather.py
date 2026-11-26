"""Hourly weather per site for the reference year.

Primary source: Open-Meteo Historical Weather API (ERA5 reanalysis), CC BY 4.0.
Fallback source: NASA POWER hourly point API (MERRA-2 based), public domain.
Offline mode produces a clearly flagged synthetic series for pipeline testing only.

Wet bulb temperature is derived from dry bulb and relative humidity with the
Stull (2011) empirical formula, so it is consistent across both sources.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .common import CACHE_DIR, YEAR, hourly_index, http_get, log

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"

COLUMNS = ["t_db_c", "rh_pct", "t_dew_c", "t_wb_c", "wind_ms", "ghi_wm2"]


def stull_wet_bulb(t_c: np.ndarray, rh_pct: np.ndarray) -> np.ndarray:
    """Stull (2011), J. Appl. Meteor. Climatol. 50, 2267-2269. Valid for RH 5-99 %, T -20 to 50 C, ~1 C error."""
    rh = np.clip(rh_pct, 5, 99)
    return (t_c * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
            + np.arctan(t_c + rh) - np.arctan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh) - 4.686035)


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reindex(hourly_index())
    df = df.interpolate(limit=6, limit_direction="both")
    df["t_wb_c"] = stull_wet_bulb(df["t_db_c"].to_numpy(), df["rh_pct"].to_numpy())
    return df[COLUMNS]


def fetch_open_meteo(lat: float, lon: float) -> pd.DataFrame:
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31",
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m,shortwave_radiation",
        "wind_speed_unit": "ms", "timezone": "UTC",
    }
    j = http_get(OPEN_METEO_URL, params=params).json()
    h = j["hourly"]
    df = pd.DataFrame({
        "t_db_c": h["temperature_2m"], "rh_pct": h["relative_humidity_2m"], "t_dew_c": h["dew_point_2m"],
        "wind_ms": h["wind_speed_10m"], "ghi_wm2": h["shortwave_radiation"],
    }, index=pd.to_datetime(h["time"]).tz_localize("UTC"))
    return _finish(df.astype(float))


def fetch_nasa_power(lat: float, lon: float) -> pd.DataFrame:
    params = {
        "parameters": "T2M,RH2M,T2MDEW,WS10M,ALLSKY_SFC_SW_DWN", "community": "RE",
        "latitude": lat, "longitude": lon, "start": f"{YEAR}0101", "end": f"{YEAR}1231",
        "format": "JSON", "time-standard": "UTC",
    }
    p = http_get(NASA_POWER_URL, params=params, timeout=300).json()["properties"]["parameter"]
    idx = pd.to_datetime(list(p["T2M"].keys()), format="%Y%m%d%H").tz_localize("UTC")
    df = pd.DataFrame({
        "t_db_c": list(p["T2M"].values()), "rh_pct": list(p["RH2M"].values()),
        "t_dew_c": list(p["T2MDEW"].values()), "wind_ms": list(p["WS10M"].values()),
        "ghi_wm2": list(p["ALLSKY_SFC_SW_DWN"].values()),
    }, index=idx).astype(float).replace(-999.0, np.nan)
    return _finish(df)


def synthetic_weather(lat: float, lon: float, seed: int) -> pd.DataFrame:
    """Simple sinusoidal climate, ONLY for offline pipeline tests. Never use for analysis."""
    idx = hourly_index()
    rng = np.random.default_rng(seed)
    doy = idx.dayofyear.to_numpy()
    local_hour = (idx.hour.to_numpy() + lon / 15.0) % 24
    sign = 1 if lat >= 0 else -1
    mean = 28 - 0.45 * abs(lat)
    seasonal = sign * (2 + 0.25 * abs(lat)) * -np.cos(2 * np.pi * (doy - 15) / 366)
    diurnal = 5 * np.cos(2 * np.pi * (local_hour - 15) / 24)
    t = mean + seasonal + diurnal + rng.normal(0, 1.5, len(idx))
    rh = np.clip(65 - 2.0 * diurnal + rng.normal(0, 8, len(idx)), 5, 100)
    a, b = 17.62, 243.12
    gamma = np.log(rh / 100) + a * t / (b + t)
    dew = b * gamma / (a - gamma)
    df = pd.DataFrame({"t_db_c": t, "rh_pct": rh, "t_dew_c": dew,
                       "wind_ms": np.abs(rng.normal(4, 2, len(idx))),
                       "ghi_wm2": np.clip(800 * np.cos(2 * np.pi * (local_hour - 12) / 24), 0, None)}, index=idx)
    return _finish(df)


def get_weather(sites: pd.DataFrame, offline: bool = False, pause_s: float = 2.0) -> tuple[pd.DataFrame, dict]:
    """Return long table (site_id, ts_utc, columns..., source) and a per-site status dict.

    Real results are cached in data/cache/weather/<site_id>.parquet so reruns only fetch missing sites.
    """
    cache = CACHE_DIR / "weather"
    cache.mkdir(parents=True, exist_ok=True)
    frames, status = [], {}
    for i, s in enumerate(sites.itertuples()):
        path = cache / f"{s.site_id}.parquet"
        df, source = None, None
        if path.exists() and not offline:
            df = pd.read_parquet(path)
            source = df.pop("source").iloc[0]
        elif offline:
            df, source = synthetic_weather(s.lat, s.lon, seed=i), "synthetic_offline"
        else:
            for name, fn in (("open_meteo_era5", fetch_open_meteo), ("nasa_power", fetch_nasa_power)):
                try:
                    df, source = fn(s.lat, s.lon), name
                    break
                except Exception as exc:  # noqa: BLE001
                    log.warning("weather %s via %s failed: %s", s.site_id, name, exc)
            if df is None:
                status[s.site_id] = "missing"
                continue
            out = df.copy()
            out["source"] = source
            out.to_parquet(path)
            time.sleep(pause_s)
        log.info("weather %s: %s (%d h, mean %.1f C)", s.site_id, source, len(df), df["t_db_c"].mean())
        status[s.site_id] = source
        df = df.rename_axis("ts_utc").reset_index()
        df.insert(0, "site_id", s.site_id)
        df["source"] = source
        frames.append(df)
    return pd.concat(frames, ignore_index=True), status
