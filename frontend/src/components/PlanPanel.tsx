import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { compact, num } from '../format';
import type { CoolingProfile, InputValue, ModelResult, OptionResult, PlanDefaults } from '../types/api';
import { HeatOrderSelect, PROFIT_FALLBACK, rankHeatOptions, reuseShare, totalNpv, type HeatOrder } from './HeatFlow';
import { PERSPECTIVES } from '../perspectives';
import { COOLING_COMPONENTS, coolingOnly, Details, money, Vendors } from './Results';

export interface PlanPoint { lat: number; lng: number }

const VERA_RUBIN_PROFILE = 'dlc_hot';
const VERA_RUBIN_RACK_KW = 150;

const REUSE = [
  { id: 'any', label: 'Auto: Best + Hybrid (recommended)' },
  { id: 'fish_farm', label: 'Fish farm (aquaculture)', screening: true },
  { id: 'biogas', label: 'Biogas production', engineering: /^biogas_/ },
  { id: 'district_heating', label: 'District heating', engineering: /^(district_heating|dh_)/ },
  { id: 'absorption_cooling', label: 'Heat-driven chilling', engineering: /^adsorption$/ },
  { id: 'orc', label: 'Organic Rankine cycle', engineering: /^orc$/ },
  { id: 'boiler_feedwater', label: 'Boiler feedwater preheat', engineering: /^feedwater$/ },
  { id: 'desalination', label: 'Desalination', engineering: /^desal_/ },
  { id: 'btes_ates', label: 'Seasonal thermal storage', engineering: /^(ates|btes)$/ },
  { id: 'dac', label: 'Direct air capture', screening: true },
  { id: 'biomass', label: 'Biomass processing', screening: true },
  { id: 'drying', label: 'Industrial drying', screening: true },
  { id: 'snow_melt', label: 'Radiant heating and snow melt', screening: true },
  { id: 'greenhouse', label: 'Greenhouse heating', screening: true },
];

interface ParamField {
  key: string;
  label: string;
  unit: string;
  scale?: number; // display = model / scale (e.g. 1000 converts m -> km, 0.01 converts fraction -> %)
  step?: string;
  min?: number;
  max?: number;
  group: 'market' | 'site' | 'plant';
}

const PARAM_FIELDS: ParamField[] = [
  { key: 'p_elec_usd_mwh', label: 'Electricity price', unit: 'USD/MWh', step: '1', min: 0, group: 'market' },
  { key: 'p_heat_usd_mwh', label: 'Local gas heat price', unit: 'USD/MWh', step: '1', min: 0, group: 'market' },
  { key: 'p_water_usd_m3', label: 'Water + sewer tariff', unit: 'USD/m³', step: '0.1', min: 0, group: 'market' },
  { key: 'wsi', label: 'Water stress (WSI)', unit: '0–5', step: '0.1', min: 0, max: 5, group: 'market' },
  { key: 'ci_grid_kg_mwh', label: 'Grid carbon intensity', unit: 'kg CO₂/MWh', step: '5', min: 0, group: 'market' },
  { key: 'p_co2_usd_t', label: 'Carbon price', unit: 'USD/t', step: '1', min: 0, group: 'market' },

  { key: 'd_dh_m', label: 'Distance to heat network', unit: 'km', scale: 1000, step: '0.5', min: 0, group: 'site' },
  { key: 'rho_heat_mwh_m', label: 'Linear heat density', unit: 'MWh/m/yr', step: '0.2', min: 0.1, group: 'site' },
  { key: 'd_coast_m', label: 'Distance to coast', unit: 'km', scale: 1000, step: '1', min: 0, group: 'site' },
  { key: 'd_pp_m', label: 'Distance to power plant', unit: 'km', scale: 1000, step: '1', min: 0, group: 'site' },
  { key: 'q_fw_mw', label: 'Feedwater heat demand', unit: 'MW', step: '1', min: 0, group: 'site' },
  { key: 'd_bio_m', label: 'Distance to biogas feedstock', unit: 'km', scale: 1000, step: '1', min: 0, group: 'site' },
  { key: 'geo_storage_score', label: 'Geo storage score', unit: '1–5', step: '1', min: 1, max: 5, group: 'site' },

  { key: 'liquid_heat_share', label: 'Liquid cooling share', unit: '%', scale: 0.01, step: '1', min: 0, max: 100, group: 'plant' },
  { key: 't_liquid_supply_c', label: 'Liquid supply temp', unit: '°C', step: '1', min: 15, max: 70, group: 'plant' },
  { key: 't_liquid_return_c', label: 'Liquid return temp', unit: '°C', step: '1', min: 20, max: 85, group: 'plant' },
  { key: 'capex_factor', label: 'CAPEX multiplier', unit: '×', step: '0.05', min: 0.2, max: 3, group: 'plant' },
  { key: 'discount_rate', label: 'Discount rate', unit: '%', scale: 0.01, step: '0.5', min: 1, max: 25, group: 'plant' },
  { key: 'lifetime_yr', label: 'Project lifetime', unit: 'yr', step: '1', min: 5, max: 40, group: 'plant' },
  { key: 'compute_capex_usd_mw', label: 'Vera Rubin hardware cost', unit: '$M/MW', scale: 1e6, step: '1', min: 1, group: 'plant' },
  { key: 'facility_capex_usd_mw', label: 'Facility shell & power', unit: '$M/MW', scale: 1e6, step: '0.5', min: 0, group: 'plant' },
];

