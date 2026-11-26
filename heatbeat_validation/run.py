"""Run every reference case through the models and compare with what the project actually did and reports.

    python -m heatbeat_validation            # writes heatbeat_validation/results/*.csv and docs/VALIDATION_RESULTS.md

Two questions per reference:
(a) Feasibility: does the model find the solution that was actually built feasible (no knock out) and how
    does it rank it against the other options at that site?
(b) Numbers: do the model outputs (heat delivered, temperatures, CO2, water, efficiency) match the
    publicly reported figures? Verdict per figure: "match" within +-30 %, "same order" within a factor 3,
    otherwise "miss". Several reported figures are capacities or upper bounds; the note says so.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .cases import CASES

OUT = Path(__file__).resolve().parent / "results"
DOC = Path(__file__).resolve().parents[1] / "docs" / "VALIDATION_RESULTS.md"
LIVE = os.getenv("HEATBEAT_LIVE", "1") != "0"


def _family(uses: str, storage: str) -> str:
    if storage == "ates":
        return "ates"
    first = uses.split("+")[0]
    for fam in ("dh", "biogas", "desal", "feedwater", "orc", "adsorption"):
        if first.startswith(fam):
            return fam
    return "none"


def _families(df: pd.DataFrame) -> pd.DataFrame:
    """Best chain per family (heat rejection only counts as family 'none'), ranked by NPV.

    ATES counts as its own family (district heating chain with seasonal ATES storage)."""
    d = df.assign(family=[_family(u, s) for u, s in zip(df["uses"], df["storage"])])
    best = d.sort_values("npv_usd", ascending=False).drop_duplicates("family").reset_index(drop=True)
    best["family_rank"] = np.arange(1, len(best) + 1)
    return best


def _engineering(c: dict):
    from heatbeat_engineering import evaluate_site, load_site
    from heatbeat_engineering.params import defaults
    from heatbeat_engineering.site import Loop, set_input

    case = load_site(c["site_id"], live=LIVE)
    if c.get("it_mw"):
        set_input(case, "it_mw", c["it_mw"])
    if c.get("loops"):
        case.loops = [Loop(n, case.it_mw * share, ts, tr) for n, share, ts, tr in c["loops"]]
    for k, (v, _src) in c.get("overrides", {}).items():
        set_input(case, k, v)
    P = defaults()
    df, base, res = evaluate_site(case, P)
    fam = _families(df)
    ko = df.attrs.get("ko", {})
    row = fam[fam["family"] == c["family"]]
    top = fam.iloc[0]
    out = dict(engine="engineering", n_options=len(fam), top_option=top["chain"],
               top_family=top["family"], site_t_mean_c=round(case.t_mean, 1), it_mw_model=case.it_mw)
    plan_ko = {k: v for k, v in ko.items() if _family(k, "") == c["family"] or (c["family"] == "ates" and k.startswith("dh"))}
    if row.empty:
        out.update(feasible=False, rank=None, option=None,
                   ko_reason="; ".join(f"{k}: {v}" for k, v in plan_ko.items()) or "no chain of this family survived")
        return out, {}, case, P, None
    r = row.iloc[0]
    chain = res[r["chain_id"]]
    alone = df[(df["tech"] == r["tech"]) & (df["uses"] == "none")].iloc[0]
    out.update(feasible=True, rank=int(r["family_rank"]), option=r["chain"], npv_musd=round(r["npv_usd"] / 1e6, 2),
               reuse_npv_musd=round(r["reuse_npv_usd"] / 1e6, 2), ko_reason="")
    cop = r["cop_hp"] if pd.notna(r["cop_hp"]) else np.nan
    hp_elec = r["heat_delivered_mwh"] / cop if cop and cop > 0 else 0.0
    m = {
        "heat_delivered_mwh": r["heat_delivered_mwh"],
        "reuse_mw_th": r["heat_delivered_mwh"] / 8760,
        "co2_avoided_t_yr": r["co2_avoided_t_yr"] - alone["co2_avoided_t_yr"],
        "pue": r["pue"],
        "t_source_c": max(l.t_return_c for l in case.loops),
        "t_supply_c": P["dh_supply_c"] if c["family"] in ("dh", "ates") else np.nan,
        "water_m3_per_mw_yr": r["water_produced_m3"] / case.it_mw,
        "electricity_saved_mwh_yr": r["heat_delivered_mwh"] - hp_elec,
        "cop_hp": cop,
    }
    if c["family"] in ("dh", "ates", "biogas"):
        out["breakeven_heat_usd_mwh"] = _breakeven_heat_price(case, P, c["family"])
    return out, m, case, P, chain


def _breakeven_heat_price(case, P, family: str, lo: float = 0.0, hi: float = 400.0) -> float | None:
    """Heat price (USD/MWh) at which the best chain of `family` reaches reuse NPV = 0 (bisection).

    The database has no heat price outside the US (model default 50 USD/MWh), so this shows how far the
    real project's heat price must be from the default for the model to call it profitable."""
    from heatbeat_engineering import evaluate_site
    old = case.x["p_heat_usd_mwh"]

    def npv(p):
        case.x["p_heat_usd_mwh"] = p
        df, _, _ = evaluate_site(case, P)
        f = _families(df)
        row = f[f["family"] == family]
        return float(row["reuse_npv_usd"].iloc[0]) if len(row) else -np.inf

    try:
        if npv(hi) < 0:
            return None
        if npv(lo) >= 0:
            return lo
        for _ in range(12):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if npv(mid) < 0 else (lo, mid)
        return round(hi, 0)
    finally:
        case.x["p_heat_usd_mwh"] = old


