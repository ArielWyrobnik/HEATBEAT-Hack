"""Site inputs for the ranking engine: the 31 Excel keys, where each comes from for US sites,
the default used while real data is missing, and the range used in the sensitivity analysis.

Status per value (shown in the UI next to each number):
  data        from the HEATBEAT database or the data center profiles
  data_pipeline/site_ranking_inputs_<topic>.csv files (GIS, industry, water, ecology threads)
              carry their own status per row: data or assumption
  assumption  US default below. Flagged. Never present it as a site fact.
  excel       the Excel example value (only for the Excel reproduction test)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"
PIPELINE_DIR = Path(__file__).resolve().parents[1] / "data_pipeline"
# Each data thread writes its own file data_pipeline/site_ranking_inputs_<topic>.csv (no merge conflicts)
OVERRIDES_GLOB = "site_ranking_inputs*.csv"

# key: (us_default, (sens_low, sens_high), source plan for US sites)
INPUT_SPEC: dict[str, tuple] = {
    "is_greenfield": (0, (0, 1), "Toggle in the UI. Default 0 for operating sites, 1 for announced or hypothetical."),
    "cooling_type": ("air", None, "data: cooling profile (dlc_*, immersion, rear_door -> liquid; air_* -> air)."),
    "t_dc_base_c": (30, (25, 55), "data: facility return temperature of the cooling profile (PR 4)."),
    "q_dc_mw": (50, (10, 300), "data: it_load_mw x 0.9 from site_profiles.csv (mostly estimates)."),
    "slope_deg": (2.0, (0.5, 8), "GIS: USGS 3DEP 1 arc second DEM, mean slope in a 1 km buffer."),
    "flat_land_m2": (10000, (0, 50000), "GIS: parcel data (county) or NLCD 2021 open land within 500 m."),
    "d_water_m": (2000, (200, 10000), "GIS: USGS NHDPlus HR, nearest perennial river or lake."),
    "wsi_index": (2.0, (0.5, 4.5), "Water thread: WRI Aqueduct 4.0 baseline water stress, rescaled 0 to 5."),
    "has_existing_dh": (0, (0, 1), "GIS: US DOE / IDEA district energy system list; few US sites will be 1."),
    "d_dh_m": (5000, (300, 10000), "GIS: distance to nearest DH system or dense urban area (Census urban areas)."),
    "rho_heat_mwh_m": (1.0, (0.5, 4.0), "GIS: NREL ResStock/ComStock heat demand per km of street, county level."),
    "d_coast_m": (100000, (1000, 200000), "GIS: NOAA shoreline, or USGS brackish groundwater (2016 national assessment)."),
    "dz_m": (50, (5, 200), "GIS: DEM elevation of site minus intake."),
    "d_bio_m": (15000, (3000, 50000), "Industry thread: EPA AgSTAR farms, NREL biomass resource, food processing plants."),
    "d_co2_m": (100000, (10000, 300000), "Industry thread: EPA GHGRP subpart RR sites, Class VI wells, CO2 pipelines."),
    "d_pp_m": (5000, (500, 20000), "Industry thread: EIA-860 thermal power plants."),
    "q_fw_mw": (0, (0, 50), "Industry thread: EIA-860 steam unit size x feedwater share (estimate)."),
    "ind_zoning": (1, (0, 1), "Assumption: DC parcels are usually industrial zoned. Check county zoning maps."),
    "campus_area_m2": (0, (0, 50000), "Greenfield only: master plan. 0 for operating sites."),
    "agri_land_m2": (0, (0, 100000), "GIS: USDA Cropland Data Layer within 1 km (greenfield only in the Excel)."),
    "geo_storage_score": (3, (1, 5), "Geology thread: USGS aquifer maps and state geological surveys."),
    "p_elec_usd_kwh": (0.08, (0.05, 0.15), "data: EIA retail industrial price of the grid region (database)."),
    "p_fuel_usd_kwh": (0.035, (0.015, 0.075), "Market thread: EIA natural gas price by state. Default is a rough US commercial level, UNVERIFIED."),
    "p_steam_usd_mwh": (15, (10, 40), "Market thread. Default = cheap US gas / boiler efficiency, UNVERIFIED."),
    "p_water_usd_m3": (2.0, (0.5, 5.0), "Water thread: utility tariffs per site."),
    "p_co2_usd_ton": (0, (0, 100), "US: no federal carbon price, so 0 for heat options (coordinator decision 2026-11-26)."),
    "p_dac_credit_usd_ton": (180, (85, 180), "45Q credit for DAC with geologic storage, IRA 2022 (26 U.S.C. 45Q). Corrected mode only."),
    "d_market_m": (50000, (5000, 200000), "Market thread: distance to food distribution hubs."),
    "ci_grid_g_kwh": (400, (100, 700), "data: grid region carbon intensity (database, kg/MWh = g/kWh)."),
    "ci_fuel_g_kwh": (200, (180, 280), "Natural gas 53.06 kg CO2/MMBtu (EPA GHG Emission Factors Hub) = 181 g/kWh fuel, / 0.9 boiler = 200 g/kWh heat."),
    "eco_sens_index": (2, (1, 5), "Ecology thread: USFWS critical habitat, PAD-US protected areas."),
    "mit_tier": ("med", None, "Design choice. Default med."),
    # corrected mode only
    "pue": (1.4, (1.1, 1.6), "data: pue_assumed from site_profiles.csv."),
    "wue_l_kwh": (1.8, (0.2, 2.5), "Assumption: evaporative cooling; site WUE rarely published."),
    "baseline_cooling_evaporative": (True, None, "Assumption: True unless the cooling profile is chiller free (dlc_hot)."),
}

EXCEL_KEYS = [k for k in INPUT_SPEC if k not in ("p_dac_credit_usd_ton", "pue", "wue_l_kwh",
                                                  "baseline_cooling_evaporative")]


def excel_example_inputs() -> dict:
    return dict(json.loads((DATA_DIR / "excel_example_expected.json").read_text())["inputs"])


def us_defaults() -> dict:
    return {k: v[0] for k, v in INPUT_SPEC.items()}


def _cooling_type(profile_id: str | None) -> str:
    if not profile_id:
        return "air"
    return "air" if profile_id.startswith("air_") else "liquid"


def load_overrides() -> pd.DataFrame:
    """Long format: site_id,key,value,status,source,note. One row per site and input.

    status is "data" (measured or looked up) or "assumption" (estimate). Files are read in name
    order; a later file wins for the same site and key.
    """
    cols = ["site_id", "key", "value", "status", "source", "note"]
    files = sorted(PIPELINE_DIR.glob(OVERRIDES_GLOB))
    if not files:
        return pd.DataFrame(columns=cols)
    return pd.concat([pd.read_csv(f, dtype={"value": str}) for f in files], ignore_index=True)


def _cast(key, raw):
    d = INPUT_SPEC[key][0]
    if isinstance(d, bool):
        return str(raw).strip().lower() in ("1", "true", "yes")
    if isinstance(d, str):
        return str(raw)
    return float(raw)


def site_inputs(site_id: str, is_greenfield: int | None = None) -> tuple[dict, dict]:
    """Inputs for one site and the provenance of each value.

    Returns (inputs, provenance) where provenance[key] = {"status", "source"}.
    """
    import heatbeat_data as hd

    x = us_defaults()
    prov = {k: {"status": "assumption", "source": INPUT_SPEC[k][2]} for k in x}

    def put(k, v, status, source):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return
        x[k] = v
        prov[k] = {"status": status, "source": source}

    sites = hd.list_sites().set_index("site_id")
    if site_id in sites.index:
        s = sites.loc[site_id]
        put("is_greenfield", int(s.get("is_hypothetical", 0) or 0), "assumption",
            "is_hypothetical flag in sites.csv; operating sites are treated as existing")
        if pd.notna(s.get("retail_industrial_usd_mwh")):
            put("p_elec_usd_kwh", float(s["retail_industrial_usd_mwh"]) / 1000, "data",
                "database: grid_regions.retail_industrial_usd_mwh")
        if pd.notna(s.get("co2_kg_mwh")):
            put("ci_grid_g_kwh", float(s["co2_kg_mwh"]), "data", "database: grid_regions.co2_kg_mwh")
    try:
        hp = hd.heat_profile(site_id)
    except KeyError:
        hp = None
    if hp:
        ct = _cooling_type(hp.get("cooling_profile_id"))
        put("cooling_type", ct, "data", f"cooling profile {hp.get('cooling_profile_id')}")
        t = hp.get("facility_return_temp_c") if ct == "liquid" else (
            hp.get("facility_return_temp_c") or hp.get("exhaust_air_temp_c"))
        put("t_dc_base_c", t, "data", "cooling profile facility return / exhaust temperature")
        if hp.get("it_load_mw"):
            put("q_dc_mw", round(float(hp["it_load_mw"]) * 0.9, 1), "data",
                "site_profiles.csv it_load_mw x 0.9 capture (estimate, confidence "
                f"{hp.get('confidence')})")
        put("pue", hp.get("pue_assumed"), "data", "site_profiles.csv pue_assumed (estimate)")
        if hp.get("cooling_profile_id") == "dlc_hot":
            put("baseline_cooling_evaporative", False, "assumption", "dlc_hot runs chiller free on dry coolers")
            put("wue_l_kwh", 0.2, "assumption", "dry cooler baseline")
    # market prices (PR 12, heatbeat_data.market): used when that module is on the branch
    excel_market = getattr(hd, "excel_inputs", None)
    if excel_market is not None:
        try:
            for k, v in (excel_market(site_id) or {}).items():
                if k in INPUT_SPEC:
                    put(k, v, "data", "heatbeat_data.excel_inputs (market_prices.csv, state level)")
        except KeyError:
            pass
    ov = load_overrides()
    for r in ov[ov["site_id"] == site_id].itertuples():
        if r.key in INPUT_SPEC:
            put(r.key, _cast(r.key, r.value), str(r.status or "override"), str(r.source))
    if is_greenfield is not None:
        put("is_greenfield", int(is_greenfield), "user", "UI toggle")
    return x, prov