function matchingOptions(result: ModelResult, path: string) {
  const route = REUSE.find((item) => item.id === path);
  const matches = (o: OptionResult) => {
    if (path === 'cooling') return coolingOnly(o);
    if (path === 'any') return o.feasible;
    if (route?.screening) return o.option_id === path;
    return [...o.components, o.option_id.replace(/^ko:/, '')].some((part) => route?.engineering?.test(part));
  };
  return result.options.filter(matches);
}

/** True when a chain combines cooling with >= 2 reuse/storage parts (hybrid heat reuse). */
function isHybridDesign(o: OptionResult) {
  const reuseParts = o.components.filter((c) => !COOLING_COMPONENTS.includes(c) && c !== 'heat_pump');
  return reuseParts.length >= 2;
}

interface Proposal {
  badge: string;
  subtitle: string;
  option: OptionResult;
}

function pickTwoProposals(feasible: OptionResult[], path: string): Proposal[] {
  if (feasible.length === 0) return [];
  if (path === 'any') {
    // two perspectives: cooling (most money saved) and heat waste (most heat reused that pays off)
    const cooling = feasible.filter(coolingOnly).sort((a, b) => totalNpv(b) - totalNpv(a))[0];
    const heat = rankHeatOptions(feasible, 'profitableHeat');
    const out: Proposal[] = [];
    if (cooling) out.push({ badge: PERSPECTIVES.cooling.label, subtitle: 'Most money saved through cooling', option: cooling });
    if (heat.options[0]) out.push({ badge: PERSPECTIVES.heat.label,
      subtitle: heat.fallback ? 'Best heat reuse here (does not pay off)' : 'Most heat reused that pays off', option: heat.options[0] });
    if (out.length) return out;
  }
  const byTotalNpv = [...feasible].sort((a, b) => totalNpv(b) - totalNpv(a));
  const first = byTotalNpv[0];

  const rest = byTotalNpv.filter((o) => o.option_id !== first.option_id);
  const hybrids = rest.filter(isHybridDesign);
  const reuseAlts = rest.filter((o) => !coolingOnly(o));

  let second: OptionResult | undefined;
  let secondBadge = 'Proposal 2 · Alternative';
  let secondSubtitle = 'Next best feasible configuration';

  if (path === 'cooling') {
    second = rest[0];
    secondSubtitle = 'Alternative heat rejection architecture';
  } else if (hybrids.length > 0) {
    // Prefer profitable hybrid by Total NPV, or highest Reuse NPV hybrid.
    const profitableHybrids = hybrids.filter((o) => (o.reuse_npv_usd ?? 0) > 0 && totalNpv(o) > 0);
    second = profitableHybrids[0] ?? [...hybrids].sort((a, b) => (b.reuse_npv_usd ?? -Infinity) - (a.reuse_npv_usd ?? -Infinity))[0];
    secondBadge = 'Proposal 2 · Hybrid Approach';
    secondSubtitle = 'Combines cooling with multi-path heat reuse / storage';
  } else if (reuseAlts.length > 0) {
    second = [...reuseAlts].sort((a, b) => (b.reuse_npv_usd ?? -Infinity) - (a.reuse_npv_usd ?? -Infinity))[0];
    secondBadge = 'Proposal 2 · Heat Reuse';
    secondSubtitle = 'Highest incremental value from heat recovery';
  } else {
    second = rest[0];
  }

  const proposals: Proposal[] = [{
    badge: isHybridDesign(first) ? 'Proposal 1 · Best Overall (Hybrid)' : 'Proposal 1 · Best Overall',
    subtitle: coolingOnly(first) ? 'Most economical cooling architecture' : 'Highest 20-year total NPV',
    option: first,
  }];
  if (second) {
    proposals.push({ badge: secondBadge, subtitle: secondSubtitle, option: second });
  }
  return proposals;
}

