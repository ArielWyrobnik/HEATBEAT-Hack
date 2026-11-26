"""Hourly electricity price series per grid region for the reference year.

Three kinds of series, recorded in price_hourly.price_kind:
  wholesale_da_lmp   Real day-ahead hourly LMP / settlement point price at a hub or zone,
                     from the ISO's public data via the open-source `gridstatus` library.
  retail_tou         Israel: IEC time-of-use (TAOZ) tariff applied hour by hour (real tariff,
                     calendar application is ours, holidays ignored).
  synthetic_shape    Annual average retail price times a synthetic diurnal and seasonal shape
                     (mean 1.0). Used where no public hourly price exists. ALWAYS is_synthetic = 1.
"""
from __future__ import annotations

import os
from collections import defaultdict

import numpy as np
import pandas as pd

from .common import CACHE_DIR, REGION_TZ, YEAR, hourly_index, log

MIN_COVERAGE = 0.90  # share of hours that must be real to accept an ISO series

# ---------------------------------------------------------------------------
# Israel: IEC Time of Use tariff, applicable as of 1 April 2023 (excl. VAT), agorot/kWh.
# Source: IEC "Time of Use Tariff" English PDF (see sources table, id iec_taoz_2023).
# The PDF lists two energy-rate columns per row; we use the LOWER column, which we read
# as the high-voltage rate. That column mapping is UNVERIFIED (text extraction lost headers).
# ---------------------------------------------------------------------------
IEC_TAOZ_AGOROT = {
    "summer": {"peak": 126.48, "off": 30.10},   # Jun-Sep
    "winter": {"peak": 82.14, "off": 25.89},    # Dec-Feb
    "transition": {"peak": 29.06, "off": 25.18},  # Mar-May, Oct-Nov
}
ILS_PER_USD = 3.70  # approximate 2024 average; UNVERIFIED, documented in sources table


def _israel_tou(idx: pd.DatetimeIndex) -> pd.Series:
    local = idx.tz_convert("Asia/Jerusalem")
    m, h, dow = local.month, local.hour, local.dayofweek  # Monday=0 ... Sunday=6
    season = np.where(np.isin(m, [6, 7, 8, 9]), "summer", np.where(np.isin(m, [12, 1, 2]), "winter", "transition"))
    workday = np.isin(dow, [6, 0, 1, 2, 3])  # Sunday to Thursday
    is_peak = np.where(
        season == "summer", workday & (h >= 17) & (h < 23),
        np.where(season == "winter", (h >= 17) & (h < 22), workday & (h >= 17) & (h < 22)))
    agorot = np.array([IEC_TAOZ_AGOROT[s]["peak" if p else "off"] for s, p in zip(season, is_peak)])
    usd_mwh = agorot / 100 * 1000 / ILS_PER_USD
    return pd.Series(usd_mwh, index=idx)


def synthetic_shape(idx: pd.DatetimeIndex, tz: str, southern: bool = False) -> np.ndarray:
    """Diurnal and seasonal multiplier with annual mean 1.0. Purely synthetic, documented in docs/DATA.md.

    Shape: night trough, small morning ramp, evening peak (17-21 local), stronger in summer
    (cooling load) and slightly stronger in winter (heating / lighting).
    """
    local = idx.tz_convert(tz)
    h = local.hour.to_numpy()
    m = local.month.to_numpy()
    if southern:
        m = (m + 5) % 12 + 1
    diurnal = (0.80
               + 0.15 * np.exp(-((h - 8) ** 2) / 4.0)
               + 0.55 * np.exp(-((h - 19) ** 2) / 5.0)
               + 0.10 * ((h >= 9) & (h <= 16)))
    season_amp = np.where(np.isin(m, [6, 7, 8, 9]), 1.25, np.where(np.isin(m, [12, 1, 2]), 1.08, 0.95))
    weekend = local.dayofweek.to_numpy() >= 5
    shape = 1 + (diurnal - 1) * season_amp
    shape = shape * np.where(weekend, 0.92, 1.0) * season_amp ** 0.3
    return shape / shape.mean()


# ---------------------------------------------------------------------------
# ISO day-ahead hourly prices via gridstatus
# ---------------------------------------------------------------------------

def _iso_client(iso: str):
    import gridstatus
    cls = {"CAISO": gridstatus.CAISO, "ERCOT": gridstatus.Ercot, "MISO": gridstatus.MISO, "NYISO": gridstatus.NYISO,
           "ISONE": gridstatus.ISONE, "SPP": gridstatus.SPP, "PJM": gridstatus.PJM}[iso]
    if iso == "PJM" and not os.getenv("PJM_API_KEY"):
        raise RuntimeError("PJM_API_KEY not set (free key from https://dataminer2.pjm.com)")
    return cls()


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    ts_col = next(c for c in ("Interval Start", "Time") if c in df.columns)
    price_col = next(c for c in ("LMP", "SPP") if c in df.columns)
    out = pd.DataFrame({"ts": pd.to_datetime(df[ts_col], utc=True), "location": df["Location"].astype(str),
                        "price": pd.to_numeric(df[price_col], errors="coerce")})
    return out


def _fetch_iso_month(client, iso: str, start: pd.Timestamp, end: pd.Timestamp, locations: list[str]) -> pd.DataFrame:
    fn = getattr(client, "get_lmp_day_ahead_hourly", None)
    attempts = []
    if fn is not None:
        attempts += [lambda: fn(date=start, end=end, locations=locations), lambda: fn(date=start, end=end)]
    attempts += [lambda: client.get_lmp(date=start, end=end, market="DAY_AHEAD_HOURLY", locations=locations)]
    last = None
    for a in attempts:
        try:
            return _normalise(a())
        except TypeError as exc:  # signature mismatch, try the next form
            last = exc
    raise RuntimeError(f"{iso}: no working call form ({last})")


