/**
 * Real data centers where heat reuse already happens (see ./ecosystem.ts), shown as reference pins.
 * They are evaluated entirely in the browser: published facts where they exist ("real"), otherwise
 * clearly flagged estimates. No backend call is needed for these pins.
 */
import type { Baseline, Flag, InputValue, SiteInputs, SiteSummary } from '../types/api';

interface Fact { value: number | string; flag: Flag; source: string }
type Country = 'NO' | 'FI' | 'SE' | 'NL' | 'FR' | 'US-WA' | 'US-NY' | 'GB' | 'IE' | 'US-ND' | 'US-VA' | 'US-HI';

export interface ReferenceSite {
  id: string;
  name: string;
  operator: string;
  city: string;
  country: string;
  lat: number;
  lng: number;
  region: Country;
  /** pathways this site demonstrates (keys of ECOSYSTEM) */
  pathways: string[];
  it_mw: Fact;
  pue: Fact;
  /** overrides of the 31 inputs, with source */
  facts: Record<string, Fact>;
  note?: string;
  /** rough climate summary, used only if Open-Meteo cannot be reached (then flagged synthetic) */
  climate: { t_db_mean_c: number; t_db_min_c: number; t_db_max_c: number; warmest_month: number };
}

const EST = (value: number | string, source: string): Fact => ({ value, flag: 'estimated', source });
const REAL = (value: number | string, source: string): Fact => ({ value, flag: 'real', source });

/** Planning defaults (the Team Excel defaults), flagged estimated. */
const DEFAULTS: Record<string, number | string> = {
  is_greenfield: 0, cooling_type: 'air', t_dc_base_c: 30, slope_deg: 2, flat_land_m2: 10000, d_water_m: 2000,
  wsi_index: 1, has_existing_dh: 0, d_dh_m: 5000, rho_heat_mwh_m: 1, d_coast_m: 100000, dz_m: 50, d_bio_m: 15000,
  d_co2_m: 100000, d_pp_m: 5000, q_fw_mw: 0, ind_zoning: 1, campus_area_m2: 0, agri_land_m2: 0, geo_storage_score: 3,
  p_steam_usd_mwh: 15, p_water_usd_m3: 2, d_market_m: 50000, eco_sens_index: 2, mit_tier: 'med',
};

/*
 * Country / state values, researched November 2026. USD conversions use ECB reference rates of
 * 17 Nov 2026: 1 EUR = 1.0989 USD, 1 GBP = 1.3191 USD. Gas is converted at 1 Mcf = 304 kWh.
 */
const EUR = 1.0989, GBP = 1.3191;
const r3 = (x: number) => Math.round(x * 1000) / 1000;
const S = {
  eurostatElec: 'Eurostat nrg_pc_205, non-household 500–2,000 MWh/yr',
  eurostatGas: 'Eurostat nrg_pc_203, non-household, H1 2026',
  ember: 'Ember 2025 lifecycle grid intensity (via Our World in Data)',
  eua: 'EU ETS: Platts nearest-Dec 2026 EUA €86.69/t on 6 Nov 2026',
  aqueduct: 'WRI Aqueduct 4.0 country baseline water stress (0–5)',
  ipcc: 'IPCC 2006 default for natural gas, 56.1 t CO2/TJ',
};
const euaUsd = r3(86.69 * EUR);
const GAS_CI = REAL(202, S.ipcc);

