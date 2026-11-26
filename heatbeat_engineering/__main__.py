"""Command line:

    python -m heatbeat_engineering us-ia-council-bluffs-google          # one database site
    python -m heatbeat_engineering --plan 41.6 -93.6 1000 dlc_hot       # planned 1 GW site
    python -m heatbeat_engineering --all                                 # all US sites -> results CSV
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from . import best_per_use, evaluate

COLS = ["rank", "chain", "npv_usd", "reuse_npv_usd", "net_value_usd_yr", "delta_capex_usd", "payback_yr", "heat_delivered_mwh",
        "co2_avoided_t_yr", "water_saved_m3_yr", "pue", "wue_l_kwh", "ere"]
OUT = Path(__file__).resolve().parent / "results" / "us_sites.csv"


def all_sites(live: bool = False) -> pd.DataFrame:
    import heatbeat_data as hd
    rows = []
    for sid in hd.list_sites().query("country_iso2 == 'US'")["site_id"]:
        df, base, res, case = evaluate(site_id=sid, live=live, greenfield=None)
        best, reuse = df.iloc[0], df[df["uses"] != "none"].iloc[0]
        rows.append({
            "site_id": sid, "cooling_profile": case.cooling_profile, "it_mw": case.it_mw,
            "baseline_rejection": case.baseline_rejection, "baseline_pue": round(base["pue"], 3),
            "baseline_wue_l_kwh": round(base["wue_l_kwh"], 2), "weather": case.prov["weather"]["source"],
            "best_chain": best["chain"], "best_npv_musd": round(best["npv_usd"] / 1e6, 2),
            "best_payback_yr": None if pd.isna(best["payback_yr"]) else round(best["payback_yr"], 1),
            "best_water_saved_m3_yr": round(best["water_saved_m3_yr"]), "best_co2_avoided_t_yr": round(best["co2_avoided_t_yr"]),
            "best_reuse_chain": reuse["chain"], "best_reuse_npv_musd": round(reuse["npv_usd"] / 1e6, 2),
            "best_reuse_heat_mwh_yr": round(reuse["heat_delivered_mwh"]),
            "best_reuse_own_npv_musd": round(reuse["reuse_npv_usd"] / 1e6, 2),
            "ko_uses": "; ".join(f"{k}: {v}" for k, v in df.attrs["ko"].items()),
            "max_balance_residual_mwh": float(df["balance_residual_mwh"].abs().max()),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site_id", nargs="?")
    ap.add_argument("--plan", nargs=4, metavar=("LAT", "LON", "IT_MW", "COOLING_PROFILE"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--offline", action="store_true", help="never fetch weather live")
    a = ap.parse_args()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 90)
    if a.all:
        d = all_sites(live=not a.offline)
        OUT.parent.mkdir(exist_ok=True)
        d.to_csv(OUT, index=False)
        print(d[["site_id", "best_chain", "best_npv_musd", "best_reuse_chain", "best_reuse_npv_musd"]].to_string())
        print(f"written {OUT}")
        return
    if a.plan:
        lat, lon, mw, prof = a.plan
        df, base, res, case = evaluate(float(lat), float(lon), float(mw), prof, live=not a.offline)
    else:
        df, base, res, case = evaluate(site_id=a.site_id, live=not a.offline, greenfield=None)
    print(case.name, "|", case.cooling_profile, "| baseline", case.baseline_rejection,
          f"PUE {base['pue']:.3f} WUE {base['wue_l_kwh']:.2f} L/kWh")
    print("Best per heat use:")
    print(best_per_use(df)[COLS].to_string(index=False))
    print("Not feasible here:", df.attrs["ko"])


if __name__ == "__main__":
    main()
