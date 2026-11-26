"""Command line pipeline check: run the live calls for a few sites and compare with the stored database.

    python -m demo.pipeline_check                         # default sample of sites
    python -m demo.pipeline_check --site il-haifa --nasa  # one site, with NASA POWER cross-check
    python -m demo.pipeline_check --lat 31.25 --lon 34.79 # any point (weather only)

Exit code 1 if any check fails, so it can run in CI.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

import heatbeat_data as hd
from data_pipeline.common import load_grid_regions, load_sites
from demo import checks as ck
from demo import live

DEFAULT_SITES = ["il-haifa", "us-ca-santa-clara", "de-frankfurt"]


def check_point(lat: float, lon: float, label: str, site_id: str | None, nasa: bool, price: bool) -> pd.DataFrame:
    log = live.CallLog()
    w_live = live.open_meteo_weather(lat, lon, log)
    live.elevation(lat, lon, log)
    w_nasa = live.nasa_power_weather(lat, lon, log) if nasa else None
    res = ck.weather_checks(w_live, "LIVE weather")
    if w_nasa is not None:
        res += ck.weather_checks(w_nasa, "NASA weather")
        res += ck.compare_weather(w_nasa, w_live, "NASA vs Open-Meteo", 2.0, independent=True)
    try:
        online = hd.meta().get("build_mode") == "online"
    except FileNotFoundError:
        online = False
        res.append(ck._row("stored database present", None, "not found, live checks only"))
    if site_id and online:
        s = hd.get_site(site_id, live=False)
        if not s.weather.empty:
            res += ck.weather_checks(s.weather, "DB weather")
            res += ck.compare_weather(w_live, s.weather, "LIVE vs DB weather", 0.2)
        res += ck.price_checks(s.prices)
        res += ck.grid_checks(s.grid)
        if price:
            r = load_grid_regions().set_index("grid_region_id").loc[s.meta["grid_region_id"]]
            if r["iso_rto"] in live.LIVE_PRICE_ISOS:
                res += ck.compare_prices(live.iso_prices_week(r["iso_rto"], r["lmp_location"], log), s.prices)
    if site_id:
        res += ck.heat_checks(hd.heat_profile(site_id))
    out = pd.DataFrame(res)
    out.insert(0, "site", label)
    calls = log.frame()[["name", "ok", "status", "seconds", "kbytes", "rows", "error"]]
    print(f"\n== {label} ({lat:.4f}, {lon:.4f})\n{calls.to_string(index=False)}\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", action="append", help="site_id (repeatable); default: a small sample")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--nasa", action="store_true", help="also call NASA POWER as an independent cross-check")
    ap.add_argument("--price", action="store_true", help="also fetch one week of ISO prices via gridstatus")
    a = ap.parse_args(argv)
    sites = load_sites().set_index("site_id")
    frames = []
    if a.lat is not None and a.lon is not None:
        frames.append(check_point(a.lat, a.lon, "custom", None, a.nasa, False))
    else:
        for sid in a.site or DEFAULT_SITES:
            r = sites.loc[sid]
            frames.append(check_point(float(r["lat"]), float(r["lon"]), sid, sid, a.nasa, a.price))
    res = pd.concat(frames, ignore_index=True)
    with pd.option_context("display.max_colwidth", 70, "display.width", 200):
        print(res.to_string(index=False))
    n = res["result"].value_counts()
    print(f"\n{n.get('pass', 0)} passed, {n.get('warn', 0)} warnings, {n.get('FAIL', 0)} failed")
    return 1 if n.get("FAIL", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