def _orc_testbed(case, P) -> dict:
    """Model ORC at the Vertiv test points (source 58 C, condenser about 14 C, 31.4 kW heat)."""
    from heatbeat_engineering.industry import orc_efficiency
    t_air = 14.0 - P["orc_cond_above_air_k"]  # condenser at 14 C (vertiv_orc_wp TL)
    eta = float(orc_efficiency(58.0, [t_air], P)[0])
    eta63 = float(orc_efficiency(63.0, [t_air], P)[0])
    q = 31.4
    net = q * eta - q * (1 - eta) * P["sfp_dry_kw_kw"]
    year = orc_efficiency(58.0, case.t_db, P)
    return {"orc_eta_gross_max": max(eta, eta63), "orc_eta_gross_max_nsf": max(eta, eta63),
            "orc_net_with_fans_kw": net, "orc_hours_running_share": float((year > 0).mean())}


def _excel(c: dict, greenfield: int) -> tuple[dict, dict]:
    from heatbeat_ranking import rank_site
    ov = {k: v for k, (v, _s) in c.get("excel_overrides", c.get("overrides", {})).items()}
    if c.get("it_mw"):
        ov["q_dc_mw"] = c["it_mw"] * 0.9
    df, x, _ = rank_site(c["site_id"], mode="excel", is_greenfield=greenfield, overrides=ov, live=LIVE)
    row = df[df["key"] == c["excel_key"]].iloc[0]
    ok = df[df["ko_gate"] == 1]
    out = dict(engine=f"excel (greenfield={greenfield})", n_options=len(df), feasible=bool(row["ko_gate"]),
               rank=None if row["rank"] == "KO" else int(row["rank"]), option=row["option"],
               top_option=ok["option"].iloc[0] if len(ok) else "all KO", viability_score=row["viability_score"],
               ko_reason="" if row["ko_gate"] else _excel_ko_reason(c["excel_key"], x))
    m = {"reuse_mw_th": row["heat_rec_mwh"] / 8760, "heat_delivered_mwh": row["heat_rec_mwh"]}
    return out, m


def _excel_ko_reason(key: str, x: dict) -> str:
    """Plain words for the Excel gate inputs that fail (thresholds from heatbeat_ranking/options.py)."""
    checks = {
        "fish_farm": [("slope_deg", "<=", 8), ("flat_land_m2", ">=", 5000), ("d_water_m", "<=", 3000), ("wsi_index", "<", 4)],
        "district_heating": [("has_existing_dh", "==", 1), ("d_dh_m", "<=", 800), ("rho_heat_mwh_m", ">=", 2.5)],
        "biogas": [("d_bio_m", "<=", 25000), ("slope_deg", "<=", 10)],
        "absorption_cooling": [("t_dc_base_c", ">=", 65), ("wsi_index", "<", 3.8)],
        "orc": [("t_dc_base_c", ">=", 80)],
        "dac": [("d_co2_m", "<=", 50000)],
        "btes_ates": [("is_greenfield", "==", 1), ("geo_storage_score", ">=", 3)],
        "boiler_feedwater": [("is_greenfield", "==", 1), ("d_pp_m", "<=", 1500), ("q_fw_mw", ">=", 2)],
        "desalination": [("is_greenfield", "==", 1), ("d_coast_m", "<=", 5000), ("dz_m", "<=", 50), ("wsi_index", ">=", 2)],
        "biomass": [("is_greenfield", "==", 1), ("d_bio_m", "<=", 25000), ("ind_zoning", "==", 1), ("slope_deg", "<=", 10)],
        "drying": [("is_greenfield", "==", 1), ("ind_zoning", "==", 1), ("q_dc_mw", ">=", 5), ("slope_deg", "<=", 8)],
        "snow_melt": [("is_greenfield", "==", 1), ("campus_area_m2", ">=", 20000)],
        "greenhouse": [("is_greenfield", "==", 1), ("agri_land_m2", ">=", 20000), ("slope_deg", "<=", 6), ("wsi_index", "<", 4)],
    }
    ops = {"<=": np.less_equal, ">=": np.greater_equal, "<": np.less, "==": np.equal}
    bad = [f"{k} {x[k]:g} (needs {op} {lim:g})" for k, op, lim in checks.get(key, [])
           if not ops[op](float(x[k]), lim)]
    return "; ".join(bad) or "climate hours gate (temperature counts)"


