"""Pipeline checks and provenance labels for the demo (no Streamlit here, so it is testable)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_pipeline.common import hourly_index

# Provenance categories shown as badges
REAL, DERIVED, ESTIMATED, SYNTHETIC, USER = "real", "derived", "estimated", "synthetic", "user input"

_REAL_SOURCES = {"open_meteo_era5", "nasa_power", "eia_avgprice_annual", "ember_yearly_global",
                 "epa_egrid2023_rev2", "iec_taoz_2023"}


def source_kind(source_id: str | None, is_synthetic: int | bool | None = None) -> str:
    """Map a source id (and synthetic flag) from the database to a provenance category."""
    if source_id is None or (isinstance(source_id, float) and np.isnan(source_id)):
        return SYNTHETIC if is_synthetic else ESTIMATED
    s = str(source_id)
    if s.startswith("synthetic") or (is_synthetic and s != "estimate_unverified"):
        return SYNTHETIC
    if s == "estimate_unverified":
        return ESTIMATED
    if s in _REAL_SOURCES or "gridstatus" in s or s.startswith("ercot"):
        return REAL
    return ESTIMATED


def heat_kind(evidence: str | None, is_assumed: bool | None) -> str:
    if evidence == "reported" and not is_assumed:
        return REAL
    if evidence == "derived":
        return DERIVED
    return ESTIMATED


def _row(check: str, ok: bool | str | None, detail: str) -> dict:
    """ok: True -> pass, False -> FAIL, "warn" -> warn (works, but the data is not real), None -> info."""
    res = "info" if ok is None else ("warn" if ok == "warn" else ("pass" if ok else "FAIL"))
    return {"check": check, "result": res, "detail": detail}


def weather_checks(df: pd.DataFrame | None, label: str) -> list[dict]:
    if df is None or df.empty:
        return [_row(f"{label}: data present", False, "no weather rows")]
    expected = len(hourly_index())
    nan = int(df[["t_db_c", "rh_pct"]].isna().any(axis=1).sum())
    t = df["t_db_c"]
    return [
        _row(f"{label}: hours", len(df) == expected, f"{len(df)} of {expected}"),
        _row(f"{label}: gaps", nan == 0, f"{nan} hours with missing temperature or humidity"),
        _row(f"{label}: temperature range", bool(t.min() > -60 and t.max() < 60),
             f"{t.min():.1f} to {t.max():.1f} C"),
        _row(f"{label}: humidity range", bool(df["rh_pct"].between(0, 100.5).all()),
             f"{df['rh_pct'].min():.0f} to {df['rh_pct'].max():.0f} %"),
        _row(f"{label}: wet bulb <= dry bulb", bool((df["t_wb_c"] <= df["t_db_c"] + 0.5).all()),
             "Stull (2011) approximation, 0.5 C tolerance"),
        _row(f"{label}: no frozen sensor", bool(t.diff().abs().rolling(48).sum().min() > 0),
             "no 48 h window with a constant temperature"),
    ]


def price_checks(df: pd.DataFrame | None) -> list[dict]:
    if df is None or df.empty:
        return [_row("prices: data present", False, "no price rows")]
    expected = len(hourly_index())
    p = df["price_usd_mwh"]
    syn = float(df["is_synthetic"].mean())
    neg = int((p < 0).sum())
    return [
        _row("prices: hours", len(df) == expected, f"{len(df)} of {expected}"),
        _row("prices: gaps", int(p.isna().sum()) == 0, f"{int(p.isna().sum())} missing hours"),
        _row("prices: plausible level", bool(-500 < p.min() and p.max() < 5000 and 5 < p.mean() < 500),
             f"mean {p.mean():.1f}, min {p.min():.1f}, max {p.max():.1f} USD/MWh"),
        _row("prices: negative hours", None, f"{neg} hours below zero (normal in some wholesale markets)"),
        _row("prices: real share", True if syn == 0 else "warn", f"{(1 - syn):.0%} of hours real, {syn:.0%} synthetic"),
    ]


def grid_checks(grid: dict) -> list[dict]:
    co2, retail = grid.get("co2_kg_mwh"), grid.get("retail_industrial_usd_mwh")
    return [
        _row("carbon intensity present", co2 is not None and not pd.isna(co2), f"{co2:.0f} kg/MWh" if co2 is not None and not pd.isna(co2) else "missing"),
        _row("carbon intensity plausible", co2 is not None and 0 <= co2 <= 1200, "0 to 1200 kg/MWh"),
        _row("retail price present", retail is not None and not pd.isna(retail), f"{retail:.1f} USD/MWh" if retail is not None and not pd.isna(retail) else "missing"),
    ]


def heat_checks(hp: dict | None) -> list[dict]:
    if not hp:
        return [_row("heat profile present", False, "no row in site_profiles.csv")]
    sup, ret = hp.get("facility_supply_temp_c"), hp.get("facility_return_temp_c")
    share = hp.get("liquid_heat_share")
    lo, mid, hi = hp.get("it_load_mw_low"), hp.get("it_load_mw"), hp.get("it_load_mw_high")
    return [
        _row("heat profile present", True, hp.get("cooling_profile_id", "")),
        _row("IT load range ordered", None if None in (lo, mid, hi) else lo <= mid <= hi, f"{lo} / {mid} / {hi} MW"),
        _row("supply < return temperature", None if sup is None or ret is None else sup < ret,
             f"{sup} C in, {ret} C out" if sup is not None else "no facility water loop (outside air)"),
        _row("liquid heat share in 0..1", share is not None and 0 <= share <= 1, f"{share}"),
        _row("PUE plausible", 1.0 <= (hp.get("pue_assumed") or 0) <= 2.5, f"{hp.get('pue_assumed')}"),
    ]


def compare_weather(a: pd.DataFrame | None, b: pd.DataFrame | None, label: str, tol_c: float,
                    independent: bool = False) -> list[dict]:
    """Hour by hour comparison of two temperature series.

    Same source (live call versus stored database): any difference above tol_c is a pipeline FAIL.
    Independent sources (NASA POWER versus Open-Meteo, different reanalyses and grids): a difference
    above tol_c is only a warning, since it reflects the data products, not a broken pipeline.
    """
    if a is None or b is None or a.empty or b.empty:
        return [_row(f"{label}", None, "one side missing")]
    j = pd.concat([a["t_db_c"].rename("a"), b["t_db_c"].rename("b")], axis=1).dropna()
    if j.empty:
        return [_row(f"{label}", False, "no overlapping hours")]
    mae = float((j["a"] - j["b"]).abs().mean())
    r = float(j["a"].corr(j["b"]))
    bias = float((j["a"] - j["b"]).mean())
    miss = "warn" if independent else False
    out = [_row(f"{label}: mean abs difference (hourly)", True if mae <= tol_c else miss,
                f"{mae:.2f} C over {len(j)} h (tolerance {tol_c} C)"),
           _row(f"{label}: correlation", r > 0.9, f"r = {r:.3f}")]
    if independent:
        d = j.resample("D").mean()
        out.append(_row(f"{label}: annual mean bias", abs(bias) <= 1.5 or "warn",
                        f"{bias:+.2f} C; daily mean abs difference {float((d['a'] - d['b']).abs().mean()):.2f} C"))
    return out


def compare_prices(live: pd.Series | None, stored: pd.DataFrame | None) -> list[dict]:
    if live is None or stored is None or stored.empty:
        return [_row("live vs stored prices", None, "one side missing")]
    j = pd.concat([live.rename("a"), stored["price_usd_mwh"].rename("b")], axis=1).dropna()
    if j.empty:
        return [_row("live vs stored prices", False, "no overlapping hours")]
    mae = float((j["a"] - j["b"]).abs().mean())
    return [_row("live vs stored prices: mean abs difference", mae < 1.0, f"{mae:.2f} USD/MWh over {len(j)} h")]
