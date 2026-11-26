/** Typed facade over ./engine.ts (DSX evaluator v3.1.1). */
import { ENGINE as RAW } from './engine';

export interface DsxSite {
  is_greenfield: number; cooling_type: 'liquid' | 'air'; t_dc_base_c: number; q_dc_mw: number;
  slope_deg: number; flat_land_m2: number; d_water_m: number; wsi_index: number; has_existing_dh: number;
  d_dh_m: number; rho_heat_mwh_m: number; d_coast_m: number; dz_m: number; d_bio_m: number; d_co2_m: number;
  d_pp_m: number; q_fw_mw: number; ind_zoning: number; campus_area_m2: number; agri_land_m2: number;
  geo_storage_score: number; p_elec_usd_kwh: number; p_fuel_usd_kwh: number; p_steam_usd_mwh: number;
  p_water_usd_m3: number; p_co2_usd_ton: number; d_market_m: number; ci_grid_g_kwh: number; ci_fuel_g_kwh: number;
  eco_sens_index: number; mit_tier: 'low' | 'med' | 'high';
}

export interface DsxAnnual {
  q_src_mwh: number; q_del_mwh: number; w_hp_mwh: number; product_qty: number; product_unit: string;
  direct_hx_hours: number; mean_cop: number | null; orc_mean_eta: number | null; net_abated_tco2: number;
  revenue_usd: number; hp_elec_cost_usd: number; capex_usd: number; net_annual_usd: number; payback_yr: number | null;
  capex_plant_usd: number; capex_pipe_usd: number; capex_hp_usd: number; value_usd: number; carbon_rev_usd: number;
  utilisation: number; cap_fraction: number;
}

export interface DsxOption {
  id: number; key: string; name: string; mode: string; t_sink_c: number; rank: number;
  ko_pass: boolean; ko_failures: string[]; viability: number; viability_ungated: number;
  subscores: { p_thermo: number; p_climate: number; p_econ: number; p_util: number };
  eco_score: number; eco_grade: string; eco_subscores: { e_ghg: number; e_water: number; e_local: number };
  annual: DsxAnnual;
}

export interface DsxClimateStats {
  mean_amb: number; gt20: number; gt24: number; gt30: number; gt35: number; lt15: number; lt18: number;
  lt25: number; lt30: number; le2: number; min_tdc: number; max_tdc: number;
}

export interface DsxEvaluation { version: string; warnings: string[]; climate_summary: DsxClimateStats; options: DsxOption[] }

export interface DsxWhatIf {
  preset: string; preset_label: string; already_at_or_above_preset: boolean;
  unlocked: string[]; lost: string[];
  deltas: { key: string; name: string; viability_before: number; viability_after: number; viability_gain: number; hp_mwh_saved: number; unlocked: boolean; lost: boolean }[];
}

export interface DsxEngine {
  VERSION: string;
  C: Record<string, number> & { mit_mult: Record<string, number> };
  INPUT_SPEC: Record<keyof DsxSite, [string, ...unknown[]]>;
  DSX_PRESETS: Record<string, { label: string; cooling_type: 'liquid' | 'air'; t_dc_base_c: number }>;
  WHAT_IF_PRESET: string;
  OPTIONS: { id: number; key: string; name: string; t_sink: number; capex_usd_kw: number; pipe_usd_m: number; dist_key: string | null; dist_max_m: number; water_factor: number; local_impact: number }[];
  InputError: new (msg: string) => Error;
  evaluate(site: DsxSite, tMin: number[], tMax: number[]): DsxEvaluation;
  whatIfSummary(site: DsxSite, baseline: DsxEvaluation, upgraded: DsxEvaluation, preset: string): DsxWhatIf;
}

export const ENGINE = RAW as unknown as DsxEngine;