def _verdict(model, reported) -> tuple[float | None, str]:
    if model is None or reported is None or pd.isna(model) or reported == 0:
        return None, "no model value"
    if np.sign(model) != np.sign(reported):
        return None, "miss (opposite sign)"
    ratio = float(model) / float(reported)
    if 1 / 1.3 <= ratio <= 1.3:
        return ratio, "match"
    if 1 / 3 <= ratio <= 3:
        return ratio, "same order"
    return ratio, "miss"


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    warnings.filterwarnings("ignore")
    rows, mets = [], []
    for c in CASES:
        base = dict(ref=str(c["ref"]), solution=c["solution"], project=c["project"], site_id=c["site_id"],
                    location=c["location_note"], real_status=c["status"])
        model_vals = {}
        for eng in c["engines"]:
            try:
                if eng == "engineering":
                    out, m, case, P, _chain = _engineering(c)
                    if c.get("family") == "orc":
                        m.update(_orc_testbed(case, P))
                    model_vals.setdefault("engineering", m)
                    rows.append({**base, **out})
                else:
                    for g in (0, 1):
                        out, m = _excel(c, g)
                        if g == 1:
                            model_vals.setdefault("excel", m)
                        rows.append({**base, **out})
            except Exception as exc:  # noqa: BLE001  (e.g. weather not stored yet for a new site)
                rows.append({**base, "engine": eng, "feasible": None, "ko_reason": f"not run: {type(exc).__name__}: {exc}"})
        if c.get("not_covered"):
            rows[-1]["note"] = c["not_covered"]
        elif c.get("note"):
            rows[-1]["note"] = c["note"]
        for metric, val, unit, src, note in c["reported"]:
            key = metric.removesuffix("_target").removesuffix("_nsf")  # same model output, other reported figure
            eng = "engineering" if key in model_vals.get("engineering", {}) else "excel"
            mv = model_vals.get(eng, {}).get(key)
            ratio, verdict = _verdict(mv, val)
            if c.get("not_covered"):
                verdict = "not covered by the model"
            mets.append(dict(ref=str(c["ref"]), solution=c["solution"], metric=metric, reported=val, model=mv,
                             unit=unit, model_engine=eng if mv is not None else "", ratio=ratio, verdict=verdict,
                             source_id=src, note=note))
    table, metrics = pd.DataFrame(rows), pd.DataFrame(mets)
    OUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT / "validation_table.csv", index=False)
    metrics.to_csv(OUT / "validation_metrics.csv", index=False)
    write_doc(table, metrics)
    return table, metrics


def _fmt(v, nd=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, (float, np.floating)):
        if float(v).is_integer() and abs(v) < 100:
            return str(int(v))
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.{nd}f}"
    return str(v)


def write_doc(table: pd.DataFrame, metrics: pd.DataFrame) -> None:
    lines = ["# Validation results (generated)", "",
             "Generated by `python -m heatbeat_validation`. Method, sources and interpretation: "
             "[VALIDATION.md](VALIDATION.md). Do not edit by hand.", "",
             "## (a) Is the implemented solution feasible in the model?", "",
             "| Ref | Solution | Site | Model | Feasible | Rank | Options | Model top option | Reuse NPV (MUSD) | Break-even heat price (USD/MWh) | Why KO |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in table.itertuples():
        feas = {True: "yes", False: "no"}.get(r.feasible, "not run")
        lines.append(f"| {r.ref} | {r.solution} | `{r.site_id}` | {r.engine} | {feas} | {_fmt(getattr(r, 'rank', None))} | "
                     f"{_fmt(getattr(r, 'n_options', None))} | {_fmt(getattr(r, 'top_option', ''))} | "
                     f"{_fmt(getattr(r, 'reuse_npv_musd', None))} | {_fmt(getattr(r, 'breakeven_heat_usd_mwh', None))} | "
                     f"{_fmt(getattr(r, 'ko_reason', ''))} |")
    lines += ["", "## (b) Do the numbers match the reported figures?", "",
              "| Ref | Metric | Reported | Model | Unit | Model / reported | Verdict | Source | Note |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in metrics.itertuples():
        lines.append(f"| {r.ref} | {r.metric} | {_fmt(r.reported, 3)} | {_fmt(r.model, 3)} | {r.unit} | "
                     f"{_fmt(r.ratio)} | {r.verdict} | {r.source_id} | {r.note} |")
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    t, m = run()
    pd.set_option("display.width", 250)
    print(t[["ref", "engine", "feasible", "rank", "n_options", "top_option", "ko_reason"]].to_string())
    print(m[["ref", "metric", "reported", "model", "ratio", "verdict"]].to_string())
