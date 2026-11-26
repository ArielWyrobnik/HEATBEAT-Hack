/**
 * Plugs the DSX Waste-Heat Recovery Evaluator (v3.2.0) into Heat Beat as a third model.
 * Runs entirely in the browser: it takes the 31 site inputs the backend already serves (same keys as the
 * Team Excel ranking), loads a 365-day climate for the site, runs the evaluator and returns a ModelResult,
 * so every existing panel (ranking, KPIs, calculation popup, tornado) works unchanged.
 */
import type { Baseline, CalcStep, CalcTerm, EnergyFlow, InputValue, ModelInfo, ModelResult, OptionResult, Tornado } from '../types/api';
import { dailyClimate, type DailyClimate } from './climate';
import { ENGINE, type DsxEvaluation, type DsxOption, type DsxSite } from './types';

export const DSX_MODEL_NAME = 'dsx_evaluator';
/** Backend model whose inputs (same 31 keys) and baseline the DSX evaluator reuses. */
export const DSX_INPUT_MODEL = 'excel_ranking';

export const DSX_MODEL: ModelInfo = {
  name: DSX_MODEL_NAME,
  label: 'DSX evaluator v3.1',
  modes: ['as_built'],
  default_mode: 'as_built',
  default: false,
  description:
    "13 heat reuse pathways on an 8,760 h diurnal climate (Open-Meteo 2024), knock-out gates, viability 0 to 5 and a standalone eco grade A to F, "
    + "with proof sites and NVIDIA-linked builders.",
};

const IMPLEMENTATION: Record<string, string> = {
  fish_farm_ras: 'Warm cooling water heats a recirculating aquaculture system (RAS) next to the site; fish sold through the local cold chain.',
  district_heating: 'Heat pump lifts cooling water to 65 C and feeds the district heating network through a trench pipe and a substation.',
  biogas: 'Cooling water keeps an anaerobic digester at 37 C (mesophilic); substrate trucked in from nearby farms or food plants.',
  absorption_cooling: 'Heat at 85 C drives a single-effect absorption chiller that offsets electric chiller load on the campus.',
  orc: 'An organic Rankine cycle turbine converts 80 C+ coolant heat to electricity; condenser rejects to ambient.',
  dac: 'Heat pump delivers 90 C to the sorbent regeneration of a direct air capture plant; CO2 piped to storage or a buyer.',
  btes_ates: 'Summer heat is stored in a borehole or aquifer field and recovered in winter at 55 C for heating.',
  feedwater_preheat: 'Cooling water preheats boiler feedwater of a neighbouring thermal plant, saving turbine bleed steam.',
  desalination: 'Multi-effect distillation or membrane distillation at 70 C makes fresh water from seawater or brackish water.',
  biomass_processing: 'Heat at 65 C dries and processes biomass (pellets, digestate) in a co-located plant on industrial land.',
  industrial_drying: 'Heat at 75 C runs belt or drum dryers for timber, food or agricultural products in an industrial zone.',
  snow_melt: 'Hydronic loops under new slabs, roads and aprons keep them ice-free with 35 C water.',
  greenhouse: 'A co-designed greenhouse on adjacent agricultural land is heated with 40 C water from the data center.',
};

const LABEL: Record<string, string> = {
  is_greenfield: 'Greenfield site', cooling_type: 'Cooling type', t_dc_base_c: 'Waste heat temperature', q_dc_mw: 'Recoverable heat',
  slope_deg: 'Terrain slope', flat_land_m2: 'Flat land', d_water_m: 'Distance to water intake', wsi_index: 'Water stress index',
  has_existing_dh: 'Existing DH grid', d_dh_m: 'Distance to DH', rho_heat_mwh_m: 'Linear heat density', d_coast_m: 'Distance to coast',
  dz_m: 'Elevation head', d_bio_m: 'Distance to biomass', d_co2_m: 'Distance to CO2 sink', d_pp_m: 'Distance to power plant',
  q_fw_mw: 'Feedwater heat sink', ind_zoning: 'Industrial zoning', campus_area_m2: 'New-build slab area', agri_land_m2: 'Agricultural land',
  geo_storage_score: 'Geo storage score', p_elec_usd_kwh: 'Electricity price', p_fuel_usd_kwh: 'Displaced fuel price',
  p_steam_usd_mwh: 'Steam value', p_water_usd_m3: 'Water price', p_co2_usd_ton: 'Carbon price', d_market_m: 'Distance to market',
  ci_grid_g_kwh: 'Grid carbon intensity', ci_fuel_g_kwh: 'Fuel carbon intensity', eco_sens_index: 'Ecological sensitivity', mit_tier: 'Mitigation tier',
};