const COUNTRY: Record<Country, Record<'p_elec_usd_kwh' | 'p_fuel_usd_kwh' | 'ci_grid_g_kwh' | 'ci_fuel_g_kwh' | 'wsi_index' | 'p_co2_usd_ton', Fact>> = {
  NO: {
    p_elec_usd_kwh: EST(0.07, 'SSB: industry power about 50 øre/kWh before grid rent and tax; grid and reduced data center tax added as estimate'),
    p_fuel_usd_kwh: EST(0.08, 'Norway has almost no gas network; displaced heat valued as an estimate'),
    ci_grid_g_kwh: REAL(28, `${S.ember}: Norway 28 g/kWh`), ci_fuel_g_kwh: GAS_CI,
    wsi_index: REAL(0.2, `${S.aqueduct}: Norway 0.20`), p_co2_usd_ton: REAL(euaUsd, `${S.eua} (Norway is in the EU ETS)`),
  },
  FI: {
    p_elec_usd_kwh: REAL(r3(0.0748 * EUR), `${S.eurostatElec}, H2 2025: Finland €0.0748/kWh`),
    p_fuel_usd_kwh: REAL(r3(0.09 * EUR), `${S.eurostatGas}: Finland €0.09/kWh`),
    ci_grid_g_kwh: REAL(57, `${S.ember}: Finland 57 g/kWh`), ci_fuel_g_kwh: GAS_CI,
    wsi_index: REAL(0.85, `${S.aqueduct}: Finland 0.85`), p_co2_usd_ton: REAL(euaUsd, S.eua),
  },
  SE: {
    p_elec_usd_kwh: REAL(r3(0.097 * EUR), `${S.eurostatElec}, H2 2025: Sweden €0.0970/kWh`),
    p_fuel_usd_kwh: REAL(r3(0.11 * EUR), `${S.eurostatGas}: Sweden €0.11/kWh`),
    ci_grid_g_kwh: REAL(35, `${S.ember}: Sweden 35 g/kWh`), ci_fuel_g_kwh: GAS_CI,
    wsi_index: REAL(0.79, `${S.aqueduct}: Sweden 0.79`), p_co2_usd_ton: REAL(euaUsd, S.eua),
  },
  NL: {
    p_elec_usd_kwh: REAL(r3(0.2046 * EUR), `${S.eurostatElec}, H1 2025: Netherlands €0.2046/kWh`),
    p_fuel_usd_kwh: REAL(r3(0.08 * EUR), `${S.eurostatGas}: Netherlands €0.08/kWh`),
    ci_grid_g_kwh: REAL(254, `${S.ember}: Netherlands 254 g/kWh`), ci_fuel_g_kwh: GAS_CI,
    wsi_index: REAL(1.6, `${S.aqueduct}: Netherlands 1.60`), p_co2_usd_ton: REAL(euaUsd, S.eua),
  },
  FR: {
    p_elec_usd_kwh: REAL(r3(0.149 * EUR), 'GlobalPetrolPrices: France business electricity €0.149/kWh'),
    p_fuel_usd_kwh: EST(r3(0.06 * EUR), `${S.eurostatGas}: EU average €0.06/kWh (France not itemised)`),
    ci_grid_g_kwh: REAL(41, `${S.ember}: France 41 g/kWh`), ci_fuel_g_kwh: GAS_CI,
    wsi_index: EST(1.5, 'Aqueduct 4.0 France score not retrieved; planning estimate'), p_co2_usd_ton: REAL(euaUsd, S.eua),
  },
  'US-WA': {
    p_elec_usd_kwh: REAL(0.0661, 'EIA 2024: Washington industrial 6.61 ¢/kWh'),
    p_fuel_usd_kwh: REAL(r3(12.13 / 304), 'EIA Natural Gas Annual 2024: Washington industrial $12.13/Mcf'),
    ci_grid_g_kwh: REAL(113, 'EIA Washington electricity profile 2024: 249 lb CO2/MWh'), ci_fuel_g_kwh: GAS_CI,
    wsi_index: EST(1.5, 'Aqueduct 4.0 state score not retrieved; planning estimate'),
    p_co2_usd_ton: REAL(39.5, 'Washington Cap-and-Invest auction, Sept 2026: $39.50/allowance'),
  },
  'US-NY': {
    p_elec_usd_kwh: REAL(0.0917, 'EIA 2024: New York industrial 9.17 ¢/kWh'),
    p_fuel_usd_kwh: REAL(r3(11.75 / 304), 'EIA Natural Gas Annual 2024: New York industrial $11.75/Mcf'),
    ci_grid_g_kwh: REAL(244, 'EIA New York electricity profile 2024: 537 lb CO2/MWh'), ci_fuel_g_kwh: GAS_CI,
    wsi_index: EST(1.0, 'Aqueduct 4.0 state score not retrieved; planning estimate'),
    p_co2_usd_ton: EST(0, 'No carbon price on heating fuel in New York (RGGI covers power plants only)'),
  },
  IE: {
    p_elec_usd_kwh: REAL(r3(0.2552 * EUR), `${S.eurostatElec}, H2 2025: Ireland €0.2552/kWh (highest in the EU)`),
    p_fuel_usd_kwh: EST(r3(0.0605 * EUR), 'Eurostat nrg_pc_203, H2 2025: EU average €0.0605/kWh (Ireland not itemised here)'),
    ci_grid_g_kwh: REAL(197, 'EPA Ireland provisional GHG 1990-2025: power generation 197 g CO2/kWh in 2025'), ci_fuel_g_kwh: GAS_CI,
    wsi_index: EST(1.0, 'Aqueduct 4.0 Ireland score not retrieved; planning estimate'), p_co2_usd_ton: REAL(euaUsd, S.eua),
  },
  'US-ND': {
    p_elec_usd_kwh: REAL(0.0725, 'EIA 2024: North Dakota industrial 7.25 ¢/kWh'),
    p_fuel_usd_kwh: REAL(r3(2.21 / 304), 'EIA Natural Gas Annual 2024, Table 23: North Dakota industrial $2.21/Mcf'),
    ci_grid_g_kwh: REAL(646, 'EIA North Dakota electricity profile 2024: 1,424 lb CO2/MWh'), ci_fuel_g_kwh: GAS_CI,
    wsi_index: EST(1.0, 'Aqueduct 4.0 state score not retrieved; planning estimate'),
    p_co2_usd_ton: EST(0, 'No carbon price on heating fuel in North Dakota'),
  },
  'US-VA': {
    p_elec_usd_kwh: REAL(0.0899, 'EIA 2024: Virginia industrial 8.99 ¢/kWh'),
    p_fuel_usd_kwh: REAL(r3(4.35 / 304), 'EIA Natural Gas Annual 2024, Table 23: Virginia industrial $4.35/Mcf'),
    ci_grid_g_kwh: REAL(286, 'EIA Virginia electricity profile 2024: 631 lb CO2/MWh'), ci_fuel_g_kwh: GAS_CI,
    wsi_index: EST(1.5, 'Aqueduct 4.0 state score not retrieved; planning estimate'),
    p_co2_usd_ton: EST(0, 'No carbon price on heating fuel in Virginia'),
  },
  'US-HI': {
    p_elec_usd_kwh: EST(0.38, 'EIA Hawaii electricity profile 2024: all-sector average 38.00 ¢/kWh (industrial not itemised here)'),
    p_fuel_usd_kwh: REAL(r3(28.35 / 304), 'EIA Natural Gas Annual 2024, Table 23: Hawaii industrial $28.35/Mcf (synthetic natural gas)'),
    ci_grid_g_kwh: REAL(647, 'EIA Hawaii electricity profile 2024: 1,426 lb CO2/MWh'), ci_fuel_g_kwh: GAS_CI,
    wsi_index: EST(1.5, 'Hand estimate from the team database (reference_sites.py); Aqueduct score not retrieved'),
    p_co2_usd_ton: EST(0, 'No carbon price on heating fuel in Hawaii'),
  },
  GB: {
    p_elec_usd_kwh: REAL(r3(0.168 * GBP), 'DESNZ Quarterly Energy Prices: manufacturing 16.8 p/kWh, Q4 2025'),
    p_fuel_usd_kwh: REAL(r3(0.035 * GBP), 'DESNZ Quarterly Energy Prices: manufacturing gas 3.5 p/kWh, Q4 2025'),
    ci_grid_g_kwh: REAL(217, `${S.ember}: United Kingdom 217 g/kWh`), ci_fuel_g_kwh: GAS_CI,
    wsi_index: REAL(1.37, `${S.aqueduct}: United Kingdom 1.37`),
    p_co2_usd_ton: REAL(r3(63.36 * GBP), 'UK ETS: EEX UKA Dec-2026 £63.36/t on 16 Oct 2026'),
  },
};

