"""Wind-driven passive radiator ("zero fan" heat rejection) for a hot closed liquid loop.

Question: a Vera Rubin class closed loop returns at 55 C and must be cooled back to 45 C. Can a flat,
wide finned radiator that turns face-on (90 degrees) to the wind reject a substantial part of that heat
with no fan power, and how much fan energy does that save against a conventional fan dry cooler?

Model per hour (all air side quantities per m2 of radiator face area):

    wind at the radiator     U = wind_10m * height_factor * cos(yaw_error)
    face velocity            v = U * through_flow_fraction(K)        porous screen in a free stream,
                                                                     Taylor & Davies: v/U = 1 / (1 + K/4)
    air capacity rate        C_air = rho_air * v * cp_air            kW/K per m2 face
    conductance              UA = UA_ref * (v / v_ref) ** n          air side film dominates, h ~ v^0.6
    effectiveness            cross flow, both fluids unmixed (Incropera eq. 11.33 approximation)
    passive heat             q_pas = eps * C_min * (T_ret - T_db)    capped at the load to bring the loop to T_sup

The passive panel sits in series ahead of the existing fan dry cooler. What the panel cannot reject in a
given hour (low wind, warm air) goes to the fan cooler, whose fan power follows the same cubic affinity
law as `heat_rejection.reject`. Saving = baseline fan MWh minus fan MWh with the panel in front.

Ignored, all conservative for the panel: natural draft (buoyancy) at zero wind, wind gusts above the
hourly mean. Ignored, optimistic for the panel: wake and blockage between panels in a large array,
yaw lag and the time the panel needs to turn, fouling. These are covered by the ranges in WIND_PARAMS
and the yaw / array factor.

Run:  python -m heatbeat_engineering.wind_radiator            (screen all US sites, case Mount Pleasant)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .heat_rejection import reject
from .params import defaults

T_SUP_C, T_RET_C = 45.0, 55.0  # Rubin hot water loop (NVIDIA: supply up to 45 C, exits chip at about 55 C)

# value, low, high, status, source
WIND_PARAMS = {
    "coil_k": (4.0, 2.0, 10.0, "assumption",
               "Pressure loss coefficient of a shallow, wide fin pitch coil (Delta p / (0.5 rho v^2)). Standard "
               "4 to 6 row dry cooler coils sit at 15 to 25; a 1 to 2 row coil with 4 to 5 mm fin pitch at 3 to 8. "
               "UNVERIFIED, needs a manufacturer selection"),
    "ua_ref_kw_km2": (2.5, 1.5, 4.0, "assumption",
                      "UA per m2 face at v_ref = 2 m/s for a 2 row finned coil (air side NTU about 1). Kays & London "
                      "compact heat exchanger correlations give that order. UNVERIFIED"),
    "ua_exp": (0.6, 0.5, 0.8, "literature", "Air side h ~ Re^0.5..0.8 on finned tubes (Incropera ch. 7)"),
    "height_factor": (1.0, 0.85, 1.15, "assumption",
                      "Wind at panel centre / wind at 10 m. Panel centre near 10 m gives 1.0; 6 m over open "
                      "terrain about 0.9 (log law, z0 = 0.03 m)"),
    "yaw_array_factor": (0.85, 0.6, 1.0, "assumption",
                         "Combined loss from yaw error, turn lag and wake / blockage between panels in an array. "
                         "1.0 = single panel always exactly face-on. UNVERIFIED, largest uncertainty"),
    "area_m2_per_mw": (40.0, 20.0, 80.0, "design choice", "Radiator face area per MW of loop heat"),
}
RHO_AIR, CP_AIR, V_REF = 1.2, 1.005, 2.0  # kg/m3, kJ/kg K, m/s


def wp(overrides: dict | None = None) -> dict:
    p = {k: v[0] for k, v in WIND_PARAMS.items()}
    p.update(overrides or {})
    return p


def eps_crossflow_unmixed(ntu, cr):
    ntu = np.maximum(ntu, 1e-9)
    cr = np.maximum(cr, 1e-9)
    return 1.0 - np.exp((1.0 / cr) * ntu ** 0.22 * (np.exp(-cr * ntu ** 0.78) - 1.0))


def passive_share(wind_ms, t_db, q_mw: float, p: dict) -> dict:
    """Hourly heat (MW) the panel rejects without fans for loop heat q_mw, T_RET -> T_SUP."""
    u = np.asarray(wind_ms, float) * p["height_factor"] * p["yaw_array_factor"]
    v = u / (1.0 + p["coil_k"] / 4.0)
    area = p["area_m2_per_mw"] * q_mw
    c_air = RHO_AIR * v * CP_AIR * area / 1000.0  # MW/K
    ua = p["ua_ref_kw_km2"] * np.power(np.maximum(v, 1e-6) / V_REF, p["ua_exp"]) * area / 1000.0
    c_w = q_mw / (T_RET_C - T_SUP_C)  # MW/K, loop flow fixed by design delta T
    c_min, c_max = np.minimum(c_air, c_w), np.maximum(c_air, c_w)
    eps = eps_crossflow_unmixed(ua / np.maximum(c_min, 1e-9), c_min / np.maximum(c_max, 1e-9))
    dt = np.clip(T_RET_C - np.asarray(t_db, float), 0, None)
    q_pas = np.minimum(eps * c_min * dt, q_mw)
    return {"q_passive_mw": q_pas, "face_v_ms": v, "area_m2": area}


def evaluate(weather: pd.DataFrame, q_mw: float, overrides: dict | None = None, P: dict | None = None) -> dict:
    """Annual result for one site: baseline fan dry cooler vs passive wind panel in front of it."""
    P = P or defaults()
    p = wp(overrides)
    w = weather
    base = reject("dry", q_mw, T_SUP_C, T_RET_C, w["t_db_c"].values, w["t_wb_c"].values, P)
    pas = passive_share(w["wind_ms"].values, w["t_db_c"].values, q_mw, p)
    rest = q_mw - pas["q_passive_mw"]
    # the fan cooler stays in place as backup, design point unchanged
    with_panel = reject("dry", rest, T_SUP_C, T_RET_C, w["t_db_c"].values, w["t_wb_c"].values, P,
                        q_design_mw=base["q_design_mw"])
    n = len(w)
    q_mwh = q_mw * n
    return {
        "q_mw": q_mw, "hours": n,
        "passive_heat_share": float(pas["q_passive_mw"].sum() / q_mwh),
        "hours_fully_passive": int((pas["q_passive_mw"] >= q_mw - 1e-9).sum()),
        "fan_mwh_base": base["fan_mwh"], "fan_mwh_with_panel": with_panel["fan_mwh"],
        "fan_saving_mwh": base["fan_mwh"] - with_panel["fan_mwh"],
        "fan_saving_share": 1 - with_panel["fan_mwh"] / max(base["fan_mwh"], 1e-9),
        "chiller_mwh_base": base["chiller_mwh"], "chiller_mwh_with_panel": with_panel["chiller_mwh"],
        "fan_mwh_base_flat": P["sfp_dry_kw_kw"] * q_mwh,
        "fan_mwh_flat_with_panel": P["sfp_dry_kw_kw"] * float(rest.sum()),
        "area_m2": pas["area_m2"],
        "_hourly": pd.DataFrame({"q_passive_mw": pas["q_passive_mw"], "face_v_ms": pas["face_v_ms"],
                                 "fan_base_mw": base["fan_mw"], "fan_panel_mw": with_panel["fan_mw"]},
                                index=w.index),
    }


def tornado(weather: pd.DataFrame, q_mw: float, metric: str = "passive_heat_share") -> pd.DataFrame:
    base = evaluate(weather, q_mw)[metric]
    rows = []
    for k, (_, lo, hi, *_r) in WIND_PARAMS.items():
        a = evaluate(weather, q_mw, {k: lo})[metric]
        b = evaluate(weather, q_mw, {k: hi})[metric]
        rows.append({"param": k, "low": lo, "high": hi, "at_low": a, "at_high": b, "swing": abs(b - a)})
    return pd.DataFrame(rows).sort_values("swing", ascending=False).assign(base=base)


def _weather(site_id: str) -> pd.DataFrame:
    w = pd.read_parquet("data/parquet/weather_hourly.parquet")
    w = w[w.site_id == site_id].set_index("ts_utc").sort_index()
    return w


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
    print("Screen, per MW of loop heat, 40 m2 face per MW:")
    print(df[["site_id", "wind_mean", "t_mean", "passive_heat_share", "hours_fully_passive",
              "fan_mwh_base", "fan_saving_share", "fan_mwh_base_flat"]].round(3).to_string(index=False))
    return df


if __name__ == "__main__":
    main()