const KEYS = Object.keys(ENGINE.INPUT_SPEC) as (keyof DsxSite)[];

/** Map the backend's inputs_used onto the evaluator's 31 inputs, clamping to its valid ranges. */
export function toDsxSite(used: Record<string, unknown>): { site: DsxSite; notes: string[] } {
  const notes: string[] = [];
  const site = {} as Record<string, unknown>;
  for (const k of KEYS) {
    const sp = ENGINE.INPUT_SPEC[k];
    const raw = used[k];
    if (sp[0] === 'enum') {
      const allowed = sp[1] as string[];
      const v = String(raw ?? '');
      site[k] = allowed.includes(v) ? v : allowed[k === 'mit_tier' ? 1 : 0];
      if (!allowed.includes(v)) notes.push(`${LABEL[k]} "${v}" not recognised; used "${site[k]}".`);
      continue;
    }
    let v = Number(raw);
    if (!Number.isFinite(v)) { v = sp[0] === 'pos' ? 0.05 : Number(sp[1] ?? 0); notes.push(`${LABEL[k]} missing; used ${v}.`); }
    if (sp[0] === 'bin') v = v >= 0.5 ? 1 : 0;
    const lo = sp[1] as number, hi = sp[2] as number | null;
    if (sp[0] === 'pos' && v <= 0) { notes.push(`${LABEL[k]} must be above 0; used 0.01.`); v = 0.01; }
    if (sp[0] === 'num' && v < lo) { notes.push(`${LABEL[k]} ${v} is below the evaluator's range; evaluated at ${lo}.`); v = lo; }
    if (sp[0] === 'num' && hi != null && v > hi) { notes.push(`${LABEL[k]} ${v} is above the evaluator's range; evaluated at ${hi}.`); v = hi; }
    site[k] = v;
  }
  return { site: site as unknown as DsxSite, notes };
}

const fmtInt = (v: number) => Math.round(v).toLocaleString('en-US');

function product(o: DsxOption): string {
  const a = o.annual;
  switch (a.product_unit) {
    case 'tCO2': return `${fmtInt(a.product_qty)} t CO2 captured`;
    case 'm3': return `${fmtInt(a.product_qty)} m3 fresh water`;
    case 'MWh_e': return `${fmtInt(a.product_qty)} MWh electricity`;
    case 'MWh_cool': return `${fmtInt(a.product_qty)} MWh cooling`;
    default: return `${fmtInt(a.product_qty)} MWh heat at ${o.t_sink_c} C`;
  }
}

interface Ctx {
  site: DsxSite;
  eval: DsxEvaluation;
  climate: DailyClimate;
  inputs: Map<string, InputValue>;
  baseline: Baseline;
  evaporative: boolean;
}

function term(ctx: Ctx, key: keyof DsxSite | string, valueOverride?: number | string): CalcTerm {
  const iv = ctx.inputs.get(key as string);
  const v = valueOverride ?? (ctx.site as unknown as Record<string, number | string>)[key as string];
  return { key: key as string, label: LABEL[key as string] ?? key as string, value: v, unit: iv?.unit ?? null, flag: iv?.flag ?? 'estimated', source: iv?.source ?? 'backend input' };
}
const calc = (key: string, label: string, value: number | string | null, unit?: string): CalcTerm => ({ key, label, value, unit: unit ?? null, flag: null });

