"""Check the engineering baseline against what operators report (heatbeat_data.current_setup).

    python -m heatbeat_engineering.validate_setup          # table to stdout
    python -m heatbeat_engineering.validate_setup out.csv  # and write it

For each site with a documented setup: modelled baseline water, WUE and PUE next to the reported
values. `implied_it_mw` = reported water / modelled water per MW of IT: if it is far below the IT load
we assumed, the IT estimate (team guess) is probably too high, or part of the site runs without water.
Reported water is consumption where given, else withdrawal (withdrawal includes blowdown and domestic use).
"""
from __future__ import annotations

import sys

import pandas as pd


def compare_with_reported(live: bool = False) -> pd.DataFrame:
    import heatbeat_data as hd

    from .chains import baseline
    from .params import defaults
    from .site import load_site

    v = hd.verification_status().set_index("site_id")
    rows = []
    for sid in v.index:
        st = hd.current_setup(sid)
        try:
            s = load_site(sid, live=live)
        except Exception as e:  # noqa: BLE001  (no weather stored and no internet)
            rows.append({"site_id": sid, "status": v.loc[sid, "status"], "error": str(e)[:80]})
            continue
        b = baseline(s, defaults())

        def num(k):
            f = st.get(k)
            try:
                return float(f["value"]) if f else None
            except (TypeError, ValueError):
                return None
        w, ww = num("water_use_m3_yr"), num("water_withdrawal_m3_yr")
        rep = w if w is not None else ww
        per_mw = b["water_m3"] / s.it_mw if s.it_mw else 0
        rows.append({
            "site_id": sid, "status": v.loc[sid, "status"], "heat_rejection": s.baseline_rejection,
            "it_mw_assumed": s.it_mw, "model_water_m3_yr": round(b["water_m3"]),
            "reported_water_m3_yr": rep, "reported_kind": "consumption" if w is not None else ("withdrawal" if ww else None),
            "implied_it_mw": round(rep / per_mw) if rep and per_mw > 0 else None,
            "model_wue_l_kwh": round(b["wue_l_kwh"], 2), "reported_wue_l_kwh": num("wue_l_kwh"),
            "model_pue": round(b["pue"], 3), "reported_pue": num("pue"),
            "reported_pue_scope": (st.get("pue") or {}).get("scope"),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = compare_with_reported()
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))
    if len(sys.argv) > 1:
        df.to_csv(sys.argv[1], index=False)