def _match(df: pd.DataFrame, location: str) -> pd.Series:
    loc_u = df["location"].str.upper()
    sel = df[loc_u == location.upper()]
    if sel.empty:
        sel = df[loc_u.str.contains(location.upper(), regex=False)]
    return sel.groupby("ts")["price"].mean()


def fetch_iso_prices(iso: str, locations: list[str]) -> tuple[dict[str, pd.Series], str]:
    client = _iso_client(iso)
    if iso == "ERCOT":
        raw = _normalise(client.get_dam_spp(YEAR))
        return {loc: _match(raw, loc) for loc in locations}, "ercot_dam_spp_historical"
    parts: dict[str, list[pd.Series]] = defaultdict(list)
    months = pd.date_range(f"{YEAR}-01-01", periods=13, freq="MS")
    for start, end in zip(months[:-1], months[1:]):
        try:
            raw = _fetch_iso_month(client, iso, start, end, locations)
            for loc in locations:
                parts[loc].append(_match(raw, loc))
            log.info("prices %s %s: %d rows", iso, start.strftime("%Y-%m"), len(raw))
        except Exception as exc:  # noqa: BLE001
            log.warning("prices %s %s failed: %s", iso, start.strftime("%Y-%m"), exc)
    return {loc: pd.concat(s) if s else pd.Series(dtype=float) for loc, s in parts.items()}, "gridstatus_da_hourly"


def prefetch_iso(regions: pd.DataFrame, iso: str) -> dict:
    """Fetch one ISO's hub series for the reference year and cache each region that meets MIN_COVERAGE."""
    idx = hourly_index()
    cache = CACHE_DIR / "prices"
    cache.mkdir(parents=True, exist_ok=True)
    grp = regions[regions["iso_rto"] == iso]
    todo = [r for r in grp.itertuples() if not (cache / f"{r.grid_region_id}.parquet").exists()]
    status: dict[str, dict] = {r.grid_region_id: {"kind": "wholesale_da_lmp", "cached": True}
                               for r in grp.itertuples() if r not in todo}
    if not todo:
        return status
    try:
        fetched, how = fetch_iso_prices(iso, sorted({r.lmp_location for r in todo}))
    except Exception as exc:  # noqa: BLE001
        log.warning("prices %s unavailable: %s", iso, exc)
        return {r.grid_region_id: {"kind": "fallback_synthetic", "error": str(exc)[:300]} for r in todo}
    for r in todo:
        s = fetched.get(r.lmp_location, pd.Series(dtype=float))
        s = s[~s.index.duplicated()].reindex(idx) if len(s) else pd.Series(np.nan, index=idx)
        coverage = float(s.notna().mean())
        log.info("prices %s (%s %s): coverage %.1f%%", r.grid_region_id, iso, r.lmp_location, 100 * coverage)
        if coverage >= MIN_COVERAGE:
            filled = s.isna().to_numpy().astype(int)
            s = s.interpolate(limit_direction="both")
            pd.DataFrame({"price_usd_mwh": s, "is_synthetic": filled, "source": f"{iso.lower()}_{how}"}).to_parquet(
                cache / f"{r.grid_region_id}.parquet")
            status[r.grid_region_id] = {"kind": "wholesale_da_lmp", "coverage": round(coverage, 4)}
        else:
            status[r.grid_region_id] = {"kind": "fallback_synthetic", "coverage": round(coverage, 4)}
    return status


def get_prices(regions: pd.DataFrame, retail: dict[str, float], offline: bool = False,
               fetch: bool = True) -> tuple[pd.DataFrame, dict]:
    """Return long price table and per-region status.

    Real ISO series come from data/cache/prices (filled by prefetch_iso; with fetch=True missing ISOs are
    fetched here). `retail` maps grid_region_id to annual average retail price (USD/MWh) used to scale
    synthetic shapes where no real hourly series is cached.
    """
    idx = hourly_index()
    cache = CACHE_DIR / "prices"
    status: dict[str, dict] = {}
    if fetch and not offline:
        for iso in sorted(regions["iso_rto"].dropna().unique()):
            status.update(prefetch_iso(regions, iso))

    rows = []
    for r in regions.itertuples():
        gid = r.grid_region_id
        path = cache / f"{gid}.parquet"
        if not offline and isinstance(r.iso_rto, str) and path.exists():
            df = pd.read_parquet(path)
            s, synth, src, kind = df["price_usd_mwh"], df["is_synthetic"].to_numpy(), df["source"].iloc[0], "wholesale_da_lmp"
            status[gid] = {"kind": kind, "coverage": round(float(1 - synth.mean()), 4)}
        elif gid == "IL":
            s, synth, src, kind = _israel_tou(idx), np.zeros(len(idx), int), "iec_taoz_2023", "retail_tou"
            status[gid] = {"kind": kind}
        else:
            base = retail.get(gid)
            if base is None or not np.isfinite(base):
                status[gid] = {"kind": "missing"}
                continue
            shape = synthetic_shape(idx, REGION_TZ[gid], southern=r.country_iso2 in ("AU", "BR", "ZA"))
            s, synth, src, kind = pd.Series(base * shape, index=idx), np.ones(len(idx), int), "synthetic_shape", "synthetic_shape"
            prev = status.get(gid, {})
            status[gid] = {**prev, "kind": kind}
        rows.append(pd.DataFrame({"grid_region_id": gid, "ts_utc": idx, "price_usd_mwh": np.asarray(s, float),
                                  "price_kind": kind, "is_synthetic": synth, "source": src}))
    return pd.concat(rows, ignore_index=True), status
