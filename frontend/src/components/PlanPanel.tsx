import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { num } from '../format';
import type { CoolingProfile, ModelResult, OptionResult } from '../types/api';
import { HeatOrderSelect, PROFIT_FALLBACK, rankHeatOptions, reuseShare, totalNpv, type HeatOrder } from './HeatFlow';
import { coolingOnly, Details, money, Vendors } from './Results';

export interface PlanPoint { lat: number; lng: number }

const REUSE = [
  { id: 'any', label: 'Compare heat reuse designs' },
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

function matchingOptions(result: ModelResult, path: string) {
  const route = REUSE.find((item) => item.id === path);
  const matches = (o: OptionResult) => {
    if (path === 'cooling') return coolingOnly(o);
    if (path === 'any') return o.feasible && !coolingOnly(o);
    if (route?.screening) return o.option_id === path;
    return [...o.components, o.option_id.replace(/^ko:/, '')].some((part) => route?.engineering?.test(part));
  };
  return result.options.filter(matches);
}

export default function PlanPanel({ point, onClose }: { point: PlanPoint; onClose: () => void }) {
  const [profiles, setProfiles] = useState<CoolingProfile[]>([]);
  const [profileError, setProfileError] = useState('');
  const [size, setSize] = useState('100');
  const [unit, setUnit] = useState<'MW' | 'GW'>('MW');
  const [cooling, setCooling] = useState('dlc_warm');
  const [pue, setPue] = useState('');
  const [greenfield, setGreenfield] = useState(1);
  const [path, setPath] = useState('any');
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
  }, [point.lat, point.lng]);

  const profile = profiles.find((p) => p.cooling_profile_id === cooling);
  const screening = REUSE.some((route) => route.id === path && route.screening);
  const run = async () => {
    const itMw = Number(size.replace(',', '.')) * (unit === 'GW' ? 1000 : 1);
    if (!Number.isFinite(itMw) || itMw <= 0 || itMw > 10000) {
      setState({ status: 'error', error: 'Enter an IT load above 0 and up to 10 GW.' });
      return;
    }
    const designPue = screening && pue.trim() ? Number(pue.replace(',', '.')) : null;
    if (designPue != null && (!Number.isFinite(designPue) || designPue < 1 || designPue > 3)) {
      setState({ status: 'error', error: 'Enter a design PUE between 1 and 3.' });
      return;
    }
    const id = ++request.current;
    setSelected('');
    setState({ status: 'loading' });
    try {
      const result = await api.plan({
        lat: point.lat, lon: point.lng, it_mw: itMw, cooling_profile: cooling,
        is_greenfield: greenfield, pue: designPue, model: screening ? 'excel_ranking' : 'heat_chain', tornado: false,
      });
      if (request.current === id) setState({ status: 'ready', result });
    } catch (e) {
      if (request.current === id) setState({ status: 'error', error: e instanceof Error ? e.message : String(e) });
    }
  };

  const result = state.status === 'ready' ? state.result : null;
  const matches = result ? matchingOptions(result, path) : [];
  const feasible = matches.filter((o) => o.feasible);
  const rankByHeat = result?.model === 'heat_chain' && path !== 'cooling';
  const comparison = rankByHeat ? rankHeatOptions(feasible, order) : { options: feasible, fallback: false };
  const designs = comparison.options;
  const design = designs.find((o) => o.option_id === selected) ?? designs[0];

  return (
    <aside className="site-panel plan-panel" aria-label="Plan a new data center">
      <header>
        <div className="panel-title">
          <p className="eyebrow-sm">Plan a new data center</p>
          <h3>New site</h3>
          <p className="muted">{num(point.lat, 3)}, {num(point.lng, 3)} · click the map to move it</p>
        </div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <form className="plan-form" onSubmit={(e) => { e.preventDefault(); void run(); }}
        onChange={() => setState({ status: 'idle' })}>
        <label>IT load
          <span className="with-unit">
            <input disabled={state.status === 'loading'} inputMode="decimal" value={size} onChange={(e) => setSize(e.target.value)} />
            <select disabled={state.status === 'loading'} aria-label="IT load unit" value={unit} onChange={(e) => setUnit(e.target.value === 'GW' ? 'GW' : 'MW')}>
              <option>MW</option><option>GW</option>
            </select>
          </span>
        </label>
        <label>Server cooling
          <select disabled={state.status === 'loading'} value={cooling} onChange={(e) => setCooling(e.target.value)} title={profile?.description ?? undefined}>
            {profiles.map((p) => <option key={p.cooling_profile_id} value={p.cooling_profile_id}>{p.label}</option>)}
          </select>
        </label>
        <label className="full">Project type
          <select disabled={state.status === 'loading'} value={greenfield} onChange={(e) => setGreenfield(Number(e.target.value))}>
            <option value={1}>New build</option><option value={0}>Retrofit</option>
          </select>
        </label>
        <label className="full">Design path
          <select disabled={state.status === 'loading'} value={path} onChange={(e) => setPath(e.target.value)}>
            <optgroup label="Cooling"><option value="cooling">Compare heat rejection designs</option></optgroup>
            <optgroup label="Heat reuse">
              {REUSE.map((route) => <option key={route.id} value={route.id}>{route.label}{route.screening ? ' (screening)' : ''}</option>)}
            </optgroup>
          </select>
        </label>
        {screening && <label className="full">Design PUE (optional)
          <input disabled={state.status === 'loading'} inputMode="decimal" value={pue}
            onChange={(e) => setPue(e.target.value)} placeholder={profile?.pue_typical?.toString()} />
        </label>}
        <button type="submit" className="btn btn-primary full" disabled={!profile || state.status === 'loading'}>
          {state.status === 'loading' ? 'Running…' : 'Generate plan'}
        </button>
      </form>
      <div className="panel-body">
        {profileError && <p role="alert" className="error">{profileError}</p>}
        {state.status === 'loading' && <p role="status" className="muted">Fetching weather and running the model…</p>}
        {state.status === 'error' && <p role="alert" className="error">{state.error}</p>}
        {result && (
          <div className="results">
            {screening && <p className="muted">Concept screening uses regional estimates and default site distances. Verify local demand and infrastructure before sizing.</p>}
            {design ? (
              <>
                {rankByHeat && feasible.length > 1 &&
                  <HeatOrderSelect order={order} onChange={(next) => { setOrder(next); setSelected(''); }} />}
                {comparison.fallback && <p className="muted">{PROFIT_FALLBACK}</p>}
                {designs.length > 1 && (
                    <label className="plan-alternatives">Compare designs
                      <select value={design.option_id} onChange={(e) => setSelected(e.target.value)}>
                        {designs.map((o) => <option key={o.option_id} value={o.option_id}>
                          {o.name}{rankByHeat ? ` · ${reuseShare(o, result.baseline.it_energy_mwh_yr)} to reuse` : ''}
                          {rankByHeat && order !== 'value' ? ` · ${money(o.reuse_npv_usd)} reuse NPV` : ` · ${money(totalNpv(o))} NPV`}
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
            <Vendors vendors={result.cooling_vendors} title={`Server cooling suppliers · ${profile?.label ?? cooling}`} />
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