function defaultDisplayValue(field: ParamField, inputs: InputValue[], greenfield: number): string {
  if (field.key === 'facility_capex_usd_mw' && greenfield === 0) return '0';
  const item = inputs.find((i) => i.key === field.key);
  if (item == null || typeof item.value !== 'number') return '';
  const scaled = item.value / (field.scale ?? 1);
  return String(Number(scaled.toPrecision(4)));
}

export default function PlanPanel({ point, onClose }: { point: PlanPoint; onClose: () => void }) {
  const [profiles, setProfiles] = useState<CoolingProfile[]>([]);
  const [profileError, setProfileError] = useState('');
  const [sizingMode, setSizingMode] = useState<'size' | 'budget'>('size');
  const [size, setSize] = useState('100');
  const [unit, setUnit] = useState<'MW' | 'GW'>('MW');
  const [budget, setBudget] = useState('500');
  const [budgetUnit, setBudgetUnit] = useState<'M' | 'B'>('M');
  const [pue, setPue] = useState('');
  const [greenfield, setGreenfield] = useState(1);
  const [path, setPath] = useState('any');
  const [baselineRej, setBaselineRej] = useState('dry');
  const [customInputs, setCustomInputs] = useState<Record<string, string>>({});
  const [defaults, setDefaults] = useState<PlanDefaults | null>(null);
  const [openProposal, setOpenProposal] = useState<number>(0);
  const [selected, setSelected] = useState('');
  const [order, setOrder] = useState<HeatOrder>('profitableHeat');
  const request = useRef(0);
  const [state, setState] = useState<
    { status: 'idle' | 'loading' } | { status: 'error'; error: string } | { status: 'ready'; result: ModelResult }
  >({ status: 'idle' });

  useEffect(() => {
    api.coolingProfiles().then(setProfiles).catch((e: Error) => setProfileError(e.message));
  }, []);

  useEffect(() => {
    request.current += 1;
    setState({ status: 'idle' });
    setCustomInputs({});
    setDefaults(null);
    let alive = true;
    api.planDefaults(point.lat, point.lng)
      .then((d) => { if (alive) setDefaults(d); })
      .catch(() => { /* optional prefill */ });
    return () => { alive = false; };
  }, [point.lat, point.lng]);

  const profile = profiles.find((p) => p.cooling_profile_id === VERA_RUBIN_PROFILE);
  const screening = REUSE.some((route) => route.id === path && route.screening);

  const buildOverrides = (): { ok: true; overrides: Record<string, unknown> } | { ok: false; error: string } => {
    const out: Record<string, unknown> = {};
    if (baselineRej !== 'dry') out.baseline_rejection = baselineRej;
    for (const f of PARAM_FIELDS) {
      const raw = customInputs[f.key];
      if (raw == null || raw.trim() === '') continue;
      const parsed = Number(raw.replace(',', '.'));
      if (!Number.isFinite(parsed)) {
        return { ok: false, error: `Invalid number for "${f.label}".` };
      }
      if ((f.min != null && parsed < f.min) || (f.max != null && parsed > f.max)) {
        return { ok: false, error: `"${f.label}" must be between ${f.min ?? '-∞'} and ${f.max ?? '∞'}.` };
      }
      out[f.key] = parsed * (f.scale ?? 1);
    }
    return { ok: true, overrides: out };
  };

  const run = async () => {
    let itMw: number | null = null;
    let budgetUsd: number | null = null;
    if (sizingMode === 'size') {
      itMw = Number(size.replace(',', '.')) * (unit === 'GW' ? 1000 : 1);
      if (!Number.isFinite(itMw) || itMw <= 0 || itMw > 10000) {
        setState({ status: 'error', error: 'Enter an IT load above 0 and up to 10 GW.' });
        return;
      }
    } else {
      budgetUsd = Number(budget.replace(',', '.')) * (budgetUnit === 'B' ? 1e9 : 1e6);
      if (!Number.isFinite(budgetUsd) || budgetUsd <= 0 || budgetUsd > 1e12) {
        setState({ status: 'error', error: 'Enter a build budget above $0 and up to $1,000B.' });
        return;
      }
    }
    const designPue = screening && pue.trim() ? Number(pue.replace(',', '.')) : null;
    if (designPue != null && (!Number.isFinite(designPue) || designPue < 1 || designPue > 3)) {
      setState({ status: 'error', error: 'Enter a design PUE between 1 and 3.' });
      return;
    }
    const ov = buildOverrides();
    if (!ov.ok) {
      setState({ status: 'error', error: ov.error });
      return;
    }
    const id = ++request.current;
    setSelected('');
    setOpenProposal(0);
    setState({ status: 'loading' });
    try {
      const result = await api.plan({
        lat: point.lat,
        lon: point.lng,
        it_mw: itMw,
        budget_usd: budgetUsd,
        cooling_profile: VERA_RUBIN_PROFILE,
        is_greenfield: greenfield,
        pue: designPue,
        overrides: ov.overrides,
        model: screening ? 'excel_ranking' : 'heat_chain',
        tornado: false,
      });
      if (request.current === id) setState({ status: 'ready', result });
    } catch (e) {
      if (request.current === id) setState({ status: 'error', error: e instanceof Error ? e.message : String(e) });
    }
  };

  const result = state.status === 'ready' ? state.result : null;
  const matches = result ? matchingOptions(result, path) : [];
  const feasible = matches.filter((o) => o.feasible);
  const proposals = result && result.model === 'heat_chain' ? pickTwoProposals(feasible, path) : [];
  const rankByHeat = result?.model === 'heat_chain' && path !== 'cooling';
  const comparison = rankByHeat ? rankHeatOptions(feasible, order) : { options: feasible, fallback: false };
  const designs = comparison.options;
  const design = designs.find((o) => o.option_id === selected) ?? designs[0];
  const nCustomized = Object.values(customInputs).filter((v) => v.trim() !== '').length + (baselineRej !== 'dry' ? 1 : 0);
  const defaultInputs = result?.inputs?.length ? result.inputs : (defaults?.inputs ?? []);
  const estRacks = sizingMode === 'size'
    ? Math.max(0, Math.round((Number(size.replace(',', '.')) * (unit === 'GW' ? 1000 : 1) * 1000) / VERA_RUBIN_RACK_KW))
    : null;

  return (
    <aside className="site-panel plan-panel" aria-label="Plan a new data center">
      <header>
        <div className="panel-title">
          <p className="eyebrow-sm">Plan a new data center</p>
          <h3>New site</h3>
          <p className="muted">
            {num(point.lat, 3)}, {num(point.lng, 3)}
            {defaults?.template_site_id ? ` · regional data via ${defaults.template_site_id} (${defaults.template_km} km)` : ' · click the map to move it'}
          </p>
        </div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <form className="plan-form" onSubmit={(e) => { e.preventDefault(); void run(); }}
        onChange={() => { if (state.status === 'ready') setState({ status: 'idle' }); }}>
        <div className="full plan-chip-banner">
          <b>NVIDIA Vera Rubin</b>
          <span>NVL144 · 150 kW/rack · 45/55 °C DLC</span>
        </div>

        <div className="full seg" role="group" aria-label="Planning mode">
          <button type="button" aria-pressed={sizingMode === 'size'} className={sizingMode === 'size' ? 'on' : ''}
            onClick={() => { setSizingMode('size'); setState({ status: 'idle' }); }}>Size by IT load</button>
          <button type="button" aria-pressed={sizingMode === 'budget'} className={sizingMode === 'budget' ? 'on' : ''}
            onClick={() => { setSizingMode('budget'); setState({ status: 'idle' }); }}>Build for budget</button>
        </div>

        {sizingMode === 'size' ? (
          <label>IT load {estRacks != null && Number.isFinite(estRacks) && estRacks > 0 && <small className="muted">≈ {compact(estRacks)} racks</small>}
            <span className="with-unit">
              <input disabled={state.status === 'loading'} inputMode="decimal" value={size} onChange={(e) => setSize(e.target.value)} />
              <select disabled={state.status === 'loading'} aria-label="IT load unit" value={unit} onChange={(e) => setUnit(e.target.value === 'GW' ? 'GW' : 'MW')}>
                <option>MW</option><option>GW</option>
              </select>
            </span>
          </label>
        ) : (
          <label>Total budget (USD)
            <span className="with-unit">
              <input disabled={state.status === 'loading'} inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} />
              <select disabled={state.status === 'loading'} aria-label="Budget unit" value={budgetUnit} onChange={(e) => setBudgetUnit(e.target.value === 'B' ? 'B' : 'M')}>
                <option value="M">$M</option><option value="B">$B</option>
              </select>
            </span>
          </label>
        )}

        <label>Project type
          <select disabled={state.status === 'loading'} value={greenfield} onChange={(e) => setGreenfield(Number(e.target.value))}>
            <option value={1}>New build</option><option value={0}>Retrofit</option>
          </select>
        </label>

        <label className="full">Design focus
          <select disabled={state.status === 'loading'} value={path} onChange={(e) => setPath(e.target.value)}>
            <option value="any">{REUSE[0].label}</option>
            <optgroup label="Cooling"><option value="cooling">Heat rejection only</option></optgroup>
            <optgroup label="Specific heat reuse path">
              {REUSE.slice(1).map((route) => <option key={route.id} value={route.id}>{route.label}{route.screening ? ' (screening)' : ''}</option>)}
            </optgroup>
          </select>
        </label>

        {screening && <label className="full">Design PUE (optional)
          <input disabled={state.status === 'loading'} inputMode="decimal" value={pue}
            onChange={(e) => setPue(e.target.value)} placeholder={profile?.pue_typical?.toString()} />
        </label>}

        <details className="full plan-custom">
          <summary>
            <span>Customize site &amp; model parameters{nCustomized > 0 ? ` (${nCustomized} customized)` : ''}</span>
            {nCustomized > 0 && (
              <button type="button" className="link" onClick={(e) => {
                e.preventDefault();
                setCustomInputs({});
                setBaselineRej('dry');
                setState({ status: 'idle' });
              }}>Reset</button>
            )}
          </summary>
          <div className="plan-custom-body">
            <label className="full">Reference heat rejection
              <select value={baselineRej} onChange={(e) => setBaselineRej(e.target.value)}>
                <option value="dry">Dry cooler (no cooling water)</option>
                <option value="adiabatic">Adiabatic cooler (water on hot hours)</option>
                <option value="tower">Cooling tower (evaporative)</option>
              </select>
            </label>
            {(['market', 'site', 'plant'] as const).map((group) => (
              <div key={group} className="plan-param-group">
                <h5>{group === 'market' ? 'Energy, water & carbon prices' : group === 'site' ? 'Local distances & heat sinks' : 'Vera Rubin cooling & economics'}</h5>
                <div className="plan-param-grid">
                  {PARAM_FIELDS.filter((f) => f.group === group).map((f) => {
                    const ph = defaultDisplayValue(f, defaultInputs, greenfield);
                    return (
                      <label key={f.key}>
                        <span>{f.label} <small className="muted">({f.unit})</small></span>
                        <input
                          inputMode="decimal"
                          placeholder={ph}
                          value={customInputs[f.key] ?? ''}
                          onChange={(e) => setCustomInputs({ ...customInputs, [f.key]: e.target.value })}
                        />
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </details>

        <button type="submit" className="btn btn-primary full" disabled={state.status === 'loading'}>
          {state.status === 'loading' ? 'Running model…' : sizingMode === 'budget' ? 'Size compute & propose 2 designs' : 'Propose 2 designs'}
        </button>
      </form>

      <div className="panel-body">
        {profileError && <p role="alert" className="error">{profileError}</p>}
        {state.status === 'loading' && <p role="status" className="muted">Fetching weather and running hourly physics…</p>}
        {state.status === 'error' && <p role="alert" className="error">{state.error}</p>}
        {result && (
          <div className="results">
            {screening && <p className="muted">Concept screening uses regional estimates and default site distances. Verify local demand and infrastructure before sizing.</p>}

            {result.budget_summary && (
              <div className="plan-budget-card">
                <p className="eyebrow-sm">Optimal compute for {money(result.budget_summary.budget_usd)} budget</p>
                <div className="plan-budget-hero">
                  <strong>{num(result.budget_summary.solved_it_mw, 1)} MW IT</strong>
                  <span>{compact(result.budget_summary.vera_rubin_racks)} Vera Rubin NVL144 racks ({num(result.budget_summary.rack_kw, 0)} kW/rack)</span>
                </div>
                <div className="plan-budget-split">
                  <span>Compute <b>{money(result.budget_summary.compute_capex_usd)}</b></span>
                  <span>Facility &amp; power <b>{money(result.budget_summary.facility_capex_usd)}</b></span>
                  <span>Cooling &amp; reuse <b>{money(result.budget_summary.cooling_reuse_capex_usd)}</b></span>
                </div>
              </div>
            )}

            {proposals.length > 0 ? (
              <div className="plan-proposals">
                <h4>{path === 'any' ? 'Two perspectives' : '2 recommended proposals'}</h4>
                {proposals.map((prop, idx) => {
                  const o = prop.option;
                  const on = openProposal === idx;
                  const fit = o.details.budget_fit as { max_it_mw_for_budget?: number; max_vera_rubin_racks?: number } | undefined;
                  return (
                    <div key={o.option_id} className={`plan-proposal${on ? ' open' : ''}`}>
                      <button type="button" className="opt-head" onClick={() => setOpenProposal(on ? -1 : idx)} aria-expanded={on}>
                        <span className="opt-rank">{idx + 1}</span>
                        <span className="opt-name">
                          <span className="plan-proposal-badge">{prop.badge}</span>
                          {o.name}
                          <small>
                            {prop.subtitle}
                            {!coolingOnly(o) && ` · ${reuseShare(o, result.baseline.it_energy_mwh_yr)} to reuse`}
                            {fit?.max_it_mw_for_budget != null && ` · fits ${num(fit.max_it_mw_for_budget, 1)} MW (${compact(fit.max_vera_rubin_racks)} racks)`}
                          </small>
                        </span>
                        <span className={`opt-npv${totalNpv(o) < 0 ? ' neg' : ''}`}>
                          {`${totalNpv(o) > 0 ? '+' : ''}${money(totalNpv(o))}`}
                          <small>Total NPV</small>
                        </span>
                        <span className="chev" aria-hidden>{on ? '−' : '+'}</span>
                      </button>
                      {on && <Details o={o} r={result} planned />}
                    </div>
                  );
                })}

                {designs.length > proposals.length && (
                  <details className="plan-all">
                    <summary>Explore all {designs.length} feasible designs</summary>
                    <div className="plan-all-body">
                      {rankByHeat && feasible.length > 1 &&
                        <HeatOrderSelect order={order} onChange={(next) => { setOrder(next); setSelected(''); }} />}
                      {comparison.fallback && <p className="muted">{PROFIT_FALLBACK}</p>}
                      <label className="plan-alternatives">Compare designs
                        <select value={design?.option_id ?? ''} onChange={(e) => setSelected(e.target.value)}>
                          {designs.map((o) => <option key={o.option_id} value={o.option_id}>
                            {o.name}{rankByHeat ? ` · ${reuseShare(o, result.baseline.it_energy_mwh_yr)} to reuse` : ''}
                            {rankByHeat && order !== 'value' ? ` · ${money(o.reuse_npv_usd)} reuse NPV` : ` · ${money(totalNpv(o))} NPV`}
                          </option>)}
                        </select>
                      </label>
                      {design && (
                        <>
                          <h4>{design.name}</h4>
                          <Details o={design} r={result} planned />
                        </>
                      )}
                    </div>
                  </details>
                )}
              </div>
            ) : design ? (
              <>
                {designs.length > 1 && (
                  <label className="plan-alternatives">Compare designs
                    <select value={design.option_id} onChange={(e) => setSelected(e.target.value)}>
                      {designs.map((o) => <option key={o.option_id} value={o.option_id}>
                        {o.name} · {money(totalNpv(o))} NPV
                      </option>)}
                    </select>
                  </label>
                )}
                <h4>{design.name}</h4>
                <Details o={design} r={result} planned />
                {!design.vendors?.length && <p className="muted">No implementation suppliers are listed for this design.</p>}
              </>
            ) : (
              <>
                <p className="muted">No design for this path passed the model checks at this location.</p>
                {[...new Set(matches.flatMap((o) => o.ko_reasons))].map((reason) => <p className="muted" key={reason}>{reason}</p>)}
              </>
            )}

            <Vendors vendors={result.cooling_vendors} title={`Server cooling suppliers · ${profile?.label ?? 'Vera Rubin DLC'}`} />
            {result.warnings.length > 0 && <details className="notes">
              <summary>Site assumptions and model notes</summary>
              <ul>{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </details>}
          </div>
        )}
      </div>
    </aside>
  );
}
