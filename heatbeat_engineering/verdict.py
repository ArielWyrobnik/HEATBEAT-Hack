"""Plain verdict for one site: does anything beat what the site does today, and by how much?

Why: the ranking always has a "best" row, even where the best row is today's setup or a gain too small to
matter. Sites that already run zero-water dry cooling (Abilene, Fairwater) or outside air with direct
evaporation (Microsoft, Meta) should say so plainly instead of showing a winner.

Levels
    no_gain     today's setup is the top row: every alternative the model checks has a negative NPV
    small_gain  best NPV is positive but below SMALL_GAIN_SHARE of one year's baseline electricity bill
    gain        anything above that

SMALL_GAIN_SHARE is a team threshold (not from literature): 2 % of one year's electricity bill over a
20 year NPV is inside the CAPEX uncertainty of the model (CAPEX mostly unverified, docs/ENGINEERING.md).
"""
from __future__ import annotations

import pandas as pd

SMALL_GAIN_SHARE = 0.02  # team threshold, see module docstring

TECH_TEXT = {"dry": "dry coolers (no cooling water)", "adiabatic": "adiabatic / direct evaporative cooling",
             "tower": "evaporative cooling towers"}


def is_today(row, baseline_tech: str) -> bool:
    return row["tech"] == baseline_tech and row["uses"] == "none" and not row["storage"]


def verdict(df: pd.DataFrame, base: dict, site, planned: bool = False) -> dict:
    """{level, text, best_chain, best_npv_usd, alternative_chain, alternative_npv_usd, threshold_usd, baseline_flag}."""
    bill = (base["it_mwh"] + base["cooling_mwh"] + base["other_mwh"]) * site.x["p_elec_usd_mwh"]
    thr = SMALL_GAIN_SHARE * bill
    rp = site.prov.get("baseline_rejection", {})
    flag = rp.get("status", "assumption")
    today = TECH_TEXT.get(site.baseline_rejection, site.baseline_rejection)
    if not len(df):
        return {"level": None, "text": "No feasible option.", "baseline_flag": flag}
    best = df.iloc[0]
    alt = next((r for _, r in df.iterrows() if not is_today(r, site.baseline_rejection)), None)
    out = {"best_chain": best["chain"], "best_npv_usd": float(best["npv_usd"]),
           "alternative_chain": None if alt is None else alt["chain"],
           "alternative_npv_usd": None if alt is None else float(alt["npv_usd"]),
           "threshold_usd": float(thr), "baseline_flag": flag}
    m = lambda v: f"{v / 1e6:,.1f} M USD"  # noqa: E731
    if is_today(best, site.baseline_rejection):
        out["level"] = "no_gain"
        out["text"] = (f"Nothing beats today's setup. The site already uses {today}; every alternative the model "
                       f"checks loses money (best alternative: {out['alternative_chain']}, NPV "
                       f"{m(out['alternative_npv_usd'] or 0)}).")
    elif best["npv_usd"] < thr:
        out["level"] = "small_gain"
        out["text"] = (f"Small gain only: {best['chain']} adds {m(best['npv_usd'])} NPV over 20 years, less than "
                       f"{SMALL_GAIN_SHARE * 100:.0f} % of one year's electricity bill ({m(bill)}). That is inside the "
                       "cost uncertainty of the model, so treat it as no clear case.")
    else:
        out["level"] = "gain"
        out["text"] = f"Improvement over today's {today}: {best['chain']}, NPV {m(best['npv_usd'])}."
    if planned:
        out["text"] = (out["text"].replace("today's setup", "the reference design")
                       .replace("The site already uses", "The reference design uses")
                       .replace("today's ", "the reference "))
        out["text"] += " Reference design for a planned site: the typical heat rejection for its cooling profile."
    elif flag == "assumption":
        out["text"] += (f" Today's heat rejection is not documented for this site; the model assumes {today}, "
                        "and the result depends on that.")
    elif flag == "data":
        out["text"] += " Today's setup is from a public source (see 'Current setup')."
    return out
