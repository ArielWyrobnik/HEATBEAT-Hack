/**
 * TypeScript mirror of heatbeat_api/schemas.py (the API contract). Keep both in sync.
 * Units are in the field names: _mwh_yr, _t_yr (t CO2), _m3_yr, _usd, _yr.
 */
export type Flag = 'real' | 'estimated' | 'synthetic' | 'user';

export interface SiteSummary {
  site_id: string;
  name: string;
  lat: number;
  lon: number;
  operator?: string | null;
  city?: string | null;
  region?: string | null;
  country?: string | null;
  capacity_mw?: number | null;
  it_load_mw?: number | null;
  cooling_type?: string | null;
  pue?: number | null;
  grid_region?: string | null;
  retail_usd_mwh?: number | null;
  co2_kg_mwh?: number | null;
  is_hypothetical: boolean;
  weather_stored: boolean;
  /** How well today's setup is documented: verified, partial, context, or null (nothing found) */
  setup_status?: string | null;
}

export interface InputValue {
  key: string;
  label?: string | null;
  value: unknown;
  unit?: string | null;
  flag: Flag;
  status: string;
  source?: string | null;
  description?: string | null;
  sens_low?: number | null;
  sens_high?: number | null;
}

export interface SiteInputs {
  site_id: string;
  inputs: InputValue[];
  weather: Record<string, unknown>;
  flag_counts: Partial<Record<Flag, number>>;
}

export interface Kpis {
  heat_recovered_mwh_yr?: number | null;
  heat_delivered_mwh_yr?: number | null;
  electricity_used_mwh_yr?: number | null;
  electricity_saved_mwh_yr?: number | null;
  co2_avoided_t_yr?: number | null;
  water_saved_m3_yr?: number | null;
  net_value_usd_yr?: number | null;
  cash_value_usd_yr?: number | null;
  water_value_usd_yr?: number | null;
  capex_usd?: number | null;
  payback_yr?: number | null;
  pue_baseline?: number | null;
  pue_with?: number | null;
  wue_baseline_l_kwh?: number | null;
  wue_with_l_kwh?: number | null;
  ere?: number | null;
  cop?: number | null;
  capacity_factor?: number | null;
}

export interface EnergyFlow {
  source: string;
  target: string;
  mwh_yr: number;
  kind: 'heat' | 'electricity' | 'cooling' | 'fuel' | 'loss' | 'other';
}

export interface HeatLoop {
  name: string;
  mwh_yr: number;
  return_c: number;
  routes: { name: string; mwh_yr: number; kind: 'reuse' | 'cooling' }[];
}

export interface CalcTerm {
  key: string;
  label?: string | null;
  value?: number | string | null;
  unit?: string | null;
  /** null = computed by the model in an earlier step */
  flag?: Flag | null;
  source?: string | null;
}

export interface CalcStep {
  title: string;
  formula: string;
  terms: CalcTerm[];
  result?: number | null;
  unit?: string | null;
  note?: string | null;
}

/** A company that can build one part of an option (heatbeat_data.vendors, docs/VENDORS.md). */
export interface Vendor {
  vendor_id: string;
  name: string;
  role: string;
  role_label?: string | null;
  one_line?: string | null;
  url?: string | null;
  where?: string | null;
  distance_km?: number | null;
  nvidia?: string | null;
  nvidia_source?: string | null;
  verified: 'verified' | 'partly' | 'unverified' | string;
  source_url?: string | null;
  note?: string | null;
}

export interface OptionResult {
  option_id: string;
  name: string;
  rank?: number | null;
  feasible: boolean;
  score?: number | null;
  eco_grade?: string | null;
  components: string[];
  product?: string | null;
  ko_reasons: string[];
  /** How it would be built at this site */
  implementation?: string | null;
  /** USD per cost item, sums to kpis.capex_usd */
  capex_breakdown: Record<string, number>;
  kpis: Kpis;
  energy_balance: EnergyFlow[];
  heat_loops?: HeatLoop[];
  details: Record<string, unknown>;
  /** Step by step calculation trace with sources (engineering model) */
  calculation?: CalcStep[];
  /** Every input this option uses, with flag and source */
  calculation_inputs?: InputValue[];
  /** Parts of this option the site already has today, with source */
  already_in_place?: string[];
  /** True for the option that is the site's current setup (no change) */
  is_today?: boolean;
  vendors?: Vendor[];
}

/** One fact about what the data center does today (site_current_setup.csv) */
export interface SetupFact {
  field: string;
  label?: string | null;
  value?: unknown;
  unit?: string | null;
  scope?: string | null;
  confidence?: string | null;
  evidence?: string | null;
  note?: string | null;
  source_url?: string | null;
  source_title?: string | null;
  source_date?: string | null;
}

export interface Baseline {
  it_load_mw?: number | null;
  it_energy_mwh_yr?: number | null;
  facility_energy_mwh_yr?: number | null;
  heat_rejected_mwh_yr?: number | null;
  pue?: number | null;
  wue_l_kwh?: number | null;
  water_use_m3_yr?: number | null;
  co2_t_yr?: number | null;
  electricity_cost_usd_yr?: number | null;
  cooling_type?: string | null;
  cooling_profile?: string | null;
  /** dry, adiabatic or tower */
  heat_rejection?: string | null;
  heat_rejection_flag?: Flag | null;
  heat_rejection_source?: string | null;
  /** verified, partial, context or null */
  setup_status?: string | null;
  current_setup?: SetupFact[];
}

export interface TornadoBar {
  input: string;
  label?: string | null;
  low_value: number;
  high_value: number;
  metric_low: number;
  metric_high: number;
  flag?: Flag | null;
}

export interface Tornado {
  option_id: string;
  metric: string;
  unit?: string | null;
  base: number;
  bars: TornadoBar[];
}

export interface ModelResult {
  site_id: string;
  model: string;
  mode: string;
  model_version?: string | null;
  score_scale: string;
  baseline: Baseline;
  options: OptionResult[];
  tornado?: Tornado | null;
  warnings: string[];
  verdict?: string | null;
  verdict_level?: 'no_gain' | 'small_gain' | 'gain' | null;
  inputs_used: Record<string, unknown>;
  /** Inputs with flags, filled for planned sites */
  inputs: InputValue[];
  cooling_vendors?: Vendor[];
  planned_site?: PlanRequest | null;
}

export interface CoolingProfile {
  cooling_profile_id: string;
  label: string;
  cooling_type: string;
  heat_temp_c?: number | null;
  pue_typical?: number | null;
  description?: string | null;
}

/** A future data center: any point on the map plus size and cooling. */
export interface PlanRequest {
  lat: number;
  lon: number;
  it_mw: number;
  cooling_profile: string;
  name?: string | null;
  pue?: number | null;
  is_greenfield: number;
  model?: string | null;
  mode?: string | null;
  overrides?: Record<string, unknown>;
  tornado?: boolean;
}

export interface ModelInfo {
  name: string;
  label: string;
  modes: string[];
  default_mode: string;
  description: string;
  default: boolean;
}

/** One data center in the opportunity ranking (GET /api/leaderboard) */
export interface LeaderboardRow {
  site_id: string;
  name: string;
  city?: string | null;
  region?: string | null;
  country?: string | null;
  operator?: string | null;
  it_load_mw?: number | null;
  verdict_level?: string | null;
  option_id?: string | null;
  option_name?: string | null;
  npv_usd?: number | null;
  cash_value_usd_yr?: number | null;
  co2_avoided_t_yr?: number | null;
  water_saved_m3_yr?: number | null;
  payback_yr?: number | null;
}
