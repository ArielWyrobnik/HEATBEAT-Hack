"""Every engineering and cost parameter of the heat chain model, with range, unit, status and source.

status:
  physics      follows from thermodynamics or a property table, not a choice
  literature   typical value from the cited source (range = spread reported there)
  assumption   team choice or estimate. UNVERIFIED, flagged in every output

Ranges (low, high) feed the tornado. CAPEX values are screening level (+/- 40 %), USD 2025.
Several literature values are quoted from the cited handbooks and catalogues without re-checking
the latest edition in this session; those carry status "literature" and the note "check edition".
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    value: float
    low: float
    high: float
    unit: str
    status: str
    source: str


P = Param
PARAMS: dict[str, Param] = {
    # ---- physical constants -----------------------------------------------------------------
    "cp_water_kj_kgk": P(4.18, 4.18, 4.18, "kJ/kg K", "physics", "IAPWS water at 20 to 80 C"),
    "h_fg_mj_kg": P(2.43, 2.40, 2.45, "MJ/kg", "physics", "Latent heat of water at 25 to 35 C (steam tables)"),
    "rho_water_kg_m3": P(990.0, 980, 1000, "kg/m3", "physics", "Water at 20 to 60 C"),
    "ng_kg_co2_per_mwh_fuel": P(181.0, 181, 181, "kg/MWh_fuel", "literature",
                                "EPA GHG Emission Factors Hub: 53.06 kg CO2/MMBtu natural gas = 181 kg/MWh (HHV)"),
    # ---- heat rejection ("radiator") ---------------------------------------------------------
    "dry_approach_k": P(6.0, 4.0, 8.0, "K", "literature",
                        "Dry cooler approach (leaving fluid minus dry bulb) 4 to 8 K at design, ASHRAE Handbook "
                        "HVAC Systems and Equipment ch. 40 / manufacturer selections (check edition)"),
    "adiabatic_eff": P(0.80, 0.70, 0.90, "-", "literature",
                       "Evaporative pad saturation efficiency 70 to 90 %, ASHRAE Handbook HVAC Systems and Equipment ch. 41"),
    "adiabatic_air_range_k": P(10.0, 8.0, 14.0, "K", "assumption",
                               "Air temperature rise across the coil at design; sets air mass flow and spray water"),
    "tower_approach_k": P(4.0, 3.0, 6.0, "K", "literature",
                          "Cooling tower approach to wet bulb 3 to 6 K, CTI / ASHRAE Handbook ch. 40 (check edition)"),
    "tower_hx_approach_k": P(1.5, 1.0, 2.5, "K", "assumption", "Plate heat exchanger between open tower and IT loop"),
    "tower_latent_share": P(0.85, 0.75, 0.90, "-", "literature",
                            "Share of tower heat leaving as latent heat (rest sensible), ASHRAE Handbook ch. 40"),
    "tower_cycles": P(4.0, 3.0, 6.0, "-", "literature",
                      "Cycles of concentration 3 to 6; blowdown = evaporation / (cycles - 1), ASHRAE Handbook ch. 40"),
    "sfp_dry_kw_kw": P(0.030, 0.020, 0.045, "kW_e/kW_th", "assumption",
                       "Dry cooler fan power at design load (EC fans). Manufacturer selections span 0.02 to 0.045"),
    "sfp_adiabatic_kw_kw": P(0.025, 0.018, 0.035, "kW_e/kW_th", "assumption", "Adiabatic cooler fan power at design"),
    "sfp_tower_kw_kw": P(0.012, 0.008, 0.018, "kW_e/kW_th", "literature",
                         "ASHRAE 90.1 minimum axial tower efficiency 40.2 gpm/hp at 95/85/75 F, about 0.01 kW_e/kW_th"),
    "pump_kw_kw": P(0.010, 0.006, 0.015, "kW_e/kW_th", "assumption", "Condenser / facility water pumps"),
    "chiller_carnot_fraction": P(0.50, 0.40, 0.60, "-", "literature",
                                 "Centrifugal chillers reach 50 to 60 % of Carnot at full load (ASHRAE Handbook)"),
    "chiller_lift_extra_k": P(3.0, 2.0, 5.0, "K", "assumption", "Evaporator plus condenser approach of the trim chiller"),
    "chiller_cop_max": P(7.0, 5.0, 9.0, "-", "assumption",
                           "Cap at small lifts, plant level incl. chilled water pumps (ASHRAE 90.1 path B full load about 5.6 to 6.3)"),
    "hall_fan_kw_kw": P(0.04, 0.02, 0.06, "kW_e/kW_th air side", "assumption",
                        "CRAH / fan wall power per kW of heat removed by air inside the hall (same in every chain)"),
    "other_overhead_share": P(0.06, 0.04, 0.10, "of IT", "assumption",
                              "UPS, transformer, lighting losses; PUE = 1 + cooling + this share"),
    # ---- heat pump --------------------------------------------------------------------------
    "hp_carnot_fraction": P(0.50, 0.40, 0.60, "-", "literature",
                            "Industrial heat pumps reach 40 to 60 % of Carnot COP, Arpagaus et al. 2018, Energy 152, 985-1010"),
    "hp_approach_k": P(2.5, 2.0, 5.0, "K", "assumption", "Approach per heat exchanger (evaporator and condenser)"),
    "hp_evap_drop_k": P(5.0, 3.0, 8.0, "K", "assumption", "Source water cooled by this much in the evaporator"),
    "hp_cop_max": P(8.0, 6.0, 10.0, "-", "assumption", "Cap for small lifts"),
    "hx_approach_k": P(3.0, 2.0, 5.0, "K", "assumption", "Direct heat exchanger approach (no heat pump)"),
    # ---- district heating -------------------------------------------------------------------
    "dh_supply_c": P(70.0, 60.0, 85.0, "C", "literature",
                     "4th generation DH supply 55 to 70 C, Lund et al. 2014, Energy 68, 1-11; 3rd gen 80 to 90 C"),
    "dh_return_c": P(40.0, 30.0, 45.0, "C", "literature", "4GDH return 25 to 40 C, Lund et al. 2014"),
    "dh_ground_c": P(10.0, 5.0, 18.0, "C", "assumption", "Soil temperature at 1 m; replaced by annual mean air if available"),
    "dh_velocity_ms": P(2.0, 1.5, 3.0, "m/s", "literature", "Design velocity for DN 200 to 600 transmission, Frederiksen and Werner 2013"),
    "dh_dp_pa_m": P(100.0, 80.0, 200.0, "Pa/m", "literature",
                    "Design specific pressure drop 100 Pa/m, Frederiksen and Werner, District Heating and Cooling, 2013"),
    "dh_pump_eff": P(0.70, 0.60, 0.80, "-", "assumption", "Pump and motor efficiency"),
    "dh_u_a_w_mk": P(0.12, 0.10, 0.16, "W/m K", "assumption",
                     "Pre-insulated steel pipe (EN 253), series 2: U' about 0.12 + 0.0008 x DN(mm) W/m K per pipe. "
                     "Linear fit to manufacturer tables, UNVERIFIED"),
    "dh_u_b_w_mk_per_mm": P(0.0008, 0.0006, 0.0010, "W/m K per mm", "assumption", "See dh_u_a_w_mk"),
    "dh_dist_loss_share": P(0.12, 0.08, 0.20, "-", "literature",
                            "Distribution network heat loss 8 to 20 % of delivered heat, Frederiksen and Werner 2013"),
    "dh_dhw_share": P(0.20, 0.15, 0.30, "-", "assumption", "Hot water share of annual community heat demand (flat over the year)"),
    "dh_hdh_base_c": P(16.0, 15.0, 18.0, "C", "literature", "Heating degree hour base temperature (EN ISO 15927-6 uses 15.5 to 18 C)"),
    "dh_network_km": P(20.0, 5.0, 60.0, "km", "assumption",
                       "Community distribution network length served. Annual demand = rho_heat x length"),
    "dh_max_transmission_km": P(20.0, 10.0, 30.0, "km", "assumption", "Longer transmission lines are rare (KO above)"),
    "dh_heat_price_share": P(0.85, 0.70, 1.00, "-", "assumption",
                             "Heat sells at this share of the customers' avoided gas heat cost (competitive offer)"),
    # ---- storage ----------------------------------------------------------------------------
    "ates_recovery": P(0.75, 0.60, 0.90, "-", "literature", "ATES heat recovery 60 to 90 %, Fleuchaus et al. 2018, RSER 94, 861-876"),
    "btes_recovery": P(0.55, 0.40, 0.70, "-", "literature", "BTES heat recovery 40 to 70 % (Drake Landing about 50 %), Fleuchaus 2018"),
    "storage_min_shift_share": P(0.01, 0.005, 0.05, "of annual demand", "assumption",
                                 "Storage must shift at least this share of the community demand, else it is not built (KO)"),
    "storage_min_geo_score": P(3.0, 2.0, 4.0, "score", "assumption", "geo_storage_score needed for ATES/BTES"),
    # ---- sorption chilling ------------------------------------------------------------------
    "ads_cop": P(0.55, 0.45, 0.65, "-", "literature",
                 "Silica gel / water adsorption chillers COP 0.5 to 0.65 at 55 to 65 C drive (manufacturer data, e.g. "
                 "Fahrenheit eCoo, InvenSor). UNVERIFIED for 2025 products"),
    "ads_min_drive_c": P(50.0, 45.0, 55.0, "C", "literature", "Lowest useful drive temperature of adsorption chillers"),
    "ads_max_cond_c": P(32.0, 30.0, 35.0, "C", "literature", "Adsorption chiller recooling water must stay below about 32 C"),
    "abs_cop": P(0.70, 0.65, 0.75, "-", "literature", "Single effect LiBr COP 0.7, Herold, Radermacher and Klein, Absorption Chillers and Heat Pumps"),
    "abs_min_drive_c": P(75.0, 70.0, 85.0, "C", "literature", "Single effect LiBr needs 75 to 90 C drive (same source)"),
    # ---- biogas digester --------------------------------------------------------------------
    "bio_feed_t_day": P(300.0, 100.0, 600.0, "t/day", "assumption",
                        "Reference co-digestion plant (manure + food waste). Site feedstock quantity is NOT in the data"),
    "bio_biogas_nm3_t": P(60.0, 30.0, 110.0, "Nm3/t", "literature",
                          "Biogas yield per wet tonne: manure 20 to 30, food waste 100 to 150 (IEA Bioenergy Task 37). Mix value assumed"),
    "bio_ch4_share": P(0.60, 0.55, 0.65, "-", "literature", "Methane share of biogas, IEA Bioenergy Task 37"),
    "bio_meso_c": P(38.0, 35.0, 40.0, "C", "literature", "Mesophilic 35 to 40 C, Metcalf and Eddy, Wastewater Engineering"),
    "bio_thermo_c": P(55.0, 50.0, 57.0, "C", "literature", "Thermophilic 50 to 57 C, Metcalf and Eddy"),
    "bio_thermo_yield_gain": P(0.05, 0.0, 0.15, "-", "assumption", "Extra methane yield of thermophilic operation"),
    "bio_wall_u_w_m2k": P(0.40, 0.25, 0.70, "W/m2 K", "literature", "Insulated digester wall and roof 0.3 to 0.7 W/m2K, Metcalf and Eddy"),
    "bio_hrt_days": P(25.0, 15.0, 30.0, "days", "literature", "Hydraulic retention time 15 to 30 days, Metcalf and Eddy"),
    "bio_boiler_eff": P(0.85, 0.80, 0.90, "-", "assumption", "Baseline: digester heated by a biogas boiler"),
    "bio_truck_usd_t_km": P(0.20, 0.10, 0.35, "USD/t km", "assumption", "Bulk feedstock trucking, round trip included"),
    "bio_max_km": P(50.0, 30.0, 80.0, "km", "assumption", "Heat line or feedstock trucking beyond this is not feasible (KO)"),
    "bio_upgrade_capex_usd_nm3h": P(4000.0, 2500.0, 6000.0, "USD per Nm3/h raw biogas", "assumption",
                                    "Biogas upgrading to RNG (membrane or water scrubber) incl. grid injection, sized for the "
                                    "freed biogas flow. Small plants 2500 to 6000 USD per Nm3/h (order of magnitude from IEA "
                                    "Bioenergy Task 37 upgrading reports). UNVERIFIED, check"),
    "bio_upgrade_kwh_nm3": P(0.25, 0.15, 0.35, "kWh_e/Nm3 raw biogas", "assumption",
                             "Electricity of the upgrading unit (membrane / water scrubber 0.2 to 0.3, IEA Bioenergy Task 37). UNVERIFIED"),
    "capex_digester_usd_m3": P(600.0, 400.0, 1000.0, "USD/m3 digester volume", "assumption",
                               "New digester incl. feeding and gas storage, only when feedstock is trucked to a digester at the "
                               "data center (the heat line case heats the existing plant). UNVERIFIED"),
    "bio_ch4_kwh_nm3": P(9.97, 9.97, 9.97, "kWh/Nm3", "physics", "Methane LHV"),
    "rng_ci_g_mj": P(20.0, -50.0, 40.0, "g CO2e/MJ", "assumption",
                     "Carbon intensity of the RNG pathway for LCFS (food waste about 0 to 40; dairy manure negative)"),
    "lcfs_ref_ci_g_mj": P(90.0, 85.0, 95.0, "g CO2e/MJ", "literature", "CARB LCFS diesel benchmark about 90 g/MJ"),
    # ---- boiler feedwater -------------------------------------------------------------------
    "p_wholesale_share": P(1.0, 0.8, 1.2, "-", "assumption", "Power plant output valued at the mean hourly market price x this"),
    "fw_target_c": P(50.0, 45.0, 60.0, "C", "assumption", "Condensate / makeup water preheated to this temperature"),
    "fw_capacity_factor": P(0.55, 0.30, 0.80, "-", "assumption", "Share of hours the steam plant runs"),
    "fw_kwh_e_per_kwh_th": P(0.15, 0.10, 0.25, "-", "assumption",
                             "Extra turbine output per kWh of displaced low pressure extraction steam"),
    "fw_max_km": P(15.0, 5.0, 25.0, "km", "assumption", "KO above"),
    # ---- desalination -----------------------------------------------------------------------
    "med_dt_per_effect_k": P(3.0, 2.5, 4.0, "K", "literature",
                             "Temperature drop per MED effect incl. boiling point elevation 2.5 to 4 K, El-Dessouky and Ettouney 2002"),
    "med_gor_per_effect": P(0.85, 0.80, 0.90, "-", "literature", "GOR about 0.85 x number of effects (same source)"),
    "med_kwh_e_m3": P(2.0, 1.5, 2.5, "kWh_e/m3", "literature", "MED pumping 1.5 to 2.5 kWh/m3, Al-Karaghouli and Kazmerski 2013, RSER 24"),
    "md_gor": P(2.0, 1.0, 5.0, "-", "literature", "Membrane distillation GOR 1 to 5 at pilot scale, Deshmukh et al. 2018, EES 11"),
    "md_kwh_e_m3": P(1.5, 1.0, 3.0, "kWh_e/m3", "assumption", ""),
    "ro_kwh_e_m3": P(3.5, 3.0, 4.0, "kWh_e/m3", "literature", "SWRO 3 to 4 kWh/m3, Al-Karaghouli and Kazmerski 2013"),
    "sea_above_air_k": P(2.0, 0.0, 5.0, "K", "assumption", "Annual mean seawater minus annual mean air temperature"),
    "desal_max_coast_km": P(10.0, 5.0, 30.0, "km", "assumption", "Intake and brine outfall beyond this: KO"),
    "desal_water_value_share": P(1.0, 0.6, 1.0, "-", "assumption", "Water sells at this share of the local tariff"),
    # ---- ORC --------------------------------------------------------------------------------
    "orc_carnot_fraction": P(0.40, 0.30, 0.50, "-", "literature",
                             "Low temperature ORC reach 30 to 50 % of Carnot, Quoilin et al. 2013, RSER 22, 168-186"),
    "orc_cond_above_air_k": P(10.0, 7.0, 15.0, "K", "assumption", "Air cooled ORC condenser"),
    "orc_min_source_c": P(80.0, 70.0, 90.0, "C", "literature",
                          "Below this loop temperature no ORC is offered. Vertiv ORC testbed (Tipton, Kremer, Ali, "
                          "white paper 'Experimental lessons of an Organic Rankine Cycle'): with liquid cooled servers "
                          "at 58 to 63 C the net power incl. condenser fan and pump was negative in every test; the "
                          "ORC needs T_hot >= T_amb,max + 40 K (about 84 C for Ashburn). Was 45 C (team assumption) "
                          "until the validation in docs/VALIDATION.md"),
    "orc_min_dt_k": P(20.0, 15.0, 25.0, "K", "assumption", "Below this source minus condenser difference no ORC is built"),
    # ---- economics --------------------------------------------------------------------------
    "discount_rate": P(0.07, 0.05, 0.10, "-", "assumption", "Real discount rate"),
    "lifetime_yr": P(20.0, 15.0, 25.0, "yr", "assumption", ""),
    "capex_factor": P(1.0, 0.6, 1.4, "-", "assumption", "Multiplies every CAPEX below (screening accuracy +/- 40 %)"),
    "water_scarcity_usd_m3_per_wsi": P(0.5, 0.0, 1.5, "USD/m3 per WSI point", "assumption",
                                       "Shadow price added to the tariff: WSI 0 to 5 times this. Makes water stress count"),
    "capex_dry_usd_kw": P(90.0, 60, 130, "USD/kW_th", "assumption", "Dry cooler installed. UNVERIFIED"),
    "capex_adiabatic_usd_kw": P(110.0, 80, 160, "USD/kW_th", "assumption", "Adiabatic cooler installed. UNVERIFIED"),
    "capex_tower_usd_kw": P(70.0, 45, 100, "USD/kW_th", "assumption", "Cooling tower + water treatment. UNVERIFIED"),
    "capex_hp_usd_kw": P(700.0, 400, 1000, "USD/kW_th", "literature",
                         "Large electric heat pumps 0.4 to 1.0 M USD/MW_th, Danish Energy Agency Technology Data "
                         "(generation of electricity and district heating), check edition"),
    "capex_hx_usd_kw": P(60.0, 30, 100, "USD/kW_th", "assumption", "Plate heat exchanger and connection"),
    "capex_pipe_usd_m_a": P(500.0, 300, 800, "USD/m", "assumption",
                            "Twin pipe trench cost = a + b x DN(mm). Catalogue 1 to 3 M USD/km for DH (UNVERIFIED)"),
    "capex_pipe_usd_m_b": P(3.0, 2.0, 4.5, "USD/m per mm", "assumption", "See capex_pipe_usd_m_a"),
    "capex_dist_network_usd_m": P(800.0, 500, 1500, "USD/m", "assumption", "Community distribution network incl. substations"),
    "capex_ates_usd_kwh": P(1.0, 0.5, 2.0, "USD/kWh capacity", "assumption", "ATES wells. Danish Energy Agency storage catalogue range (check)"),
    "capex_btes_usd_kwh": P(2.0, 1.0, 4.0, "USD/kWh capacity", "assumption", "BTES boreholes (check)"),
    "capex_tank_usd_kwh": P(3.0, 1.5, 6.0, "USD/kWh capacity", "assumption",
                            "Large steel tank, daily cycling. Danish Energy Agency storage catalogue range (check)"),
    "capex_ads_usd_kw": P(650.0, 450, 900, "USD/kW_cold", "assumption", "Adsorption chiller installed. UNVERIFIED"),
    "capex_abs_usd_kw": P(400.0, 300, 600, "USD/kW_cold", "assumption", "LiBr absorption chiller installed. UNVERIFIED"),
    "capex_med_usd_m3d": P(2000.0, 1500, 2800, "USD per m3/day", "literature", "MED 1500 to 2500 USD/(m3/d), Al-Karaghouli and Kazmerski 2013"),
    "capex_md_usd_m3d": P(2500.0, 1800, 3500, "USD per m3/day", "assumption", "MD pilot scale. UNVERIFIED"),
    "capex_orc_usd_kwe": P(3000.0, 2000, 4500, "USD/kW_e", "literature", "Small low temperature ORC 2000 to 4500 USD/kW_e, Quoilin 2013"),
    "opex_share": P(0.02, 0.01, 0.04, "of CAPEX per yr", "assumption", "Fixed O&M"),
}


def defaults() -> dict[str, float]:
    return {k: p.value for k, p in PARAMS.items()}


def table():
    import pandas as pd
    return pd.DataFrame([{"param": k, **p.__dict__} for k, p in PARAMS.items()])
