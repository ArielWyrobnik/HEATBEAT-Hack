"""The 13 heat recovery options of the team Excel model (sheet 3 and 4 of "Hack data.xlsx").

Every number in this file is copied from the Excel unless a comment says otherwise.
The Excel itself gives no sources for these coefficients: treat them as team assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Option:
    key: str
    name: str            # exact Excel name (used in tests and in the Excel water rule)
    build_mode: str      # Both | Adaptive | Greenfield_Only
    t_sink_c: float      # target sink temperature, sheet 3 row 1
    uses_heat_pump: bool = True  # ORC column is hard coded to 0 in the Excel
    output: str = "heat"  # what the recovered heat displaces, used by the corrected GHG counterfactual


OPTIONS: list[Option] = [
    Option("fish_farm", "Fish Farm", "Both", 28),
    Option("district_heating", "District Heating", "Adaptive", 65),
    Option("biogas", "Biogas Generator", "Both", 38),
    Option("absorption_cooling", "Absorption Cooling", "Both", 85, output="cooling"),
    Option("orc", "Organic Rankine Cycle", "Both", 100, uses_heat_pump=False, output="electricity"),
    Option("dac", "Carbon Capture / DAC", "Both", 90, output="co2_removal"),
    Option("btes_ates", "BTES / ATES Storage", "Greenfield_Only", 55),
    Option("boiler_feedwater", "Boiler Feedwater Preheat", "Greenfield_Only", 55),
    Option("desalination", "Desalination (MED/MD)", "Greenfield_Only", 70, output="water"),
    Option("biomass", "Biomass Processing", "Greenfield_Only", 65),
    Option("drying", "Industrial Drying", "Greenfield_Only", 75),
    Option("snow_melt", "Radiant / Snow-Melt", "Greenfield_Only", 35),
    Option("greenhouse", "Co-Designed Greenhouse", "Greenfield_Only", 40),
]
BY_KEY = {o.key: o for o in OPTIONS}


def _ramp(t, hi, span, lo_clip=0.0):
    """Excel MIN(1, MAX(lo, (hi - T) / span))."""
    return np.minimum(1.0, np.maximum(lo_clip, (hi - t) / span))


def heat_recovered_mw(key: str, t_amb: np.ndarray, x: dict) -> np.ndarray:
    """Hourly recovered DC heat in MW_th (sheet 3 columns F to R)."""
    q = float(x["q_dc_mw"])
    ones = np.ones_like(t_amb, dtype=float)
    match key:
        case "fish_farm":
            return q * _ramp(t_amb, 26, 18)
        case "district_heating":
            return q * _ramp(t_amb, 16, 22)
        case "biogas":
            return q * _ramp(t_amb, 30, 25, lo_clip=0.2)
        case "absorption_cooling":
            return q * np.minimum(1.0, np.maximum(0.0, (t_amb - 22) / 14))
        case "orc":
            return np.where(t_amb < 32, q, 0.0)
        case "btes_ates":
            return np.where(t_amb > 12, q * 0.95, q * 0.6)
        case "boiler_feedwater":
            return ones * min(q, float(x["q_fw_mw"]))
        case "snow_melt":
            return q * _ramp(t_amb, 3, 15)
        case "greenhouse":
            return q * _ramp(t_amb, 18, 20)
        case "dac" | "desalination" | "biomass" | "drying":
            return ones * q
    raise KeyError(key)


def ko_gate(key: str, x: dict, t_amb: np.ndarray, t_dc: np.ndarray) -> bool:
    """Binary knock-out gate (sheet 4 column I). Counts are hours per year."""
    g = int(x["is_greenfield"]) == 1
    n = lambda mask: int(np.count_nonzero(mask))  # noqa: E731
    match key:
        case "fish_farm":
            return (t_amb.mean() <= 26 and n(t_amb > 30) < 1500 and x["slope_deg"] <= 8
                    and x["flat_land_m2"] >= 5000 and x["d_water_m"] <= 3000
                    and x["wsi_index"] < 4 and x["q_dc_mw"] >= 0.5)
        case "district_heating":
            net = (x["d_dh_m"] <= 3000 and x["rho_heat_mwh_m"] >= 1.5) if g else (
                int(x["has_existing_dh"]) == 1 and x["d_dh_m"] <= 800 and x["rho_heat_mwh_m"] >= 2.5)
            return n(t_amb < 15) >= 2000 and net
        case "biogas":
            return n(t_amb < 25) >= 2500 and x["d_bio_m"] <= 25000 and x["slope_deg"] <= 10
        case "absorption_cooling":
            return t_dc.max() >= 65 and n(t_amb > 24) >= 1500 and x["wsi_index"] < 3.8
        case "orc":
            return t_dc.min() >= 80 and n(t_amb < 30) >= 5000
        case "dac":
            return x["d_co2_m"] <= 50000 and n(t_amb > 35) < 1500
        case "btes_ates":
            return g and x["geo_storage_score"] >= 3 and n(t_amb < 15) >= 2500 and n(t_amb > 20) >= 1000
        case "boiler_feedwater":
            return g and x["d_pp_m"] <= 1500 and x["q_fw_mw"] >= 2
        case "desalination":
            return g and x["d_coast_m"] <= 5000 and x["dz_m"] <= 50 and x["wsi_index"] >= 2
        case "biomass":
            return g and x["d_bio_m"] <= 25000 and int(x["ind_zoning"]) == 1 and x["slope_deg"] <= 10
        case "drying":
            return g and int(x["ind_zoning"]) == 1 and x["q_dc_mw"] >= 5 and x["slope_deg"] <= 8
        case "snow_melt":
            return g and x["campus_area_m2"] >= 20000 and n(t_amb <= 2) >= 800
        case "greenhouse":
            return (g and x["agri_land_m2"] >= 20000 and x["slope_deg"] <= 6 and x["wsi_index"] < 4
                    and n(t_amb < 18) >= 2000)
    raise KeyError(key)


def gross_value_usd(key: str, e_mwh: float, x: dict) -> float:
    """Annual gross value of the recovered heat in USD, before heat pump electricity (sheet 4 col L).

    p_fuel is in USD/kWh, so p_fuel * 1000 is USD/MWh. The factors 650, 900, 950 are the Excel's
    fractions of the fuel price that each product can capture (team assumption, no source).
    """
    pf, pe = float(x["p_fuel_usd_kwh"]), float(x["p_elec_usd_kwh"])
    market = 1 - float(x["d_market_m"]) / 300000
    match key:
        case "fish_farm":
            return e_mwh * pf * 650 * max(0.2, market)
        case "greenhouse":
            return e_mwh * pf * 900 * max(0.3, market)
        case "district_heating" | "biogas" | "drying" | "snow_melt":
            return e_mwh * pf * 1000
        case "btes_ates":
            return e_mwh * pf * 900
        case "biomass":
            return e_mwh * pf * 950
        case "absorption_cooling":
            # thermal COP 0.7, displaces an electric chiller with COP 4.5
            return e_mwh * 0.7 * (pe * 1000 / 4.5)
        case "orc":
            # 10 % net electric efficiency (Excel); see AUDIT.md, physically too high at 60 to 100 C
            return e_mwh * 0.1 * pe * 1000
        case "dac":
            # 0.556 tCO2 per MWh_th (about 1.8 MWh_th/t) and 0.25 MWh_e per t
            return e_mwh * 0.556 * (float(x["p_co2_usd_ton"]) - 0.25 * pe * 1000)
        case "boiler_feedwater":
            return e_mwh * float(x["p_steam_usd_mwh"])
        case "desalination":
            # 15.38 m3 per MWh_th, i.e. 65 kWh_th per m3 (thermal MED)
            return e_mwh * 15.38 * float(x["p_water_usd_m3"])
    raise KeyError(key)