export const REFERENCE_SITES: ReferenceSite[] = [
  {
    id: 'ref-mantsala', climate: { t_db_mean_c: 5, t_db_min_c: -25, t_db_max_c: 28, warmest_month: 7 }, name: 'Nebius Mäntsälä', operator: 'Nebius', city: 'Mäntsälä', country: 'FI', region: 'FI',
    lat: 60.633, lng: 25.317, pathways: ['district_heating'],
    it_mw: REAL(75, 'Nebius: Mäntsälä expanded to 75 MW'), pue: REAL(1.13, 'Nebius: PUE 1.13 at full capacity'),
    facts: {
      is_greenfield: REAL(1, 'Nebius: greenfield data center built with heat recovery for district heating'),
      t_dc_base_c: REAL(38, 'Nebius: air-to-water heat exchangers raise water to 35–40 C'),
      has_existing_dh: REAL(1, 'Nebius: heat fed to the Mäntsälä district heating network (Nivos)'),
      d_dh_m: EST(900, 'Handoff archetype nebius_mantsala'), rho_heat_mwh_m: EST(4.2, 'Handoff archetype nebius_mantsala'),
    },
  },
  {
    id: 'ref-rjukan', climate: { t_db_mean_c: 4, t_db_min_c: -20, t_db_max_c: 26, warmest_month: 7 }, name: 'Green Mountain TEL-Rjukan', operator: 'Green Mountain', city: 'Rjukan', country: 'NO', region: 'NO',
    lat: 59.877, lng: 8.593, pathways: ['fish_farm_ras'],
    it_mw: REAL(6.7, 'Menon Economics 2025: TEL-Rjukan current power capacity 6.7 MW (expanding toward 43.7 MW)'), pue: REAL(1.14, 'Green Mountain: average PUE 1.08–1.20 (midpoint)'),
    facts: {
      d_water_m: REAL(800, 'Green Mountain: 800 m pipeline to Hima Seafood'),
      flat_land_m2: EST(30000, 'Hima RAS farm site next to the data center (estimate)'),
      t_dc_base_c: EST(30, 'Cooling water return, estimate'), slope_deg: EST(4, 'Valley floor, estimate'),
    },
  },
  {
    id: 'ref-am3', climate: { t_db_mean_c: 10.5, t_db_min_c: -6, t_db_max_c: 30, warmest_month: 7 }, name: 'Equinix AM3 Science Park', operator: 'Equinix', city: 'Amsterdam', country: 'NL', region: 'NL',
    lat: 52.355, lng: 4.951, pathways: ['btes_ates'],
    it_mw: REAL(18, 'Cloudscene / datacenters.com: AM3 total power 18 MW'), pue: REAL(1.2, 'Equinix Netherlands via ioplus: AM3 PUE 1.2'),
    facts: {
      ind_zoning: EST(0, 'Amsterdam Science Park, inside the city (urban / research campus): no industrial zoning, so no fish farm, biomass or drying plant'), flat_land_m2: EST(0, 'No free flat land in an urban core (estimate)'),
      is_greenfield: REAL(1, 'ATES was designed in when AM3 was built (2012), so it is evaluated as designed-in'),
      geo_storage_score: REAL(5, 'Operating ATES wells on site'), t_dc_base_c: EST(30, 'Estimate'),
      d_dh_m: EST(300, 'Heat goes to neighbouring Science Park buildings (estimate)'),
    },
  },
  {
    id: 'ref-falun', climate: { t_db_mean_c: 4.5, t_db_min_c: -22, t_db_max_c: 27, warmest_month: 7 }, name: 'EcoDataCenter Falun', operator: 'EcoDataCenter', city: 'Falun', country: 'SE', region: 'SE',
    lat: 60.606, lng: 15.626, pathways: ['biomass_processing', 'industrial_drying'],
    it_mw: REAL(45, 'DCD: expansion brings EcoDataCenter 1 to 45 MW (Q2 2025); 80 MW grid access secured'), pue: REAL(1.15, 'DCD: PUE around 1.15'),
    facts: {
      is_greenfield: REAL(1, 'Built together with Falu Energi & Vatten next to its pellet plant, evaluated as designed-in'),
      t_dc_base_c: REAL(31, 'SWEP: surplus heat between 30 and 32 C'),
      d_pp_m: REAL(300, 'DCD: pipes to the CHP plant next door (distance estimated)'),
      d_bio_m: REAL(500, 'Sawdust and pellet plant on the CHP site (distance estimated)'),
      has_existing_dh: REAL(1, 'Falun district heating from the same CHP plant'), d_dh_m: EST(500, 'Estimate'),
      ind_zoning: REAL(1, 'Industrial site of the energy company'), q_fw_mw: EST(10, 'CHP feedwater sink, estimate'),
    },
  },
  {
    id: 'ref-pa10', climate: { t_db_mean_c: 12.5, t_db_min_c: -4, t_db_max_c: 34, warmest_month: 7 }, name: 'Equinix PA10', operator: 'Equinix', city: 'Saint-Denis (Paris)', country: 'FR', region: 'FR',
    lat: 48.917, lng: 2.357, pathways: ['greenhouse', 'district_heating'],
    it_mw: REAL(5, 'datacenters.com: PA10 has access to 5 MW of power'), pue: EST(1.3, 'Not published; planning estimate'),
    facts: {
      ind_zoning: EST(0, 'Saint-Denis, dense inner Paris suburb (urban): no industrial zoning, so no fish farm, biomass or drying plant'), flat_land_m2: EST(0, 'No free flat land in an urban core (estimate)'),
      is_greenfield: REAL(1, 'Heat recovery and greenhouse were designed into PA10'),
      agri_land_m2: REAL(430, 'Equinix: 430 m² rooftop greenhouse'),
      has_existing_dh: REAL(1, 'Connected to the Saint-Denis heating network'), d_dh_m: EST(500, 'Plaine Saulnier zone next door (estimate)'),
      rho_heat_mwh_m: EST(3, 'Dense urban district, estimate'), t_dc_base_c: EST(30, 'Estimate'),
    },
    note: 'The greenhouse is 430 m², far below the 2 ha the model gate expects, so the model knocks it out at this size.',
  },
  {
    id: 'ref-seattle', climate: { t_db_mean_c: 11.5, t_db_min_c: -4, t_db_max_c: 32, warmest_month: 8 }, name: 'Westin Building Exchange', operator: 'Westin Building Exchange / Amazon', city: 'Seattle', country: 'US', region: 'US-WA',
    lat: 47.6145, lng: -122.3385, pathways: ['district_heating'],
    it_mw: REAL(19, 'datacentermap: Westin Building fully built-out power 19 MW'), pue: EST(1.4, 'Not published; older multi-tenant building, planning estimate'),
    facts: {
      ind_zoning: EST(0, 'Downtown Seattle carrier hotel (urban core): no industrial zoning, so no fish farm, biomass or drying plant'), flat_land_m2: EST(0, 'No free flat land in an urban core (estimate)'),
      has_existing_dh: REAL(1, 'Amazon eco-district loop across the street'), d_dh_m: REAL(100, 'Across the street'),
      t_dc_base_c: REAL(18, 'Water at about 65 F before heat pumps (evaluated at the model minimum of 25 C)'),
      rho_heat_mwh_m: EST(3, 'Dense downtown, estimate'),
    },
  },
  {
    id: 'ref-syracuse', climate: { t_db_mean_c: 9, t_db_min_c: -20, t_db_max_c: 32, warmest_month: 7 }, name: 'Syracuse University Green Data Center', operator: 'Syracuse University / IBM', city: 'Syracuse, NY', country: 'US', region: 'US-NY',
    lat: 43.0377, lng: -76.134, pathways: ['absorption_cooling'],
    it_mw: EST(0.5, 'Not published; sized below the 780 kW on-site microturbine plant'), pue: EST(1.3, 'Not published; planning estimate'),
    facts: {
      ind_zoning: EST(0, 'University campus in the city of Syracuse (urban): no industrial zoning, so no fish farm, biomass or drying plant'), flat_land_m2: EST(0, 'No free flat land in an urban core (estimate)'), t_dc_base_c: EST(30, 'Estimate') },
    note: 'Here the absorption chillers run on microturbine exhaust, not server heat; the model tests whether server heat could do it.',
  },
  {
    id: 'ref-civo', climate: { t_db_mean_c: 11.5, t_db_min_c: -4, t_db_max_c: 32, warmest_month: 7 }, name: 'Civo UK data center (Orbital pilot)', operator: 'Civo', city: 'United Kingdom (exact site not disclosed)', country: 'GB', region: 'GB',
    lat: 51.507, lng: -0.128, pathways: ['dac'],
    it_mw: EST(2, 'Not published by Civo; planning estimate'), pue: EST(1.3, 'Not published; planning estimate'),
    facts: { t_dc_base_c: EST(30, 'Estimate'), d_co2_m: EST(50000, 'CO2 offtake distance unknown, estimate') },
    note: 'Pin placed in London because the pilot site is not public.',
  },
  {
    id: 'ref-eindhoven', climate: { t_db_mean_c: 11, t_db_min_c: -6, t_db_max_c: 31, warmest_month: 7 }, name: 'NorthC Eindhoven 1 (High Tech Campus)', operator: 'NorthC', city: 'Eindhoven', country: 'NL', region: 'NL',
    lat: 51.4110, lng: 5.4590, pathways: ['btes_ates'],
    it_mw: EST(1.8, 'NorthC factsheet: 2.4 MW installed power; IT = 2.4 / PUE 1.25 (inferred)'), pue: EST(1.25, 'Grundfos case study: under 20 % for cooling and security (inferred)'),
    facts: {
      is_greenfield: EST(1, 'ATES (WKO) built with the data center (Grundfos case study), so evaluated as designed-in'),
      geo_storage_score: EST(4, 'Sand aquifers with active ATES use; hand estimate (team database data_pipeline/reference_sites.py)'),
      has_existing_dh: REAL(1, 'Heat goes to the High Tech Campus heat ring (Grundfos case study)'), d_dh_m: EST(0, 'On the campus ring; hand estimate'),
      t_dc_base_c: EST(30, 'Estimate'),
    },
  },
  {
    id: 'ref-arklow', climate: { t_db_mean_c: 10, t_db_min_c: -3, t_db_max_c: 25, warmest_month: 7 }, name: 'Echelon DUB20 Arklow', operator: 'Echelon Data Centres', city: 'Arklow, Wicklow', country: 'IE', region: 'IE',
    lat: 52.7930, lng: -6.1600, pathways: ['biogas'],
    it_mw: EST(80, 'RTE 2021: 100 MW facility; IT share not published (estimate)'), pue: EST(1.3, 'Not published; planning estimate'),
    facts: {
      is_greenfield: REAL(1, 'Biocore digester agreed together with the new campus (Bioenergy Insight, 2021)'),
      d_bio_m: REAL(500, 'Biocore biogas plant co-located on the DUB20 site (Bioenergy Insight, 2021); distance assumed 500 m'),
      ind_zoning: EST(1, 'Industrial campus; hand estimate (team database data_pipeline/reference_sites.py)'), t_dc_base_c: EST(30, 'Estimate'),
    },
    note: 'Planned (agreed 2021): data center heat keeps the co-located digester warm.',
  },
  {
    id: 'ref-williston', climate: { t_db_mean_c: 5, t_db_min_c: -30, t_db_max_c: 35, warmest_month: 7 }, name: 'Crusoe Digital Flare Mitigation (Williston Basin)', operator: 'Crusoe', city: 'Williston, North Dakota', country: 'US', region: 'US-ND',
    lat: 48.1470, lng: -103.6180, pathways: ['biogas'],
    it_mw: EST(1.5, 'Module size per well pad not published (team assumption)'), pue: EST(1.1, 'Containerised modules; estimate'),
    facts: {
      d_bio_m: EST(50000, 'Flare gas is not digester feedstock; hand estimate (team database data_pipeline/reference_sites.py)'),
      flat_land_m2: EST(3000000, 'Open prairie; hand estimate (team database data_pipeline/reference_sites.py)'), t_dc_base_c: EST(30, 'Estimate'),
    },
    note: 'Crusoe burns stranded flare gas to power the compute (gas to power). It does not reuse server heat, so the model is expected to find no heat option here.',
  },
  {
    id: 'ref-kona', climate: { t_db_mean_c: 24, t_db_min_c: 17, t_db_max_c: 31, warmest_month: 8 }, name: 'Trevi Systems desalination test (NELHA Kona)', operator: 'Trevi Systems / Endeavour', city: 'Kailua-Kona, Hawaii', country: 'US', region: 'US-HI',
    lat: 19.7280, lng: -156.0570, pathways: ['desalination'],
    it_mw: EST(1, 'Modelled as a 1 MW warm liquid-cooled module so results read per MW (team database data_pipeline/reference_sites.py)'), pue: EST(1.15, 'Estimate'),
    facts: {
      is_greenfield: EST(1, 'New modular build'), cooling_type: EST('liquid', 'Warm liquid cooling assumed (Endeavour concept)'), t_dc_base_c: EST(60, 'Warm liquid cooling; estimate'),
      d_coast_m: EST(300, 'NELHA seawater intake on the coast; hand estimate (team database data_pipeline/reference_sites.py)'), dz_m: EST(5, 'Hand estimate'),
    },
    note: 'Pilot: Trevi ran its process on seawater at NELHA (DOE EERE, 2022); Endeavour plans to pair it with data center heat. Not a data center site.',
  },
  {
    id: 'ref-vertiv-orc', climate: { t_db_mean_c: 13.5, t_db_min_c: -10, t_db_max_c: 35, warmest_month: 7 }, name: 'Vertiv ORC testbed (Ashburn design climate)', operator: 'Vertiv', city: 'Ashburn, Virginia', country: 'US', region: 'US-VA',
    lat: 39.0438, lng: -77.4874, pathways: ['orc'],
    it_mw: REAL(0.04, 'Vertiv white paper: about 40 kW of liquid-cooled servers'), pue: EST(1.2, 'Estimate'),
    facts: {
      cooling_type: REAL('liquid', 'Vertiv white paper: liquid-cooled servers'), t_dc_base_c: REAL(58, 'Vertiv white paper: server outlet 58 C'),
    },
    note: 'Lab test, not a data center: the best case still had negative net power after fans and pumps (Vertiv white paper).',
  },
];

