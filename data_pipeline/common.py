"""Shared paths, constants and helpers for the HEATBEAT data pipeline."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = ROOT / "data_pipeline"
DATA_DIR = Path(os.getenv("HEATBEAT_DATA_DIR", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
PARQUET_DIR = DATA_DIR / "parquet"
DB_PATH = DATA_DIR / "heatbeat.db"
REPORT_PATH = DATA_DIR / "build_report.json"

# Reference year for all hourly series (weather and prices are aligned on it).
YEAR = 2024

USER_AGENT = "heatbeat-hackathon-data-pipeline/0.1 (research, non-commercial)"

log = logging.getLogger("heatbeat")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def hourly_index(year: int = YEAR) -> pd.DatetimeIndex:
    """All hours of the reference year in UTC (8784 for 2024)."""
    return pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz="UTC", inclusive="left")


class RateLimited(RuntimeError):
    pass


class PermanentHTTPError(RuntimeError):
    pass


def http_get(url: str, *, params: dict | None = None, timeout: int = 120, retries: int = 4,
             backoff: float = 5.0) -> requests.Response:
    """GET with retries and exponential backoff (handles 429 and 5xx)."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if r.status_code == 429:
                raise RateLimited(f"HTTP 429: {r.text[:200]}")
            if r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:  # other client errors will not fix themselves
                raise PermanentHTTPError(f"HTTP {r.status_code} for {url}: {r.text[:200]}")
            return r
        except PermanentHTTPError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            wait = backoff * (2 ** attempt)
            if isinstance(exc, RateLimited):
                wait = max(wait, 65.0)  # Open-Meteo minutely limit resets after 60 s
            log.warning("GET %s failed (%s), retry %d/%d in %.0fs", url, exc, attempt + 1, retries, wait)
            time.sleep(wait)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_exc}")


def load_sites() -> pd.DataFrame:
    return pd.read_csv(PIPELINE_DIR / "sites.csv")


def load_grid_regions() -> pd.DataFrame:
    return pd.read_csv(PIPELINE_DIR / "grid_regions.csv")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str))


# IANA time zone per grid region, used for local time-of-day price shapes.
REGION_TZ = {
    "US-PJM-DOM": "America/New_York", "US-PJM-COMED": "America/Chicago", "US-PJM-AEP": "America/New_York",
    "US-PJM-PSEG": "America/New_York", "US-ERCOT-WEST": "America/Chicago", "US-ERCOT-NORTH": "America/Chicago",
    "US-ERCOT-SOUTH": "America/Chicago", "US-CAISO-NP15": "America/Los_Angeles",
    "US-CAISO-SP15": "America/Los_Angeles", "US-MISO-IA": "America/Chicago", "US-MISO-WI": "America/Chicago",
    "US-MISO-LA": "America/Chicago", "US-SPP-NE": "America/Chicago", "US-SPP-OK": "America/Chicago",
    "US-NYISO-NYC": "America/New_York", "US-ISONE-BOS": "America/New_York", "US-SE-GA": "America/New_York",
    "US-SE-NC": "America/New_York", "US-SE-SC": "America/New_York", "US-TVA-TN": "America/Chicago",
    "US-FL": "America/New_York", "US-AZ": "America/Phoenix", "US-NV-N": "America/Los_Angeles",
    "US-NV-S": "America/Los_Angeles", "US-NW-OR": "America/Los_Angeles", "US-NW-WA": "America/Los_Angeles",
    "US-UT": "America/Denver", "US-WY": "America/Denver",
    "IE": "Europe/Dublin", "DE": "Europe/Berlin", "NL": "Europe/Amsterdam", "GB": "Europe/London",
    "FR": "Europe/Paris", "SE": "Europe/Stockholm", "DK": "Europe/Copenhagen", "FI": "Europe/Helsinki",
    "SG": "Asia/Singapore", "JP": "Asia/Tokyo", "AU": "Australia/Sydney", "BR": "America/Sao_Paulo",
    "ZA": "Africa/Johannesburg", "IN": "Asia/Kolkata", "AE": "Asia/Dubai", "IL": "Asia/Jerusalem",
    # reference validation sites (data_pipeline/reference_sites.py)
    "NO": "Europe/Oslo", "US-SPP-ND": "America/Chicago", "US-NYISO-CENTRL": "America/New_York",
    "US-HI": "Pacific/Honolulu",
}
