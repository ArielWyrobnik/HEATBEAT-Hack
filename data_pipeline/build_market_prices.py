"""Build data_pipeline/market_prices.csv: market prices that value the outputs of each solution.

Run:  python -m data_pipeline.build_market_prices

No network needed. All source numbers below were transcribed on 2026-11-26 from the public
documents listed in SOURCES (the cloud build machine cannot reach the EIA/USDA/NOAA APIs, see
docs/MARKET.md). Derived values (USD per kWh of heat, steam value, carbon intensity of displaced
heat) are computed here from those inputs plus a few engineering assumptions in ASSUMPTIONS.
Every assumption is flagged with is_estimate = 1 in the output.

Output format: long table, one row per (country_iso2, region, item). region "*" is the national
default used when no state row exists. Columns:
    country_iso2, region, item, value, low, high, unit, year, category, is_estimate,
    source_id, source_url, note
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "market_prices.csv"

US_STATES = ["AZ", "CA", "FL", "GA", "IA", "IL", "LA", "MA", "NC", "NE", "NJ", "NV", "NY", "OH",
             "OK", "OR", "SC", "TN", "TX", "UT", "VA", "WA", "WI", "WY"]

# US Census regions, used for EIA regional heating fuel prices.
CENSUS_REGION = {
    "MA": "Northeast", "NJ": "Northeast", "NY": "Northeast",
    "IA": "Midwest", "IL": "Midwest", "NE": "Midwest", "OH": "Midwest", "WI": "Midwest",
    "FL": "South", "GA": "South", "LA": "South", "NC": "South", "OK": "South", "SC": "South",
    "TN": "South", "TX": "South", "VA": "South",
    "AZ": "West", "CA": "West", "NV": "West", "OR": "West", "UT": "West", "WA": "West", "WY": "West",
}

SOURCES = {
    "eia_nga_t22": ("EIA Natural Gas Annual 2024, Table 22, average citygate price by state",
                    "https://www.eia.gov/naturalgas/Annual/pdf/table_022.pdf"),
    "eia_nga_t23": ("EIA Natural Gas Annual 2024, Table 23, average price delivered to consumers by state and sector",
                    "https://www.eia.gov/naturalgas/Annual/pdf/table_023.pdf"),
    "eia_wfo_2026": ("EIA Winter Fuels Outlook 2026-27 (STEO, 6 Oct 2026), winter Nov-Mar forecast",
                     "https://www.eia.gov/outlooks/steo/report/perspectives/2026/10-winterfuels/article.php"),
    "eia_recs_2020": ("EIA RECS 2020, Highlights for space heating fuel in U.S. homes by state",
                      "https://www.eia.gov/consumption/residential/data/2020/state/pdf/State%20Space%20Heating%20Fuels.pdf"),
    "epa_ef_hub": ("EPA GHG Emission Factors Hub, Table 1 stationary combustion (kg CO2 per MMBtu HHV)",
                   "https://www.epa.gov/climateleadership/ghg-emission-factors-hub"),
    "arb_auction_2025_11": ("CARB / Quebec joint auction #45, Nov 2025 summary results",
                            "https://ww2.arb.ca.gov/sites/default/files/2025-11/nc-nov_2025_summary_results_report.pdf"),
    "edf_wa_2026_09": ("EDF Climate 411, Washington cap-and-invest Q3 2026 auction",
                       "https://blogs.edf.org/climate411/2026/09/09/washington-cap-and-invest-sees-lowest-prices-in-years-following-linkage-agreement-with-california-and-quebec/"),
    "edf_wa_2025_12": ("EDF Climate 411, Washington Q4 2025 auction",
                       "https://blogs.edf.org/climate411/2025/12/10/washingtons-fourth-cap-and-invest-auction-of-the-year-shows-strong-demand/"),
    "rggi_a72": ("RGGI Auction 72 press release, 3 Jun 2026",
                 "https://www.rggi.org/sites/default/files/Uploads/Auction-Materials/72/PR060526_Auction72.pdf"),
    "rggi_a69": ("RGGI Auction 69 press release, 3 Sep 2025",
                 "https://www.rggi.org/sites/default/files/Uploads/Auction-Materials/69/PR090525_Auction69.pdf"),
    "gccsi_45q_2025": ("Global CCS Institute, 45Q under the One Big Beautiful Bill Act (Jul 2025)",
                       "https://www.globalccsinstitute.com/u-s-preserves-and-increases-45q-credit-in-one-big-beautiful-bill-act/"),
    "aegis_2025_12": ("Aegis Hedging, LCFS and RIN pricing report, week of 15-19 Dec 2025",
                      "https://aegis-hedging.com/insights/lcfs-rin-pricing-report-through-december-22nd-2025"),
    "arb_lcfs_2025_10": ("CARB Monthly LCFS Credit Transfer Activity, Oct 2025",
                         "https://ww2.arb.ca.gov/sites/default/files/2025-11/October%202025%20-%20Monthly%20LCFS%20Credit%20Transfer%20Activity.pdf"),
    "epa_rfs_rng": ("EPA RFS: 77,000 Btu (LHV) of RNG per RIN; 11.727 RIN per MMBtu HHV is the common industry conversion",
                    "https://www.epa.gov/renewable-fuel-standard-program"),
    "eia_biomass_2025_12": ("EIA Monthly Densified Biomass Fuel Report, Dec 2025",
                            "https://www.eia.gov/biofuels/biomass/?month=12&year=2025"),
    "nass_trout_2026": ("USDA NASS Trout Production, 27 Feb 2026",
                        "https://esmis.nal.usda.gov/sites/default/release-files/795798/trpr0226.txt"),
    "nass_catfish_2026": ("USDA NASS Catfish Production, 9 Feb 2026",
                          "https://esmis.nal.usda.gov/sites/default/release-files/795763/cfpd0226.pdf"),
    "msu_tilapia_2025": ("Mississippi State Univ. Extension, MarketMaker vol 15 no 8 (Jul 2025), tilapia imports",
                         "https://extension.msstate.edu/newsletters/mississippi-marketmaker/2025/vol-15-no-8-tariffs-us-tilapia-imports-direct-revenues-and-impacts-prices"),
    "noaa_fus_2022": ("NOAA Fisheries of the United States 2022 (Oct 2024), Table 4 landings by state, imports",
                      "https://fisheries.noaa.gov/s3/2024-10/FUS-2022-final.pdf"),
    "wb_cpd_il": ("World Bank Carbon Pricing Dashboard, Israel carbon tax factsheet",
                  "https://carbonpricingdashboard.worldbank.org/compliance-factsheet/Tax_IL"),
    "ams_tomato": ("USDA AMS tomato market news report (fvdtomf)",
                   "https://www.ams.usda.gov/mnreports/fvdtomf.pdf"),
    "estimate": ("HEATBEAT team engineering estimate (see note column)", ""),
}

# ---------------------------------------------------------------------------------------------
# Transcribed source data
# ---------------------------------------------------------------------------------------------

# EIA NGA 2024, USD per thousand cubic feet (Mcf), nominal: citygate, residential, commercial, industrial.
NG_2024 = {
    "AZ": (3.29, 20.47, 11.89, 5.33), "CA": (3.79, 19.14, 14.01, 11.48), "FL": (6.58, 25.37, 12.05, 6.00),
    "GA": (3.90, 18.19, 9.33, 4.84), "IA": (4.33, 10.33, 7.69, 5.77), "IL": (3.83, 11.11, 9.30, 6.62),
    "LA": (3.91, 16.38, 10.96, 3.32), "MA": (7.43, 21.90, 15.47, 13.17), "NC": (3.59, 16.42, 8.23, 5.47),
    "NE": (4.05, 10.63, 7.30, 4.48), "NJ": (5.10, 13.21, 11.58, 8.62), "NV": (3.98, 18.69, 13.67, 10.69),
    "NY": (4.16, 16.58, 10.39, 11.75), "OH": (4.92, 13.77, 7.42, 7.73), "OK": (6.19, 13.99, 9.83, 3.03),
    "OR": (4.98, 15.71, 11.67, 6.91), "SC": (4.83, 16.91, 10.63, 4.88), "TN": (3.52, 10.75, 9.12, 4.01),
    "TX": (3.25, 17.98, 9.64, 2.52), "UT": (5.24, 13.15, 11.42, 7.75), "VA": (4.34, 15.40, 9.61, 4.35),
    "WA": (4.34, 12.72, 10.38, 12.13), "WI": (4.06, 10.14, 7.42, 5.78), "WY": (3.91, 12.39, 8.91, 4.73),
    "*": (4.25, 14.50, 10.07, 4.07),
}

# EIA Winter Fuels Outlook 2026-27, residential winter averages (forecast).
PROPANE_USD_GAL = {"Northeast": 3.28, "Midwest": 2.04, "South": 3.19, "*": 2.52}  # West not printed -> US
HEATING_OIL_USD_GAL_US = 5.26  # US only; regional not printed

# EIA RECS 2020, percent of housing units by main heating fuel: electricity, gas, propane, fuel oil.
# None = withheld (Q) or no sample (N); treated as 0 in weighting.
RECS_HEAT_MIX = {
    "AZ": (51, 36, 2, None), "CA": (20, 64, 2, None), "FL": (66, 5, None, None), "GA": (46, 47, 5, None),
    "IA": (16, 71, 13, None), "IL": (17, 78, 4, None), "LA": (62, 33, None, None), "MA": (17, 53, 3, 24),
    "NC": (62, 29, 4, None), "NE": (24, 69, None, None), "NJ": (16, 75, None, 7), "NV": (23, 68, None, None),
    "NY": (16, 61, 4, 17), "OH": (23, 64, 7, None), "OK": (39, 52, None, None), "OR": (45, 41, None, None),
    "SC": (64, 28, 5, None), "TN": (60, 35, 3, None), "TX": (51, 42, 2, None), "UT": (13, 86, None, None),
    "VA": (50, 36, 5, 4), "WA": (55, 37, None, None), "WI": (14, 71, 10, None), "WY": (18, 71, 8, None),
    "*": (34, 51, 4, 4),
}

# NOAA FUS 2022 Table 4 commercial landings: (thousand lb, thousand USD). Inland states not listed.
LANDINGS_2022 = {
    "CA": (186_229, 207_919), "FL": (109_260, 269_724), "GA": (9_882, 19_559), "LA": (912_343, 416_486),
    "MA": (190_446, 687_027), "NC": (33_779, 68_395), "NJ": (138_497, 141_848), "NY": (19_217, 38_886),
    "OR": (286_182, 132_589), "SC": (6_591, 24_652), "TX": (62_902, 169_705), "VA": (342_509, 168_983),
    "WA": (159_887, 325_410),
}

# USDA NASS 2025 foodsize trout, USD per lb (state rows printed; others withheld).
TROUT_USD_LB_2025 = {"*": 2.40, "NC": 2.72, "UT": 5.15, "WI": 6.65}

# ---------------------------------------------------------------------------------------------
# Engineering assumptions (all flagged as estimates)
# ---------------------------------------------------------------------------------------------
ASSUMPTIONS = {
    "ng_mmbtu_per_mcf": 1.036,     # EIA average heat content of delivered gas, about 1,036 Btu/cf
    "kwh_per_mmbtu": 293.07,       # unit conversion (exact)
    "kwh_per_gal_oil": 40.59,      # No. 2 heating oil 138,500 Btu/gal (EIA)
    "kwh_per_gal_propane": 26.80,  # propane 91,452 Btu/gal (EIA)
    "boiler_eff": 0.85,            # seasonal efficiency of the displaced fossil boiler (estimate, range 0.80-0.95)
    "elec_heat_cop_mix": 1.5,      # mix of resistance and heat pumps in electric-heated buildings (estimate)
    "dh_markup": (1.0, 1.15, 1.4), # district heat tariff vs. avoided gas boiler cost (estimate)
}
EF_KG_PER_MMBTU = {"gas": 53.06, "oil": 73.96, "propane": 62.87}  # EPA EF Hub, CO2 only

ROWS: list[dict] = []


def add(country, region, item, value, unit, year, category, source_id, low=None, high=None,
        is_estimate=0, note=""):
    ROWS.append(dict(country_iso2=country, region=region, item=item, value=value, low=low, high=high,
                     unit=unit, year=year, category=category, is_estimate=int(is_estimate),
                     source_id=source_id, source_url=SOURCES[source_id][1], note=note))


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def heat_cost_usd_kwh(price_per_unit: float, kwh_per_unit: float, eff: float | None = None) -> float:
    """Cost of one kWh of delivered heat from a fuel boiler."""
    return price_per_unit / (kwh_per_unit * (eff or ASSUMPTIONS["boiler_eff"]))


def ci_heat_g_kwh(fuel: str, eff: float | None = None) -> float:
    """gCO2 per kWh of delivered heat for a fossil boiler."""
    return EF_KG_PER_MMBTU[fuel] * 1000 / ASSUMPTIONS["kwh_per_mmbtu"] / (eff or ASSUMPTIONS["boiler_eff"])


def build_us() -> None:
    A = ASSUMPTIONS
    kwh_mcf = A["ng_mmbtu_per_mcf"] * A["kwh_per_mmbtu"]
    eff_lo, eff_hi = 0.95, 0.80  # better boiler -> lower avoided cost
    for st in US_STATES + ["*"]:
        cg, res, com, ind = NG_2024[st]
        for item, v in (("ng_citygate_usd_mcf", cg), ("ng_residential_usd_mcf", res),
                        ("ng_commercial_usd_mcf", com), ("ng_industrial_usd_mcf", ind)):
            add("US", st, item, v, "USD/Mcf", 2024, "fuel",
                "eia_nga_t22" if item.startswith("ng_citygate") else "eia_nga_t23")
        add("US", st, "ng_citygate_usd_mmbtu", _r(cg / A["ng_mmbtu_per_mcf"], 3), "USD/MMBtu", 2024, "fuel",
            "eia_nga_t22", note="citygate / 1.036 MMBtu per Mcf; commodity value of biogas or RNG injected without credits")

        # Heat cost of displaced boilers, USD per kWh_th
        hc = {k: heat_cost_usd_kwh(v, kwh_mcf) for k, v in (("res", res), ("com", com), ("ind", ind))}
        add("US", st, "heat_cost_gas_commercial_usd_kwh_th", _r(hc["com"]), "USD/kWh_th", 2024, "heat",
            "eia_nga_t23", low=_r(heat_cost_usd_kwh(com, kwh_mcf, eff_lo)), high=_r(heat_cost_usd_kwh(com, kwh_mcf, eff_hi)),
            is_estimate=1, note="commercial gas price / (303.6 kWh per Mcf x boiler eff 0.85; range 0.95..0.80)")
        add("US", st, "heat_cost_gas_industrial_usd_kwh_th", _r(hc["ind"]), "USD/kWh_th", 2024, "heat",
            "eia_nga_t23", low=_r(heat_cost_usd_kwh(ind, kwh_mcf, eff_lo)), high=_r(heat_cost_usd_kwh(ind, kwh_mcf, eff_hi)),
            is_estimate=1, note="industrial gas price / (303.6 kWh per Mcf x 0.85)")
        add("US", st, "heat_cost_gas_residential_usd_kwh_th", _r(hc["res"]), "USD/kWh_th", 2024, "heat",
            "eia_nga_t23", low=_r(heat_cost_usd_kwh(res, kwh_mcf, eff_lo)), high=_r(heat_cost_usd_kwh(res, kwh_mcf, eff_hi)),
            is_estimate=1, note="residential gas price / (303.6 kWh per Mcf x 0.85)")

        region = CENSUS_REGION.get(st, "*")
        prop = PROPANE_USD_GAL.get(region, PROPANE_USD_GAL["*"])
        add("US", st, "propane_residential_usd_gal", prop, "USD/gal", 2026, "fuel", "eia_wfo_2026",
            is_estimate=int(region not in PROPANE_USD_GAL),
            note=f"winter 2026-27 forecast, Census region {region}" + ("" if region in PROPANE_USD_GAL else " (West not printed, US value used)"))
        add("US", st, "heating_oil_residential_usd_gal", HEATING_OIL_USD_GAL_US, "USD/gal", 2026, "fuel",
            "eia_wfo_2026", is_estimate=int(st != "*"), note="winter 2026-27 forecast, US average (no regional value printed)")
        add("US", st, "heat_cost_propane_usd_kwh_th", _r(heat_cost_usd_kwh(prop, A["kwh_per_gal_propane"])), "USD/kWh_th",
            2026, "heat", "eia_wfo_2026", is_estimate=1, note="propane / (26.80 kWh per gal x 0.85)")
        add("US", st, "heat_cost_oil_usd_kwh_th", _r(heat_cost_usd_kwh(HEATING_OIL_USD_GAL_US, A["kwh_per_gal_oil"])),
            "USD/kWh_th", 2026, "heat", "eia_wfo_2026", is_estimate=1, note="heating oil / (40.59 kWh per gal x 0.85)")

        # Excel keys -----------------------------------------------------------------------------
        add("US", st, "p_fuel_usd_kwh", _r(hc["com"]), "USD/kWh_th", 2024, "excel_key", "eia_nga_t23",
            low=_r(min(hc.values())), high=_r(max(hc.values())), is_estimate=1,
            note="team Excel input 23. Default = commercial gas boiler heat cost; range = min..max of industrial, commercial, residential")
        steam = ind / (kwh_mcf / 1000 * A["boiler_eff"])
        add("US", st, "p_steam_usd_mwh", _r(steam, 2), "USD/MWh_th", 2024, "excel_key", "eia_nga_t23",
            low=_r(min(steam, cg / (kwh_mcf / 1000 * 0.90)), 2), high=_r(max(ind, com) / (kwh_mcf / 1000 * 0.80), 2), is_estimate=1,
            note="team Excel input 24. Fuel cost of bleed steam = industrial gas / (0.3036 MWh per Mcf x 0.85); low = citygate at 0.90, high = max(industrial, commercial) at 0.80")
        dh_lo, dh_mid, dh_hi = A["dh_markup"]
        add("US", st, "district_heat_tariff_usd_mwh_th", _r(hc["com"] * 1000 * dh_mid, 1), "USD/MWh_th", 2024,
            "heat", "estimate", low=_r(hc["com"] * 1000 * dh_lo, 1), high=_r(hc["com"] * 1000 * dh_hi, 1), is_estimate=1,
            note="SYNTHETIC: no US district heat tariff dataset; priced at avoided commercial gas boiler cost x 1.15 (range 1.0..1.4)")

        # Heating fuel mix and carbon intensity of displaced heat ------------------------------------
        e, g, p, o = (x or 0 for x in RECS_HEAT_MIX[st])
        for item, v in (("heat_mix_electricity_pct", RECS_HEAT_MIX[st][0]), ("heat_mix_gas_pct", RECS_HEAT_MIX[st][1]),
                        ("heat_mix_propane_pct", RECS_HEAT_MIX[st][2]), ("heat_mix_oil_pct", RECS_HEAT_MIX[st][3])):
            add("US", st, item, v, "% of homes", 2020, "heat_mix", "eia_recs_2020",
                note="" if v is not None else "withheld (Q) or no sample (N) in RECS; treat as about 0")
        fossil = g + p + o
        ci_mix = (g * ci_heat_g_kwh("gas") + p * ci_heat_g_kwh("propane") + o * ci_heat_g_kwh("oil")) / fossil
        add("US", st, "ci_heat_fossil_mix_g_kwh_th", _r(ci_mix, 1), "gCO2/kWh_th", 2020, "heat_mix", "eia_recs_2020",
            is_estimate=1, note="RECS fossil heating shares x EPA CO2 factors / boiler eff 0.85. Electric heat is added in heatbeat_data.market using the site grid CO2")
        add("US", st, "ci_fuel_g_kwh", _r(ci_heat_g_kwh("gas"), 1), "gCO2/kWh_th", 2024, "excel_key", "epa_ef_hub",
            low=_r(ci_heat_g_kwh("gas", 0.95), 1), high=_r(ci_mix if ci_mix > ci_heat_g_kwh("gas") else ci_heat_g_kwh("gas", 0.80), 1),
            is_estimate=1, note="team Excel input 29. Gas boiler (53.06 kg/MMBtu / 0.85), consistent with p_fuel_usd_kwh. High = fossil mix if oil heavy")

    # Fish ---------------------------------------------------------------------------------------
    for st in US_STATES:
        lb, usd = LANDINGS_2022.get(st, (0, 0))
        add("US", st, "seafood_landings_klb", lb, "1000 lb", 2022, "fish", "noaa_fus_2022",
            note="commercial landings; 0 = landlocked or Great Lakes state, not in Table 4")
        add("US", st, "seafood_landings_kusd", usd, "1000 USD", 2022, "fish", "noaa_fus_2022")
        local = "none" if lb == 0 else ("high" if usd >= 150_000 else ("medium" if usd >= 50_000 else "low"))
        prem = {"none": (0.10, 0.0, 0.25), "low": (0.05, 0.0, 0.15), "medium": (0.0, -0.05, 0.10),
                "high": (-0.05, -0.15, 0.05)}[local]
        add("US", st, "fish_local_price_premium", prem[0], "fraction vs US price", 2022, "fish", "estimate",
            low=prem[1], high=prem[2], is_estimate=1,
            note=f"SYNTHETIC: local supply class '{local}' from NOAA landings value; inland states pay more for fresh fish")
    add("US", "*", "seafood_import_share_pct", 86, "% of consumption", 2022, "fish", "noaa_fus_2022", low=75, high=90)
    add("US", "*", "seafood_per_capita_lb", 19.7, "lb/person/yr", 2022, "fish", "noaa_fus_2022")
    add("US", "*", "tilapia_import_usd_lb", 1.75, "USD/lb", 2024, "fish", "msu_tilapia_2025", low=1.50, high=2.00,
        note="imputed average import price, all product forms; fluctuated 1.50..2.00 since 2015")
    add("US", "*", "catfish_farmgate_usd_lb", 1.11, "USD/lb live", 2025, "fish", "nass_catfish_2026", low=1.10, high=1.11,
        note="foodsize, US average price paid to producers; 2024 = 1.10")
    for st, v in TROUT_USD_LB_2025.items():
        add("US", st, "trout_farmgate_usd_lb", v, "USD/lb", 2025, "fish", "nass_trout_2026",
            note="foodsize (12 in +) average price per lb")
    add("US", "*", "shellfish_aquaculture_usd_lb", 8.07, "USD/lb", 2022, "fish", "noaa_fus_2022", low=6.69, high=16.30,
        note="derived: value / volume of oysters, clams, mussels (oysters 6.69, mussels 16.30)")

    # Carbon value ---------------------------------------------------------------------------------
    rggi_t = 35.00 / 0.90718  # short ton -> metric ton
    compliance = {"CA": (28.32, 25.87, 29.61, "arb_auction_2025_11", "CA-QC cap-and-trade, Nov 2025 current vintage; low = reserve price"),
                  "WA": (39.50, 27.92, 70.86, "edf_wa_2026_09", "WA cap-and-invest Q3 2026; high = Q4 2025 (70.86)"),
                  "MA": (rggi_t, 22.25 / 0.90718, rggi_t, "rggi_a72", "RGGI Auction 72 (Jun 2026) 35.00 USD per short ton; low = Auction 69 (Sep 2025). Power sector only"),
                  "NJ": (rggi_t, 22.25 / 0.90718, rggi_t, "rggi_a72", "RGGI, power sector only"),
                  "NY": (rggi_t, 22.25 / 0.90718, rggi_t, "rggi_a72", "RGGI, power sector only"),
                  "VA": (0.0, 0.0, rggi_t, "rggi_a72", "ESTIMATE: Virginia left RGGI end of 2023, rejoining is under discussion; high = RGGI price if it rejoins")}
    for st in US_STATES + ["*"]:
        v, lo, hi, src, note = compliance.get(st, (0.0, 0.0, 0.0, "estimate", "no state carbon market"))
        add("US", st, "co2_compliance_usd_t", _r(v, 2), "USD/tCO2", 2026, "carbon", src, low=_r(lo, 2), high=_r(hi, 2),
            is_estimate=int(st in ("VA",) or src == "estimate"),
            note=note + ". Mostly already inside fuel and power prices: do not add on top of p_fuel/p_elec")
    add("US", "*", "credit_45q_point_source_usd_t", 85, "USD/tCO2", 2025, "carbon", "gccsi_45q_2025",
        note="geologic storage; since OBBBA utilization and EOR get the same value")
    add("US", "*", "credit_45q_dac_usd_t", 180, "USD/tCO2", 2025, "carbon", "gccsi_45q_2025", note="DAC with geologic storage")
    for st in US_STATES + ["*"]:
        lcfs = 53.37 if st == "CA" else 0.0
        add("US", st, "p_dac_credit_usd_ton", 180.0, "USD/tCO2", 2025, "excel_key", "gccsi_45q_2025",
            low=0.0, high=_r(180 + lcfs, 2), is_estimate=1,
            note="45Q credit for DAC with geologic storage; low = no storage access; high CA = 45Q + LCFS credit")
        v, lo, hi, src, note = compliance.get(st, (0.0, 0.0, 0.0, "estimate", "no state carbon market"))
        add("US", st, "p_co2_usd_ton", _r(v, 2), "USD/tCO2", 2026, "excel_key", src, low=_r(lo, 2), high=_r(hi, 2),
            is_estimate=1, note="team Excel input 26, used as value of avoided emissions = state compliance carbon price "
            "(0 without a state market). Partly embedded in fuel and power prices already")

    # Fuel credits (biogas / RNG) ----------------------------------------------------------------------
    add("US", "*", "rin_d3_usd", 2.452, "USD/RIN", 2025, "credits", "aegis_2025_12", low=2.40, high=2.452,
        note="Dec 2025 monthly average; D3 = cellulosic, includes RNG from landfill, digesters")
    add("US", "*", "rin_d5_usd", 1.119, "USD/RIN", 2025, "credits", "aegis_2025_12", note="Dec 2025 monthly average")
    add("US", "*", "rng_rins_per_mmbtu", 11.727, "RIN/MMBtu", 2025, "credits", "epa_rfs_rng")
    add("US", "*", "rng_d3_value_usd_mmbtu", _r(2.452 * 11.727, 2), "USD/MMBtu", 2025, "credits", "aegis_2025_12",
        low=_r(2.40 * 11.727 * 0.5, 2), high=_r(2.452 * 11.727, 2), is_estimate=1,
        note="only if RNG is sold as transport fuel; low = 50 % RIN realisation after marketing share")
    add("US", "CA", "lcfs_credit_usd_t", 53.37, "USD/tCO2", 2025, "credits", "aegis_2025_12", low=53.37, high=64.0,
        note="Dec 2025 average; ARB Oct 2025 average 58, CY2024 64")
    add("US", "OR", "lcfs_credit_usd_t", 157.50, "USD/tCO2", 2025, "credits", "aegis_2025_12",
        note="Oregon Clean Fuels Program credit, Dec 2025 average")

    # Greenhouse produce -------------------------------------------------------------------------------
    add("US", "*", "tomato_greenhouse_usd_lb", 1.45, "USD/lb", 2026, "produce", "ams_tomato", low=0.65, high=2.20,
        is_estimate=1, note="derived from USDA AMS Tomato Fax terminal prices, greenhouse vine ripes: 15 lb flats 12-15 USD "
        "(17 Nov 2025) to 28-32 USD (22 Oct 2026), 11 lb TOV flats 7-24 USD; Boston, Chicago, LA, NY, Philadelphia similar. "
        "Strongly seasonal; mostly imported from Canada and Mexico")
    add("US", "*", "tomato_field_roma_usd_lb", 1.25, "USD/lb", 2026, "produce", "ams_tomato", low=0.90, high=1.75,
        is_estimate=1, note="derived: ROMA 25 lb cartons, shipping point 23-35 USD, terminal 32-48 USD (Nov 2025, Oct 2026)")

    # Biomass / drying products ------------------------------------------------------------------------
    add("US", "*", "wood_pellet_domestic_usd_ton", 239.25, "USD/short ton", 2025, "biomass", "eia_biomass_2025_12",
        note="densified biomass, domestic sales Dec 2025")
    add("US", "*", "wood_pellet_export_usd_ton", 202.74, "USD/short ton", 2025, "biomass", "eia_biomass_2025_12")


def build_il() -> None:
    # Israel: national rows only, mostly estimates.
    nis_per_usd = 3.6  # ESTIMATE, Nov 2026 order of magnitude
    t_co2_per_t_gas = 2.75  # CH4 combustion, approx
    add("IL", "*", "co2_tax_gas_2030_usd_t", _r(192 / t_co2_per_t_gas / nis_per_usd, 2), "USD/tCO2", 2030, "carbon",
        "wb_cpd_il", low=0.0, high=_r(192 / t_co2_per_t_gas / nis_per_usd, 2), is_estimate=1,
        note="ESTIMATE: Israel carbon tax on natural gas rises to 192 NIS per t of gas by 2030 (2024 prices), converted at 2.75 tCO2/t and 3.6 NIS/USD")


def main(write: bool = True) -> pd.DataFrame:
    ROWS.clear()
    build_us()
    build_il()
    df = pd.DataFrame(ROWS)
    assert not df.duplicated(["country_iso2", "region", "item"]).any()
    if not write:
        return df
    df.to_csv(OUT, index=False)
    print(f"wrote {len(df)} rows to {OUT}")
    return df


if __name__ == "__main__":
    main()