const LABELS: Record<string, [string, string | null]> = {
  is_greenfield: ['Greenfield / designed-in', null], cooling_type: ['Cooling type', null], t_dc_base_c: ['Waste heat temperature', 'C'],
  q_dc_mw: ['Recoverable heat', 'MW'], slope_deg: ['Terrain slope', 'deg'], flat_land_m2: ['Flat land nearby', 'm2'],
  d_water_m: ['Distance to water', 'm'], wsi_index: ['Water stress', null], has_existing_dh: ['Existing district heating', null],
  d_dh_m: ['Distance to heat demand', 'm'], rho_heat_mwh_m: ['Heat demand density', 'MWh/m/yr'], d_coast_m: ['Distance to coast', 'm'],
  dz_m: ['Height above intake', 'm'], d_bio_m: ['Distance to biomass', 'm'], d_co2_m: ['Distance to CO2 sink', 'm'],
  d_pp_m: ['Distance to power plant', 'm'], q_fw_mw: ['Feedwater heat demand', 'MW'], ind_zoning: ['Industrial zoning', null],
  campus_area_m2: ['New-build slab area', 'm2'], agri_land_m2: ['Agricultural / greenhouse area', 'm2'],
  geo_storage_score: ['Geological storage score', null], p_elec_usd_kwh: ['Electricity price', 'USD/kWh'],
  p_fuel_usd_kwh: ['Displaced fuel price', 'USD/kWh'], p_steam_usd_mwh: ['Steam value', 'USD/MWh'], p_water_usd_m3: ['Water price', 'USD/m3'],
  p_co2_usd_ton: ['Carbon price', 'USD/t'], d_market_m: ['Distance to market', 'm'], ci_grid_g_kwh: ['Grid carbon intensity', 'g CO2/kWh'],
  ci_fuel_g_kwh: ['Fuel carbon intensity', 'g CO2/kWh'], eco_sens_index: ['Ecological sensitivity', null], mit_tier: ['Mitigation tier', null],
};

