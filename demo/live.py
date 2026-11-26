"""Live API calls for the demo. Only APIs that need no key.

Every call is recorded in a CallLog (endpoint, parameters, HTTP status, duration, size, rows),
so the demo can show exactly what went over the wire and whether it worked.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
import requests

from data_pipeline.common import USER_AGENT, YEAR, hourly_index
from data_pipeline.fetch_weather import COLUMNS as WEATHER_COLS, NASA_POWER_URL, OPEN_METEO_URL, stull_wet_bulb

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
LIVE_PRICE_ISOS = ("CAISO", "MISO", "NYISO", "ISONE", "SPP")  # gridstatus, no key, fast enough for one week


@dataclass
class Call:
    name: str
    url: str
    params: dict
    full_url: str = ""
    ok: bool = False
    status: int | None = None
    seconds: float = 0.0
    kbytes: float = 0.0
    rows: int = 0
    error: str = ""


@dataclass
class CallLog:
    calls: list[Call] = field(default_factory=list)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(c) for c in self.calls])


def _get(log: CallLog, name: str, url: str, params: dict, timeout: int = 90) -> dict | None:
    c = Call(name=name, url=url, params=params, full_url=requests.Request("GET", url, params=params).prepare().url)
    t0 = time.perf_counter()
    try:
        r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
        c.status, c.kbytes = r.status_code, round(len(r.content) / 1024, 1)
        r.raise_for_status()
        c.ok = True
        return r.json()
    except Exception as exc:  # noqa: BLE001
        c.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return None
    finally:
        c.seconds = round(time.perf_counter() - t0, 2)
        log.calls.append(c)


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reindex(hourly_index())
    df["t_wb_c"] = stull_wet_bulb(df["t_db_c"].to_numpy(), df["rh_pct"].to_numpy())
    return df[WEATHER_COLS]


def open_meteo_weather(lat: float, lon: float, log: CallLog) -> pd.DataFrame | None:
    """Hourly weather for the reference year, same request as data_pipeline.fetch_weather."""
    params = {"latitude": lat, "longitude": lon, "start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31",
              "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m,shortwave_radiation",
              "wind_speed_unit": "ms", "timezone": "UTC"}
    j = _get(log, "Open-Meteo archive (hourly weather)", OPEN_METEO_URL, params)
    if j is None:
        return None
    h = j["hourly"]
    df = pd.DataFrame({"t_db_c": h["temperature_2m"], "rh_pct": h["relative_humidity_2m"],
                       "t_dew_c": h["dew_point_2m"], "wind_ms": h["wind_speed_10m"],
                       "ghi_wm2": h["shortwave_radiation"]},
                      index=pd.to_datetime(h["time"]).tz_localize("UTC")).astype(float)
    log.calls[-1].rows = len(df)
    df = _finish(df)
    df.attrs["grid_elevation_m"] = j.get("elevation")
    df.attrs["grid_lat"], df.attrs["grid_lon"] = j.get("latitude"), j.get("longitude")
    return df


def elevation(lat: float, lon: float, log: CallLog) -> float | None:
    j = _get(log, "Open-Meteo elevation", ELEVATION_URL, {"latitude": lat, "longitude": lon}, timeout=30)
    if j and j.get("elevation"):
        log.calls[-1].rows = 1
        return float(j["elevation"][0])
    return None


def nasa_power_weather(lat: float, lon: float, log: CallLog) -> pd.DataFrame | None:
    """Independent second source (MERRA-2 based), used as a cross-check. Slower (often 20 to 60 s)."""
    params = {"parameters": "T2M,RH2M,T2MDEW,WS10M,ALLSKY_SFC_SW_DWN", "community": "RE",
              "latitude": lat, "longitude": lon, "start": f"{YEAR}0101", "end": f"{YEAR}1231",
              "format": "JSON", "time-standard": "UTC"}
    j = _get(log, "NASA POWER (hourly weather, cross-check)", NASA_POWER_URL, params, timeout=300)
    if j is None:
        return None
    p = j["properties"]["parameter"]
    idx = pd.to_datetime(list(p["T2M"].keys()), format="%Y%m%d%H").tz_localize("UTC")
    df = pd.DataFrame({"t_db_c": list(p["T2M"].values()), "rh_pct": list(p["RH2M"].values()),
                       "t_dew_c": list(p["T2MDEW"].values()), "wind_ms": list(p["WS10M"].values()),
                       "ghi_wm2": list(p["ALLSKY_SFC_SW_DWN"].values())}, index=idx).astype(float).replace(-999.0, np.nan)
    log.calls[-1].rows = len(df)
    return _finish(df)


def iso_prices_week(iso: str, location: str, log: CallLog) -> pd.Series | None:
    """One week (1 to 8 January of the reference year) of day-ahead hourly LMP via gridstatus.

    Only a spot check that the price feed works and matches the stored data, not a full year.
    """
    from data_pipeline.fetch_prices import _fetch_iso_month, _iso_client, _match

    start, end = pd.Timestamp(f"{YEAR}-01-01"), pd.Timestamp(f"{YEAR}-01-08")
    c = Call(name=f"gridstatus {iso} day-ahead LMP (1 week)", url=f"gridstatus.{iso}",
             params={"location": location, "start": str(start.date()), "end": str(end.date())})
    t0 = time.perf_counter()
    try:
        raw = _fetch_iso_month(_iso_client(iso), iso, start, end, [location])
        s = _match(raw, location)
        c.ok, c.rows = len(s) > 0, len(s)
        if not c.ok:
            c.error = f"no rows for location {location!r}"
        return s if c.ok else None
    except Exception as exc:  # noqa: BLE001
        c.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return None
    finally:
        c.seconds = round(time.perf_counter() - t0, 2)
        log.calls.append(c)
