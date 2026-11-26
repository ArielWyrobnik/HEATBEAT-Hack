"""Wind radiator screen: passive, fan free heat rejection for a hot closed liquid loop.

The physics lives in `heat_rejection` (tech "wind": `wind_passive_mw` ahead of a fan dry cooler), the
parameters in `params.PARAMS` (keys wind_* and capex_wind_usd_m2), so the same model runs in the heat
chain optimizer, the API ranking and the tornado. This module only answers the standalone question
from docs/WIND_RADIATOR.md: for a Vera Rubin class loop (55 C back to 45 C), how much heat can the
panel reject with no fans at each site, and how much fan energy does that save against a dry cooler?

Run:  python -m heatbeat_engineering.wind_radiator            (screen all US sites per MW of loop heat)
"""
from __future__ import annotations

import pandas as pd

from .heat_rejection import reject
from .params import PARAMS, defaults

T_SUP_C, T_RET_C = 45.0, 55.0  # Rubin hot water loop (nvidia_45c_2026: supply up to 45 C, exits chip at about 55 C)
WIND_KEYS = [k for k in PARAMS if k.startswith("wind_")]


def evaluate(weather: pd.DataFrame, q_mw: float, overrides: dict | None = None, P: dict | None = None) -> dict:
    """Annual result for one site: fan dry cooler alone vs wind radiator in front of it."""
    P = {**(P or defaults()), **(overrides or {})}
    t_db, t_wb, wind = weather["t_db_c"].values, weather["t_wb_c"].values, weather["wind_ms"].values
    base = reject("dry", q_mw, T_SUP_C, T_RET_C, t_db, t_wb, P)
    wr = reject("wind", q_mw, T_SUP_C, T_RET_C, t_db, t_wb, P, q_design_mw=base["q_design_mw"], wind_ms=wind)
    q_mwh = q_mw * len(weather)
    rest = q_mw - wr["passive_mw"]
    return {
        "q_mw": q_mw, "hours": len(weather),
        "passive_heat_share": wr["passive_mwh"] / q_mwh,
        "hours_fully_passive": int((wr["passive_mw"] >= q_mw - 1e-9).sum()),
        "fan_mwh_base": base["fan_mwh"], "fan_mwh_with_panel": wr["fan_mwh"],
        "fan_saving_mwh": base["fan_mwh"] - wr["fan_mwh"],
        "fan_saving_share": 1 - wr["fan_mwh"] / max(base["fan_mwh"], 1e-9),
        "fan_mwh_base_flat": P["sfp_dry_kw_kw"] * q_mwh,
        "fan_mwh_flat_with_panel": P["sfp_dry_kw_kw"] * float(rest.sum()),
        "area_m2": wr["wind_area_m2"],
        "_hourly": pd.DataFrame({"q_passive_mw": wr["passive_mw"], "fan_base_mw": base["fan_mw"],
                                 "fan_panel_mw": wr["fan_mw"]}, index=weather.index),
    }


def tornado(weather: pd.DataFrame, q_mw: float, metric: str = "passive_heat_share") -> pd.DataFrame:
    base = evaluate(weather, q_mw)[metric]
    rows = []
    for k in WIND_KEYS:
        p = PARAMS[k]
        a, b = evaluate(weather, q_mw, {k: p.low})[metric], evaluate(weather, q_mw, {k: p.high})[metric]
        rows.append({"param": k, "low": p.low, "high": p.high, "at_low": a, "at_high": b, "swing": abs(b - a)})
    return pd.DataFrame(rows).sort_values("swing", ascending=False).assign(base=base)


def main():
    sites = pd.read_parquet("data/parquet/sites.parquet").set_index("site_id")
    w_all = pd.read_parquet("data/parquet/weather_hourly.parquet")
    rows = []
    for sid, w in w_all.groupby("site_id"):
        if sites.loc[sid, "country_iso2"] != "US":
            continue
        r = evaluate(w.set_index("ts_utc").sort_index(), 1.0)
        rows.append({"site_id": sid, "wind_mean": w.wind_ms.mean(), "t_mean": w.t_db_c.mean(),
                     **{k: v for k, v in r.items() if not k.startswith("_")}})
    df = pd.DataFrame(rows).sort_values("passive_heat_share", ascending=False)
    pd.set_option("display.width", 200)
    print(f"Screen per MW of loop heat, {defaults()['wind_area_m2_per_mw']:.0f} m2 face per MW:")
    print(df[["site_id", "wind_mean", "t_mean", "passive_heat_share", "hours_fully_passive",
              "fan_mwh_base", "fan_saving_share", "fan_mwh_base_flat"]].round(3).to_string(index=False))
    return df


if __name__ == "__main__":
    main()