/** LaTeX number: 2 decimals for small values, thousands separated for large ones. */
const tn = (v: number | null | undefined, d = 2) => (v == null || !isFinite(v) ? '\\text{n/a}'
  : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('en-US').replace(/,/g, '{,}') : v.toFixed(d));

function steps(ctx: Ctx, o: DsxOption): CalcStep[] {
  const h = ctx.eval.climate_summary, a = o.annual, s = o.subscores, e = o.eco_subscores, C = ENGINE.C;
  const opt = ENGINE.OPTIONS.find((x) => x.key === o.key)!;
  const climateFlag = ctx.climate.synthetic ? 'synthetic' : 'real';
  const productFormula: Record<string, string> = {
    MWh_th: 'value = Q_del / 0.90 boiler efficiency × fuel price; CO2 avoided = Q_del / 0.90 × fuel carbon intensity − W × grid carbon intensity',
    MWh_cool: 'cooling = 0.70 × Q_del; electricity saved = cooling / 5 (chiller COP); value = saved × electricity price',
    MWh_e: 'electricity = Q_src × 0.45 × Carnot(T_dc, T_amb + 10 C); value = electricity × electricity price',
    m3: 'water = Q_del / 60 kWh_th per m3; value = water × water price; CO2 avoided = 3.5 kWh/m3 of RO × grid carbon',
    tCO2: 'CO2 captured = Q_del / 1.8 MWh_th per t; value = captured × carbon price',
  };
  const CW = C as unknown as { weights: Record<string, number>; eco_weights: Record<string, number> };
  const VW = CW.weights, EW = CW.eco_weights;
  const productTex: Record<string, string[]> = {
    MWh_th: [String.raw`V = \frac{Q_{del}}{\eta_{boiler}}\; p_{fuel},\qquad \eta_{boiler} = 0.90`,
      String.raw`\Delta CO_2 = \frac{Q_{del}}{0.90}\, CI_{fuel} \;-\; W_{hp}\, CI_{grid}`],
    MWh_cool: [String.raw`Q_{cool} = 0.70\, Q_{del},\qquad E_{saved} = \frac{Q_{cool}}{\mathrm{COP}_{chiller}=5}`,
      String.raw`V = E_{saved}\; p_{elec}`],
    MWh_e: [String.raw`E_{el} = Q_{src}\cdot 0.45 \cdot \left(1 - \frac{T_{amb} + 10 + 273.15}{T_{dc} + 273.15}\right)`,
      String.raw`V = E_{el}\; p_{elec}`],
    m3: [String.raw`V_{water} = \frac{Q_{del}}{60\ \mathrm{kWh_{th}/m^3}},\qquad V = V_{water}\; p_{water}`,
      String.raw`\Delta CO_2 = V_{water}\cdot 3.5\ \mathrm{kWh/m^3}\cdot CI_{grid}\quad\text{(reverse osmosis avoided)}`],
    tCO2: [String.raw`m_{CO_2} = \frac{Q_{del}}{1.8\ \mathrm{MWh_{th}/t}},\qquad V = m_{CO_2}\; p_{CO_2}`],
  };
  return [
    {
      title: 'Hourly climate and coolant temperature',
      tex: [String.raw`T_{amb}(d,h) = \frac{T_{max}+T_{min}}{2} \;-\; \frac{T_{max}-T_{min}}{2}\,\cos\!\left(\frac{2\pi\,(h-4)}{24}\right)`,
        String.raw`T_{dc} = \begin{cases} T_{dc,base} & \text{liquid cooling} \\ \max\left(T_{dc,base},\; T_{amb} + ${C.air_offset_c}\right) & \text{air cooling} \end{cases}`],
      formula: 'T_amb(d,h) = (Tmax+Tmin)/2 − (Tmax−Tmin)/2 · cos(2π(h−4)/24);  T_dc = t_dc_base (liquid) or max(t_dc_base, T_amb + 12) (air)',
      terms: [
        { key: 'daily_climate', label: 'Daily min / max temperature', value: '365 days', unit: null, flag: climateFlag, source: ctx.climate.source },
        term(ctx, 'cooling_type'), term(ctx, 't_dc_base_c'),
        calc('mean_amb', 'Mean ambient', h.mean_amb, 'C'),
        calc('tdc_range', 'Coolant range', `${h.min_tdc.toFixed(0)} to ${h.max_tdc.toFixed(0)}`, 'C'),
      ],
      result: h.mean_amb, unit: 'C mean',
    },
    {
      title: 'Knock-out gates',
      tex: [String.raw`G = \prod_i g_i, \qquad g_i \in \{0, 1\}`],
      formula: 'G = 1 only if every gate of this pathway holds (climate hours, distances, land, zoning, water stress, build status)',
      terms: [
        term(ctx, 'is_greenfield'),
        calc('lt15', 'Hours below 15 C', h.lt15, 'h'), calc('gt30', 'Hours above 30 C', h.gt30, 'h'),
        ...(opt.dist_key ? [term(ctx, opt.dist_key)] : []),
      ],
      result: o.ko_pass ? 1 : 0, unit: o.ko_pass ? 'pass' : 'knocked out',
      note: o.ko_pass ? 'All gates hold.' : `Fails: ${o.ko_failures.join('; ')}.`,
    },
    {
      title: 'Heat drawn from the data center',
      tex: [String.raw`Q_{src} = \sum_{t=1}^{8760} q_{dc}\cdot d\big(T_{amb}(t)\big)\cdot c_{cap}\cdot 0.998`,
        String.raw`d = \text{share of the hour the heat user needs heat (or cooling)},\quad c_{cap} = \text{off-taker size cap}`],
      tex_values: String.raw`Q_{src} = ${tn(a.q_src_mwh, 0)}\ \mathrm{MWh/yr}`,
      formula: 'Q_src(t) = q_dc × demand(T_amb) × cap × 0.998 uptime  (demand follows heating or cooling need, or is constant for process loads)',
      terms: [term(ctx, 'q_dc_mw'), calc('cap', 'Off-taker size cap', a.cap_fraction, '-'), calc('util', 'Utilisation of DC heat', a.utilisation, '-')],
      result: a.q_src_mwh, unit: 'MWh/yr',
    },
    {
      title: o.key === 'orc' ? 'Power cycle' : 'Heat pump lift',
      tex: o.key === 'orc'
        ? [String.raw`\eta = 0.45\left(1 - \frac{T_{amb} + 10 + 273.15}{T_{dc} + 273.15}\right)`]
        : [String.raw`\text{direct exchange if } T_{dc} \ge T_{sink} + ${C.approach_k}\ \mathrm{K}`,
          String.raw`\mathrm{COP} = \min\left(${C.cop_cap},\; ${C.carnot_eta}\cdot\frac{T_{sink} + ${C.approach_k} + 273.15}{(T_{sink} + ${C.approach_k}) - (T_{dc} - ${C.approach_k})}\right),\qquad W_{hp} = \frac{Q_{src}}{\mathrm{COP} - 1}`],
      formula: o.key === 'orc'
        ? 'η = 0.45 × (1 − (T_amb + 10 + 273.15) / (T_dc + 273.15))'
        : `direct exchange if T_dc ≥ T_sink + ${C.approach_k} K; else COP = min(${C.cop_cap}, ${C.carnot_eta} × (T_sink + 5 + 273.15) / lift), W = Q_src / (COP − 1)`,
      terms: [calc('t_sink', 'Sink temperature', o.t_sink_c, 'C'),
        calc('cop', o.key === 'orc' ? 'Mean cycle efficiency' : 'Mean COP', o.key === 'orc' ? a.orc_mean_eta : a.mean_cop ?? 'direct', null as unknown as string),
        calc('direct_h', 'Hours with direct exchange', a.direct_hx_hours, 'h')],
      result: o.key === 'orc' ? a.q_del_mwh : a.w_hp_mwh, unit: o.key === 'orc' ? 'MWh_e/yr' : 'MWh_e/yr heat pump',
    },
    {
      title: 'Product, value and CO2',
      tex: productTex[a.product_unit] ?? productTex.MWh_th,
      tex_values: String.raw`V = \$${tn(a.value_usd, 0)},\quad \text{carbon credit} = \Delta CO_2 \cdot p_{CO_2} = \$${tn(a.carbon_rev_usd, 0)}\ \text{per year}`,
      formula: productFormula[a.product_unit] ?? productFormula.MWh_th,
      terms: [term(ctx, 'p_fuel_usd_kwh'), term(ctx, 'p_elec_usd_kwh'), term(ctx, 'ci_fuel_g_kwh'), term(ctx, 'ci_grid_g_kwh'), term(ctx, 'p_co2_usd_ton'),
        calc('product', 'Product', product(o)), calc('abated', 'Net CO2 avoided', a.net_abated_tco2, 't/yr')],
      result: a.value_usd + a.carbon_rev_usd, unit: 'USD/yr revenue',
    },
    {
      title: 'Investment and payback',
      tex: [String.raw`\mathrm{CAPEX} = q_{dc}\, c_{cap}\cdot ${opt.capex_usd_kw}\,\tfrac{\$}{kW} \;+\; L_{pipe}\cdot ${opt.pipe_usd_m}\,\tfrac{\$}{m} \;+\; \dot Q_{hp}\cdot ${C.hp_capex_usd_kw}\,\tfrac{\$}{kW}`,
        String.raw`\text{payback} = \frac{\mathrm{CAPEX}}{V + V_{CO_2} - C_{hp} - 0.02\,\mathrm{CAPEX}}`],
      tex_values: a.net_annual_usd > 0
        ? String.raw`\text{payback} = \frac{\$${tn(a.capex_usd, 0)}}{\$${tn(a.net_annual_usd, 0)}\ /\text{yr}} = ${tn(a.payback_yr, 1)}\ \text{years}`
        : String.raw`\text{net cash flow} = \$${tn(a.net_annual_usd, 0)} \le 0 \;\Rightarrow\; \text{never pays back}`,
      formula: `CAPEX = q_dc × cap × ${opt.capex_usd_kw} $/kW + distance × ${opt.pipe_usd_m} $/m + heat pump × ${C.hp_capex_usd_kw} $/kW;  payback = CAPEX / (revenue − heat pump power − 2 % CAPEX)`,
      terms: [calc('capex', 'CAPEX', a.capex_usd, 'USD'), calc('hp_cost', 'Heat pump electricity', a.hp_elec_cost_usd, 'USD/yr'), calc('net', 'Net cash flow', a.net_annual_usd, 'USD/yr')],
      result: a.payback_yr, unit: 'years',
      note: 'Specific costs are generic planning values, so payback is indicative.',
    },
    {
      title: 'Viability score',
      tex: [String.raw`\text{Viability} = G\cdot\left(${VW.thermo.toFixed(2)}\,P_{thermo} + ${VW.climate.toFixed(2)}\,P_{climate} + ${VW.econ.toFixed(2)}\,P_{econ} + ${VW.util.toFixed(2)}\,P_{util}\right)`,
        o.key === 'orc'
          ? String.raw`P_{thermo} = 5\cdot\frac{\eta}{0.12},\qquad P_{econ} = 5\cdot\frac{15 - \text{payback}}{15 - 3}\ \text{(clipped to 0 to 5)}`
          : String.raw`P_{thermo} = 5\cdot\frac{Q_{del} - W_{hp}}{Q_{del}},\qquad P_{econ} = 5\cdot\frac{15 - \text{payback}}{15 - 3}\ \text{(clipped to 0 to 5)}`],
      tex_values: String.raw`= ${o.ko_pass ? 1 : 0}\cdot\left(${VW.thermo.toFixed(2)}\cdot ${tn(s.p_thermo)} + ${VW.climate.toFixed(2)}\cdot ${tn(s.p_climate)} + ${VW.econ.toFixed(2)}\cdot ${tn(s.p_econ)} + ${VW.util.toFixed(2)}\cdot ${tn(s.p_util)}\right) = \mathbf{${tn(o.viability)}}`,
      formula: 'viability = G × (0.30·P_thermo + 0.30·P_climate + 0.25·P_econ + 0.15·P_util), each 0 to 5;  P_thermo = 5 × free-heat share (ORC: 5 × efficiency / 12 %)',
      terms: [calc('p_thermo', 'P thermo (share of delivered heat not from heat-pump power)', s.p_thermo, '0-5'), calc('p_climate', 'P climate (demand hours)', s.p_climate, '0-5'),
        calc('p_econ', 'P econ (payback 15 → 3 yr)', s.p_econ, '0-5'), calc('p_util', 'P util (heat used, distance)', s.p_util, '0-5')],
      result: o.viability, unit: 'of 5',
    },
    {
      title: 'Eco grade (independent of viability)',
      tex: [String.raw`E = ${EW.ghg.toFixed(2)}\,e_{GHG} + ${EW.water.toFixed(2)}\,e_{water} + ${EW.local.toFixed(2)}\,e_{local}`,
        String.raw`\text{grade} = \begin{cases} A & E \ge 4.2 \\ B & E \ge 3.4 \\ C & E \ge 2.6 \\ D & E \ge 1.8 \\ F & \text{otherwise} \end{cases}`],
      tex_values: String.raw`E = ${EW.ghg.toFixed(2)}\cdot ${tn(e.e_ghg)} + ${EW.water.toFixed(2)}\cdot ${tn(e.e_water)} + ${EW.local.toFixed(2)}\cdot ${tn(e.e_local)} = \mathbf{${tn(o.eco_score)}}\ \Rightarrow\ \text{grade ${o.eco_grade}}`,
      formula: 'E = 0.40·e_GHG + 0.30·e_water + 0.30·e_local;  e_GHG scores CO2 avoided per MWh delivered against a fully displaced gas boiler (fuel CI / 0.90); e_water adds a credit for cooling-tower water saved;  A ≥ 4.2, B ≥ 3.4, C ≥ 2.6, D ≥ 1.8, else F',
      terms: [calc('e_ghg', 'e GHG', e.e_ghg, '1-5'), calc('e_water', 'e water', e.e_water, '1-5'), calc('e_local', 'e local habitat', e.e_local, '1-5'),
        term(ctx, 'wsi_index'), term(ctx, 'eco_sens_index'), term(ctx, 'mit_tier')],
      result: o.eco_score, unit: `grade ${o.eco_grade}`,
    },
  ];
}