export const isReference = (id: string) => id.startsWith('ref-');
export const referenceById = (id: string) => REFERENCE_SITES.find((s) => s.id === id);

export function referenceSummaries(): (SiteSummary & { reference: true; pathways: string[] })[] {
  return REFERENCE_SITES.map((s) => ({
    site_id: s.id, name: s.name, lat: s.lat, lon: s.lng, operator: s.operator, city: s.city, country: s.country,
    it_load_mw: Number(s.it_mw.value), pue: Number(s.pue.value), cooling_type: 'reference site', is_hypothetical: false,
    weather_stored: false, reference: true, pathways: s.pathways,
  }));
}

/** The 31 inputs of a reference site with flags and sources, plus the derived baseline. */
export function referenceInputs(id: string, isGreenfield?: number): { inputs: InputValue[]; used: Record<string, unknown>; baseline: Baseline; site: ReferenceSite } {
  const s = referenceById(id);
  if (!s) throw new Error(`Unknown reference site ${id}`);
  const c = COUNTRY[s.region];
  const itMw = Number(s.it_mw.value), pue = Number(s.pue.value);
  const values: Record<string, Fact> = {};
  for (const [k, v] of Object.entries(DEFAULTS)) values[k] = EST(v, 'Planning default (Team Excel defaults)');
  Object.assign(values, c);
  values.q_dc_mw = { value: Math.round(itMw * 0.9 * 100) / 100, flag: s.it_mw.flag, source: `IT load ${itMw} MW x 0.9 capture (${s.it_mw.source})` };
  Object.assign(values, s.facts);
  if (isGreenfield === 1) values.is_greenfield = { value: 1, flag: 'user', source: 'Greenfield toggle in the panel' };
  const inputs: InputValue[] = Object.keys(LABELS).map((k) => ({
    key: k, label: LABELS[k][0], unit: LABELS[k][1], value: values[k].value, flag: values[k].flag,
    status: values[k].flag === 'real' ? 'data' : 'assumption', source: values[k].source,
  }));
  const used = Object.fromEntries(inputs.map((i) => [i.key, i.value]));
  used.baseline_cooling_evaporative = false;
  const itE = itMw * 8760, fac = itE * pue, wue = 0.5;
  const baseline: Baseline = {
    it_load_mw: itMw, it_energy_mwh_yr: itE, facility_energy_mwh_yr: fac, heat_rejected_mwh_yr: fac, pue,
    wue_l_kwh: wue, water_use_m3_yr: itE * wue, co2_t_yr: (fac * Number(c.ci_grid_g_kwh.value)) / 1000,
    electricity_cost_usd_yr: fac * Number(c.p_elec_usd_kwh.value) * 1000, cooling_type: String(values.cooling_type.value),
  };
  return { inputs, used, baseline, site: s };
}

export function referenceSiteInputs(id: string, isGreenfield?: number): SiteInputs {
  const { inputs } = referenceInputs(id, isGreenfield);
  const flag_counts = inputs.reduce((a, i) => ({ ...a, [i.flag]: (a[i.flag] ?? 0) + 1 }), {} as Partial<Record<Flag, number>>);
  return { site_id: id, inputs, weather: {}, flag_counts };
}
