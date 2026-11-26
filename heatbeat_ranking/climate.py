"""Ambient temperature series for the ranking model.

Two ways to get 8760 hourly dry bulb temperatures:

- `diurnal_from_daily`: the Excel method (sheet 2 + sheet 3 column D). A cosine between the daily
  minimum (04:00) and maximum (16:00). Kept so the Excel example can be reproduced exactly.
- `hourly_from_site`: real hourly 2024 weather from `heatbeat_data` (Open-Meteo ERA5). 2024 is a
  leap year, so 29 February is dropped to keep the Excel's 8760 hour thresholds comparable.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"


def diurnal_from_daily(t_min: np.ndarray, t_max: np.ndarray) -> np.ndarray:
    """T(d, h) = mean(d) - swing(d)/2 * cos(2 pi (h - 4) / 24), h = 0..23, as in the Excel."""
    t_min, t_max = np.asarray(t_min, float), np.asarray(t_max, float)
    if len(t_min) != 365 or len(t_max) != 365:
        raise ValueError("need 365 daily values")
    h = np.arange(24)
    mean = ((t_min + t_max) / 2)[:, None]
    swing = (t_max - t_min)[:, None]
    return (mean - swing / 2 * np.cos(2 * np.pi * (h - 4) / 24)).ravel()


def excel_example_t_amb() -> np.ndarray:
    df = pd.read_csv(DATA_DIR / "excel_example_daily_climate.csv")
    return diurnal_from_daily(df["t_min_c"].to_numpy(), df["t_max_c"].to_numpy())


def to_8760(series: pd.Series, tz: str | None = None) -> np.ndarray:
    """Hourly series (UTC index) to a local time array of 8760 values, 29 February removed."""
    s = series.copy()
    if tz:
        s.index = s.index.tz_convert(tz)
    s = s[~((s.index.month == 2) & (s.index.day == 29))]
    a = s.to_numpy(dtype=float)
    if len(a) < 8760:
        raise ValueError(f"only {len(a)} hours of weather, need a full year")
    a = a[:8760]
    if np.isnan(a).any():
        a = pd.Series(a).interpolate(limit_direction="both").to_numpy()
    return a


def hourly_from_site(site) -> np.ndarray:
    """Dry bulb temperature of a `heatbeat_data.Site` as 8760 local hours."""
    return to_8760(site.weather["t_db_c"], site.tz)


def daily_min_max(t_amb: np.ndarray) -> pd.DataFrame:
    """Daily min/max of an 8760 series (to compare the cosine method against real weather)."""
    d = t_amb.reshape(365, 24)
    return pd.DataFrame({"t_min_c": d.min(axis=1), "t_max_c": d.max(axis=1)})
