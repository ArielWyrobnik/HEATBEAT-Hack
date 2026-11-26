"""python -m heatbeat_ranking <site_id> [--mode excel|corrected] [--greenfield 0|1] [--weather hourly|daily_cosine]
python -m heatbeat_ranking --excel-example   (reproduce the team Excel)
"""
import argparse

import pandas as pd

from . import evaluate, excel_example_inputs, excel_example_t_amb, rank_site

COLS = ["rank", "option", "ko_gate", "viability_score", "eco_grade", "weighted_cop", "net_value_usd_yr"]
EXTRA = ["co2_avoided_t", "water_saved_m3", "capex_usd", "payback_yr", "product"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site_id", nargs="?")
    ap.add_argument("--mode", default="corrected", choices=["excel", "corrected"])
    ap.add_argument("--greenfield", type=int, choices=[0, 1])
    ap.add_argument("--weather", default="hourly", choices=["hourly", "daily_cosine"])
    ap.add_argument("--excel-example", action="store_true")
    a = ap.parse_args()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    if a.excel_example or not a.site_id:
        df = evaluate(excel_example_inputs(), excel_example_t_amb(), a.mode)
    else:
        df, x, prov = rank_site(a.site_id, a.mode, a.weather, a.greenfield)
        flagged = [k for k, p in prov.items() if p["status"] == "assumption"]
        print(f"{a.site_id}: {len(flagged)} of {len(prov)} inputs are flagged assumptions: {', '.join(flagged)}\n")
    cols = COLS + (EXTRA if a.mode == "corrected" else [])
    print(df[cols].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