function toOption(ctx: Ctx, o: DsxOption, rank: number | null): OptionResult {
  const a = o.annual, b = ctx.baseline;
  // only evaporative heat rejection saves water when heat is diverted to reuse
  const evap = ctx.evaporative && (b.water_use_m3_yr ?? 0) > 0 && (b.heat_rejected_mwh_yr ?? 0) > 0;
  const waterFromRejection = evap ? (b.water_use_m3_yr! * Math.min(1, a.q_src_mwh / b.heat_rejected_mwh_yr!)) : 0;
  const water = waterFromRejection + (a.product_unit === 'm3' ? a.product_qty : 0);
  const flows: EnergyFlow[] = [
    { source: 'Data center', target: 'Heat recovery', mwh_yr: a.q_src_mwh, kind: 'heat' },
    ...(a.w_hp_mwh > 0 ? [{ source: 'Grid', target: 'Heat pump', mwh_yr: a.w_hp_mwh, kind: 'electricity' as const }] : []),
    { source: 'Heat recovery', target: o.name, mwh_yr: a.q_del_mwh, kind: a.product_unit === 'MWh_e' ? 'electricity' : 'heat' },
  ];
  const capex: Record<string, number> = {};
  if (a.capex_plant_usd) capex.plant = a.capex_plant_usd;
  if (a.capex_pipe_usd) capex.pipeline = a.capex_pipe_usd;
  if (a.capex_hp_usd) capex.heat_pump = a.capex_hp_usd;
  const used = new Set<string>(KEYS);
  return {
    option_id: o.key,
    name: o.name,
    rank,
    feasible: o.ko_pass,
    score: o.viability,
    eco_grade: o.eco_grade,
    components: [o.key],
    product: product(o),
    ko_reasons: o.ko_failures,
    implementation: IMPLEMENTATION[o.key] ?? null,
    capex_breakdown: capex,
    kpis: {
      heat_recovered_mwh_yr: a.q_src_mwh,
      heat_delivered_mwh_yr: a.product_unit === 'MWh_e' ? null : a.q_del_mwh,
      electricity_used_mwh_yr: a.w_hp_mwh,
      electricity_saved_mwh_yr: a.product_unit === 'MWh_e' ? a.q_del_mwh : a.product_unit === 'MWh_cool' ? a.product_qty / ENGINE.C.chiller_cop : null,
      co2_avoided_t_yr: a.net_abated_tco2,
      water_saved_m3_yr: water || null,
      net_value_usd_yr: a.net_annual_usd,
      capex_usd: a.capex_usd,
      payback_yr: a.payback_yr,
      pue_baseline: b.pue ?? null,
      pue_with: null,
      wue_baseline_l_kwh: b.wue_l_kwh ?? null,
      wue_with_l_kwh: null,
      ere: b.facility_energy_mwh_yr && b.it_energy_mwh_yr ? (b.facility_energy_mwh_yr - a.q_src_mwh) / b.it_energy_mwh_yr : null,
      cop: a.mean_cop,
      capacity_factor: a.utilisation,
    },
    energy_balance: flows,
    // where the server heat goes: all IT energy becomes heat in the cooling loop; the pathway takes Q_src
    heat_loops: o.ko_pass && (b.it_energy_mwh_yr ?? 0) > 0 ? [{
      name: String(ctx.site.cooling_type), mwh_yr: b.it_energy_mwh_yr!, return_c: Number(ctx.site.t_dc_base_c),
      routes: [
        { name: o.name, mwh_yr: Math.min(a.q_src_mwh, b.it_energy_mwh_yr!), kind: 'reuse' as const },
        { name: ctx.evaporative ? 'Cooling tower' : 'Dry cooler', mwh_yr: Math.max(0, b.it_energy_mwh_yr! - a.q_src_mwh), kind: 'cooling' as const },
      ],
    }] : [],
    details: {
      build_mode: o.mode, t_sink_c: o.t_sink_c, ...o.subscores, viability_ungated: o.viability_ungated,
      eco_score: o.eco_score, ...o.eco_subscores, direct_hx_hours: a.direct_hx_hours,
      // money and energy pieces for the pie charts (USD/yr and MWh/yr)
      money_product_usd: a.value_usd, money_carbon_usd: a.carbon_rev_usd, money_hp_usd: a.hp_elec_cost_usd,
      money_om_usd: Math.round(0.02 * a.capex_usd), money_net_usd: a.net_annual_usd,
      capex_plant_usd: a.capex_plant_usd, capex_pipe_usd: a.capex_pipe_usd, capex_hp_usd: a.capex_hp_usd,
      energy_src_mwh: a.q_src_mwh, energy_hp_mwh: a.w_hp_mwh, energy_del_mwh: a.q_del_mwh, product: ENGINE.OPTIONS.find((x) => x.key === o.key)?.product ?? null,
    },
    calculation: steps(ctx, o),
    calculation_inputs: [...ctx.inputs.values()].filter((i) => used.has(i.key)),
  };
}

