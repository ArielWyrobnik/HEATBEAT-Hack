"""Offline tests for the demo: response parsing, call logging and pipeline checks (no network)."""
import numpy as np
import pandas as pd

from data_pipeline.common import hourly_index
from demo import checks as ck
from demo import live


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.content = payload, status, b"x" * 2048

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _open_meteo_payload():
    idx = hourly_index()
    n = len(idx)
    t = 20 + 5 * np.sin(np.arange(n) * 2 * np.pi / 24)
    return {"latitude": 32.0, "longitude": 34.8, "elevation": 30.0, "hourly": {
        "time": idx.strftime("%Y-%m-%dT%H:%M").tolist(), "temperature_2m": t.tolist(),
        "relative_humidity_2m": [60.0] * n, "dew_point_2m": (t - 8).tolist(),
        "wind_speed_10m": [3.0] * n, "shortwave_radiation": [100.0] * n}}


def test_open_meteo_parsing_and_log(monkeypatch):
    monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resp(_open_meteo_payload()))
    log = live.CallLog()
    df = live.open_meteo_weather(32.0, 34.8, log)
    assert len(df) == len(hourly_index())
    assert (df["t_wb_c"] <= df["t_db_c"] + 0.5).all()
    c = log.calls[0]
    assert c.ok and c.status == 200 and c.rows == len(df) and "latitude=32.0" in c.full_url
    assert all(r["result"] == "pass" for r in ck.weather_checks(df, "live"))
    assert ck.compare_weather(df, df, "same", 0.2)[0]["result"] == "pass"


def test_failed_call_is_logged(monkeypatch):
    monkeypatch.setattr(live.requests, "get", lambda *a, **k: _Resp({}, status=403))
    log = live.CallLog()
    assert live.open_meteo_weather(0, 0, log) is None
    assert not log.calls[0].ok and "403" in log.calls[0].error
    assert ck.weather_checks(None, "live")[0]["result"] == "FAIL"


def test_gap_detected():
    idx = hourly_index()
    df = pd.DataFrame({"t_db_c": 10.0 + np.random.default_rng(0).normal(size=len(idx)), "rh_pct": 50.0,
                       "t_wb_c": 5.0}, index=idx)
    df.iloc[:10, 0] = np.nan
    res = {r["check"]: r["result"] for r in ck.weather_checks(df, "x")}
    assert res["x: gaps"] == "FAIL"


def test_synthetic_prices_warn():
    idx = hourly_index()
    p = pd.DataFrame({"price_usd_mwh": 80.0, "is_synthetic": 1, "price_kind": "synthetic_shape"}, index=idx)
    res = {r["check"]: r["result"] for r in ck.price_checks(p)}
    assert res["prices: real share"] == "warn" and res["prices: hours"] == "pass"


def test_source_kind():
    assert ck.source_kind("open_meteo_era5") == ck.REAL
    assert ck.source_kind("synthetic_shape", 1) == ck.SYNTHETIC
    assert ck.source_kind("estimate_unverified", 1) == ck.ESTIMATED
    assert ck.source_kind("caiso_gridstatus_da_hourly", 0) == ck.REAL


def test_independent_source_difference_is_warning():
    idx = hourly_index()
    a = pd.DataFrame({"t_db_c": 15 + 8 * np.sin(np.arange(len(idx)) * 2 * np.pi / 24)}, index=idx)
    b = a + 3.0
    same = {r["check"]: r["result"] for r in ck.compare_weather(a, b, "s", 0.2)}
    ind = {r["check"]: r["result"] for r in ck.compare_weather(a, b, "i", 2.0, independent=True)}
    assert same["s: mean abs difference (hourly)"] == "FAIL"
    assert ind["i: mean abs difference (hourly)"] == "warn" and ind["i: annual mean bias"] == "warn"
