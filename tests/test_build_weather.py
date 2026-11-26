"""A build whose cache has no weather must keep the stored weather (regression: run 45819015536)."""
import pandas as pd

from data_pipeline import build_db


def test_missing_weather_is_kept_from_previous_build(tmp_path, monkeypatch):
    ts = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    prev = pd.DataFrame({"site_id": ["a"] * 3 + ["b"] * 3, "ts_utc": list(ts) * 2, "t_db_c": range(6),
                         "source": ["open_meteo_era5"] * 6})
    prev.to_parquet(tmp_path / "weather_hourly.parquet", index=False)
    monkeypatch.setattr(build_db, "PARQUET_DIR", tmp_path)

    status = {"a": "missing", "b": "missing"}
    out = build_db._keep_previous_weather(prev.iloc[:0], status)
    assert len(out) == 6
    assert status["a"].startswith("kept_from_previous_build")

    fresh = prev[prev["site_id"] == "b"].assign(t_db_c=99.0)
    status = {"a": "missing", "b": "open_meteo_era5"}
    out = build_db._keep_previous_weather(fresh, status)
    assert sorted(out["site_id"].unique()) == ["a", "b"]
    assert (out.loc[out["site_id"] == "b", "t_db_c"] == 99.0).all()