/** Sensitivity of the best option's net value to every input that has a low / high range. */
function tornado(site: DsxSite, inputs: InputValue[], climate: DailyClimate, best: DsxOption): Tornado | null {
  const bars = [];
  for (const iv of inputs) {
    const k = iv.key as keyof DsxSite;
    if (!KEYS.includes(k) || iv.sens_low == null || iv.sens_high == null || typeof site[k] !== 'number') continue;
    const at = (v: number) => {
      const { site: s2 } = toDsxSite({ ...site, [k]: v });
      (s2 as Record<string, unknown>).baseline_evaporative = (site as Record<string, unknown>).baseline_evaporative;
      return ENGINE.evaluate(s2, climate.t_min, climate.t_max).options.find((x) => x.key === best.key)!.annual.net_annual_usd;
    };
    try {
      bars.push({ input: k, label: LABEL[k], low_value: iv.sens_low, high_value: iv.sens_high, metric_low: at(iv.sens_low), metric_high: at(iv.sens_high), flag: iv.flag });
    } catch { /* input outside the evaluator's range */ }
  }
  bars.sort((x, y) => Math.abs(y.metric_high - y.metric_low) - Math.abs(x.metric_high - x.metric_low));
  const top = bars.filter((b) => b.metric_high !== b.metric_low).slice(0, 10);
  return top.length ? { option_id: best.key, metric: 'net_value_usd_yr', unit: 'USD/yr', base: best.annual.net_annual_usd, bars: top } : null;
}

