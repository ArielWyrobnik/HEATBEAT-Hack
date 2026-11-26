"""Audit of the engineering recommendations against the documented current setup, and an inventory
of every model input per site with where it comes from.

    python -m heatbeat_engineering.audit          # writes docs/audit/*.csv, prints a summary

Files written
    docs/audit/recommendations.csv     one row per US site: recommendation before PR #41 (heat rejection
                                       assumed from the cooling profile) vs now (documented setup where a
                                       source exists), baseline used, verdict, how much the answer depends
                                       on the baseline, and the result at the IT load implied by reported water
    docs/audit/input_inventory.csv     one row per site and input: value, class, confidence, source
    docs/audit/model_parameters.csv    the global engineering and cost parameters (same for every site)

"Before" comes from docs/audit/results_before_pr41.csv, the output of `python -m heatbeat_engineering --all
--offline` at commit 0566f4b (main just before PR #41), so it can be reproduced with git.

Input classes (column `class`)
    sourced_site        a public source states it for this site (operator report, permit, press)
    sourced_region      public dataset value for the state, grid region or utility (EIA, eGRID, ISO, tariff)
    measured_location   public dataset at the site coordinates (ERA5 weather, WRI Aqueduct)
    derived             computed from public data with a documented method (GIS distances, unit conversions);
                        `confidence` comes from the data file (low = rough method, e.g. campus centre coordinates)
    literature_typical  typical value for the technology from literature, not specific to this site
    team_estimate       team judgement or a value the data file flags as estimate (IT load, engineering
                        estimates, scoring thresholds); `confidence` says how good the judgement is
    synthetic           generated placeholder (hourly price shape, synthetic tariff rows)
    default             fallback because the data is missing
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import evaluate
from .chains import evaluate_site
from .params import PARAMS, defaults
from .site import SITE_SCOPES, load_site
from .verdict import is_today, verdict

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "audit"
DP = ROOT / "data_pipeline"
TECHS = ("dry", "adiabatic", "tower")


def _short(chain: str) -> str:
    return (chain.replace("Biogas digester heating (thermophilic 55 C)", "digester heating")
            .replace("Biogas digester heating (mesophilic 37 C)", "digester heating (meso)")
            .replace("Boiler feedwater preheat", "feedwater"))


def _best(df, tech):
    b = df.iloc[0]
    return ("no change" if is_today(b, tech) else _short(b["chain"])), round(b["npv_usd"] / 1e6, 2)


def recommendations(live: bool = False) -> pd.DataFrame:
    import heatbeat_data as hd

    before = pd.read_csv(OUT / "results_before_pr41.csv").set_index("site_id")
    check = pd.read_csv(DP / "current_setup_check.csv").set_index("site_id")
    status = hd.verification_status().set_index("site_id")
    rows = []
    for sid in hd.list_sites().query("country_iso2 == 'US'")["site_id"]:
        df, base, _, s = evaluate(site_id=sid, live=live, greenfield=None)
        v = verdict(df, base, s)
        rp = s.prov["baseline_rejection"]
        hr = s.setup.get("heat_rejection") or {}
        b = before.loc[sid] if sid in before.index else None
        rec_b = None
        if b is not None:
            rec_b = "no change" if b["best_npv_musd"] == 0 and b["best_chain"].split(" +")[0].lower().startswith(
                {"dry": "dry", "adiabatic": "adiabatic", "tower": "cooling tower"}[b["baseline_rejection"]]) \
                else _short(b["best_chain"])
        rec_n, npv_n = _best(df, s.baseline_rejection)
        row = {
            "site_id": sid, "name": s.name, "setup_status": status["status"].get(sid, "unverified"),
            "baseline_before": None if b is None else b["baseline_rejection"],
            "baseline_now": s.baseline_rejection,
            "baseline_now_basis": "documented" if rp["status"] == "data" else "assumed from cooling profile",
            "baseline_source": hr.get("source_title") if rp["status"] == "data" else None,
            "baseline_confidence": hr.get("confidence") if rp["status"] == "data" else None,
            "low_confidence_hint": (hr.get("value") if hr and rp["status"] != "data" else None),
            "cooling_profile": s.cooling_profile, "it_mw": s.it_mw,
            "rec_before": rec_b, "npv_before_musd": None if b is None else b["best_npv_musd"],
            "rec_now": rec_n, "npv_now_musd": npv_n, "verdict": v["level"],
            "water_saved_now_m3_yr": round(float(df.iloc[0]["water_saved_m3_yr"])),
        }
        row["changed"] = ("yes" if (row["rec_before"], row["baseline_before"]) != (rec_n, s.baseline_rejection)
                          else "no")
        # how much the answer depends on the baseline: best option if today's heat rejection were each technology
        for t in TECHS:
            d2, _, _, s2 = evaluate(site_id=sid, live=live, greenfield=None, overrides={"baseline_rejection": t})
            row[f"rec_if_{t}"], row[f"npv_if_{t}_musd"] = _best(d2, t)
        # IT load implied by the reported water volume (derived, see validate_setup.py), where reported
        imp = check["implied_it_mw"].get(sid) if sid in check.index else None
        if imp is not None and pd.notna(imp) and imp > 0:
            d3, _, _, s3 = evaluate(site_id=sid, live=live, greenfield=None, overrides={"it_mw": float(imp)})
            row["implied_it_mw"] = float(imp)
            row["rec_at_implied_mw"], row["npv_at_implied_mw_musd"] = _best(d3, s3.baseline_rejection)
        row["verdict_text"] = v["text"]
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- input inventory

def input_inventory(live: bool = False) -> pd.DataFrame:
    import heatbeat_data as hd

    prof = pd.read_csv(DP / "site_profiles.csv").drop_duplicates("site_id").set_index("site_id")
    cp = pd.read_csv(DP / "cooling_profiles.csv").set_index("cooling_profile_id")
    wat = pd.read_csv(DP / "site_water.csv").set_index("site_id")
    gis = pd.read_csv(DP / "site_gis.csv").set_index("site_id")
    ind = pd.read_csv(DP / "site_industry.csv").set_index("site_id")
    eco = pd.read_csv(DP / "site_ecology.csv").set_index("site_id")
    mk = pd.read_csv(DP / "market_prices.csv")
    rows = []

    def add(sid, key, label, value, unit, cls, conf, source, note=""):
        rows.append({"site_id": sid, "input": key, "label": label, "value": value, "unit": unit, "class": cls,
                     "confidence": conf, "source": source, "note": note})

    def market(state, item):
        r = mk[(mk["country_iso2"] == "US") & (mk["region"] == state) & (mk["item"] == item)]
        if not len(r):
            r = mk[(mk["country_iso2"] == "US") & (mk["region"].isin(["US", "national"])) & (mk["item"] == item)]
        if not len(r):
            return None
        r = r.iloc[0]
        return r

    for sid in hd.list_sites().query("country_iso2 == 'US'")["site_id"]:
        s = load_site(sid, live=live)
        site = hd.get_site(sid, live=live)
        g, st = site.grid, s.state
        p = prof.loc[sid]
        # data center itself
        cls = "team_estimate" if int(p.get("is_assumed") or 0) or str(p["confidence"]) == "low" else "sourced_site"
        add(sid, "it_mw", "IT load", s.it_mw, "MW", cls, p["confidence"], p["source_ids"], p.get("notes") or "")
        cs = s.setup.get("cooling_profile_id") or {}
        ok = cs.get("confidence") in ("high", "medium") and cs.get("scope") in SITE_SCOPES
        add(sid, "cooling_profile", "Cooling at the rack", s.cooling_profile, "",
            "sourced_site" if ok else "team_estimate", cs.get("confidence") if ok else p["confidence"],
            cs.get("source_title") if ok else f"site_profiles.csv ({p['source_ids']})")
        c = cp.loc[s.cooling_profile] if s.cooling_profile in cp.index else None
        for l in s.loops:
            add(sid, f"loop_{l.name}", f"{l.name} loop temperatures and heat", f"{l.t_return_c:.0f}/{l.t_supply_c:.0f} C, "
                f"{l.q_mw:,.0f} MW", "", "literature_typical", None if c is None else c["confidence"],
                f"cooling_profiles.csv ({'' if c is None else c['source_ids']})",
                "typical for the cooling profile, not measured at this site; heat = IT load x liquid share")
        rp = s.prov["baseline_rejection"]
        hr = s.setup.get("heat_rejection") or {}
        add(sid, "baseline_rejection", "Today's heat rejection", s.baseline_rejection, "",
            "sourced_site" if rp["status"] == "data" else "team_estimate",
            hr.get("confidence") if rp["status"] == "data" else "low",
            hr.get("source_url") if rp["status"] == "data" else "typical for the cooling profile (no public source)")
        pf = s.prov.get("pue_reported")
        add(sid, "pue_reported", "PUE used for comparison", s.pue_reported, "",
            "sourced_site" if pf else "team_estimate", "high" if pf else p["confidence"],
            pf["source"] if pf else "site_profiles.csv pue_assumed",
            "the model computes its own PUE from the energy balance; this value is only a check")
        add(sid, "coordinates", "Location", f"{site.meta['lat']}, {site.meta['lon']}", "deg", "derived",
            site.meta.get("coord_precision"), "sites.csv", "campus_approx = campus centre from maps, not a parcel")
        # location data
        wsrc = str(site.weather["source"].iloc[0]) if len(site.weather) else "none"
        add(sid, "weather", "Hourly dry and wet bulb temperature", "8760 h", "C",
            "synthetic" if "synthetic" in wsrc else "measured_location", "high", wsrc,
            "reanalysis at the coordinates, one year")
        add(sid, "p_elec_usd_mwh", "Electricity price (retail industrial)", s.x["p_elec_usd_mwh"], "USD/MWh",
            "synthetic" if g.get("retail_price_is_synthetic") else "sourced_region", "medium",
            f"{g.get('retail_price_source')} {g.get('retail_price_year')}",
            "state average; a hyperscale contract price is not public and is likely lower")
        add(sid, "ci_grid_kg_mwh", "Grid carbon intensity", round(s.x["ci_grid_kg_mwh"], 1), "kg CO2/MWh",
            "synthetic" if g.get("co2_is_synthetic") else "sourced_region", "high",
            f"{g.get('co2_source')} {g.get('co2_year')} ({g.get('egrid_subregion')})", "annual average, not hourly")
        hk = g.get("hourly_price_kind")
        add(sid, "p_wholesale_usd_mwh", "Hourly wholesale price", round(s.x["p_wholesale_usd_mwh"], 1), "USD/MWh",
            "synthetic" if hk == "synthetic_shape" else "sourced_region", "high" if hk != "synthetic_shape" else "low",
            (f"{g.get('iso_rto')} {g.get('lmp_location')} ({hk})" if g.get("iso_rto") else
             "no wholesale market in this region: synthetic hourly shape"),
            "used only for the power value of feedwater preheat and ORC")
        for key, item, label, unit in [("p_gas_usd_mwh", "ng_citygate_usd_mcf", "Gas citygate price", "USD/MWh"),
                                       ("p_heat_usd_mwh", "ng_commercial_usd_mcf", "Heat price (gas boiler)", "USD/MWh"),
                                       ("rin_usd_mmbtu", "rin_d3_usd", "D3 RIN value", "USD/MMBtu"),
                                       ("lcfs_usd_t", "lcfs_credit_usd_t", "LCFS credit", "USD/t"),
                                       ("p_co2_usd_t", "p_co2_usd_ton", "State carbon price", "USD/t")]:
            r = market(st, item)
            if key == "lcfs_usd_t" and st not in ("CA", "OR", "WA"):
                add(sid, key, label, 0.0, unit, "sourced_region", "high", "no LCFS program in this state")
                continue
            if r is None:
                add(sid, key, label, s.x[key], unit, "default" if s.prov.get(key, {}).get("status") == "assumption"
                    else "sourced_region", None, s.prov.get(key, {}).get("source"))
                continue
            est = int(r["is_estimate"] or 0) if pd.notna(r["is_estimate"]) else 0
            cls = "team_estimate" if est else ("derived" if key == "p_heat_usd_mwh" else "sourced_region")
            add(sid, key, label, round(s.x[key], 2), unit, cls, "low" if est else "high",
                r["source_url"] if pd.notna(r["source_url"]) else r["source_id"],
                "gas price / boiler efficiency (assumed)" if key == "p_heat_usd_mwh" else (r["note"] if pd.notna(r["note"]) else ""))
        w = wat.loc[sid] if sid in wat.index else None
        if w is not None:
            est = int(w["water_is_estimated"] or 0) or int(w["sewer_is_estimated"] or 0)
            add(sid, "p_water_usd_m3", "Water + sewer tariff", s.x["p_water_usd_m3"], "USD/m3",
                "team_estimate" if est else "sourced_region", w["confidence"], f"{w['water_utility']} ({w['source_ids']})",
                "estimated part flagged in site_water.csv" if est else "")
        add(sid, "wsi", "Water stress (WRI Aqueduct)", s.x["wsi"], "0 to 5", "measured_location", "high",
            "WRI Aqueduct 4.0 (data_pipeline/aqueduct_sites.csv)")
        gi = gis.loc[sid] if sid in gis.index else None
        for key, label, unit in [("d_dh_m", "Distance to dense heat demand", "m"),
                                 ("rho_heat_mwh_m", "Linear heat density of that area", "MWh/m"),
                                 ("d_coast_m", "Distance to coast", "m")]:
            if gi is None:
                continue
            conf = gi.get(f"{key}_confidence")
            add(sid, key, label, s.x[key], unit, "derived", conf, gi.get(f"{key}_source"))
        ii = ind.loc[sid] if sid in ind.index else None
        if ii is not None:
            add(sid, "d_pp_m", "Distance to thermal power plant", s.x["d_pp_m"], "m", "derived",
                ii["pp_confidence"], f"{ii['pp_name']}: {ii['pp_source']}")
            add(sid, "q_fw_mw", "Feedwater heat that plant could take", s.x["q_fw_mw"], "MW", "team_estimate", "low",
                "engineering estimate from steam capacity (docs/INDUSTRY.md)")
            add(sid, "d_bio_m", "Distance to digester / feedstock", s.x["d_bio_m"], "m", "derived",
                ii["bio_confidence"], f"{ii['bio_name']}: {ii['bio_source']}")
        e = eco.loc[sid] if sid in eco.index else None
        if e is not None:
            add(sid, "geo_storage_score", "Geology score for ATES/BTES", s.x["geo_storage_score"], "1 to 5",
                "team_estimate", e["geo_confidence"], f"{e['geo_source_ids']} (team thresholds on public geology)")
    return pd.DataFrame(rows)


def model_parameters() -> pd.DataFrame:
    cls = {"physics": "physics", "literature": "literature_typical", "assumption": "team_estimate"}
    return pd.DataFrame([{"parameter": k, "value": p.value, "low": p.low, "high": p.high, "unit": p.unit,
                          "class": cls.get(p.status, p.status), "status": p.status, "source": p.source}
                         for k, p in PARAMS.items()])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rec = recommendations()
    rec.to_csv(OUT / "recommendations.csv", index=False)
    inv = input_inventory()
    inv.to_csv(OUT / "input_inventory.csv", index=False)
    par = model_parameters()
    par.to_csv(OUT / "model_parameters.csv", index=False)
    pd.set_option("display.width", 250)
    print(rec[["site_id", "baseline_before", "baseline_now", "baseline_now_basis", "rec_before", "npv_before_musd",
               "rec_now", "npv_now_musd", "verdict"]].to_string(index=False))
    print(inv.groupby("class").size())
    print(par.groupby("class").size())
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