export interface DsxRunArgs {
  siteId: string;
  lat: number;
  lon: number;
  mode?: string | null;
  /** inputs_used of the backend's excel_ranking result (31 keys) */
  inputsUsed: Record<string, unknown>;
  /** flagged inputs from the backend (sources, ranges) */
  inputs: InputValue[];
  baseline: Baseline;
  weather?: Record<string, unknown>;
  keepInputs?: boolean;
  planned?: ModelResult['planned_site'];
}

export async function runDsx(a: DsxRunArgs): Promise<ModelResult> {
  const mode = a.mode && DSX_MODEL.modes.includes(a.mode) ? a.mode : DSX_MODEL.default_mode;
  const { site, notes } = toDsxSite(a.inputsUsed);
  const evaporative = a.inputsUsed.baseline_cooling_evaporative !== false;
  (site as Record<string, unknown>).baseline_evaporative = evaporative ? 1 : 0;
  const climate = await dailyClimate(a.lat, a.lon, a.weather);
  const base = ENGINE.evaluate(site, climate.t_min, climate.t_max);
  const shown = base;
  const shownSite = site;
  const inputs = new Map(a.inputs.map((i) => [i.key, i]));
  const ctx: Ctx = { site: shownSite, eval: shown, climate, inputs, baseline: a.baseline, evaporative };
  let rank = 0;
  const options = shown.options.map((o) => toOption(ctx, o, o.ko_pass ? ++rank : null));
  const best = shown.options.find((o) => o.ko_pass);

  const warnings: string[] = [];
  if (climate.synthetic) warnings.push(`Climate: ${climate.source}.`);
  warnings.push(...notes);
  warnings.push(`CAPEX: heat pump, absorption chiller, ORC, ATES and desalination costs are sourced; the other plant costs are DSX planning values, so payback is indicative.${evaporative ? ' Water saved is scaled from the baseline evaporative cooling water.' : ''}`);

  return {
    site_id: a.siteId,
    model: DSX_MODEL_NAME,
    mode,
    model_version: ENGINE.VERSION,
    score_scale: '0 to 5 viability; eco grade A to F scored separately',
    baseline: a.baseline,
    options,
    tornado: best ? tornado(shownSite, [...inputs.values()], climate, best) : null,
    warnings,
    inputs_used: { ...shownSite, climate_source: climate.source },
    inputs: a.keepInputs ? [...inputs.values()] : [],
    planned_site: a.planned ?? null,
  };
}
