import { useEffect, useState } from 'react';
import { api } from '../api';
import { num } from '../format';
import type { CoolingProfile, ModelResult, SiteInputs } from '../types/api';
import { Inputs, Results } from './SitePanel';

export interface PlanPoint { lat: number; lng: number }

/**
 * Plan a future data center: the user clicked a point on the map, enters the IT size (MW or GW)
 * and the cooling, and gets the ranked options with cost, savings and payback (POST /api/plan).
 */
export default function PlanPanel({ point, onClose }: { point: PlanPoint; onClose: () => void }) {
  const [profiles, setProfiles] = useState<CoolingProfile[]>([]);
  const [name, setName] = useState('');
  const [size, setSize] = useState('100');
  const [unit, setUnit] = useState<'MW' | 'GW'>('MW');
  const [cooling, setCooling] = useState('dlc_warm');
  const [pue, setPue] = useState('');
  const [greenfield, setGreenfield] = useState(1);
  const [mode, setMode] = useState<string | undefined>();
  const [tab, setTab] = useState<'results' | 'inputs'>('results');
  const [state, setState] = useState<{ s: 'idle' | 'loading' } | { s: 'error'; e: string } | { s: 'ok'; r: ModelResult }>({ s: 'idle' });

  useEffect(() => { api.coolingProfiles().then(setProfiles).catch(() => setProfiles([])); }, []);

  const itMw = (parseFloat(size.replace(',', '.')) || 0) * (unit === 'GW' ? 1000 : 1);
  const profile = profiles.find((p) => p.cooling_profile_id === cooling);

  const run = (m = mode) => {
    if (itMw <= 0) { setState({ s: 'error', e: 'Enter an IT load above 0.' }); return; }
    setState({ s: 'loading' });
    api.plan({
      lat: point.lat, lon: point.lng, it_mw: itMw, cooling_profile: cooling, name: name || null,
      pue: pue ? parseFloat(pue.replace(',', '.')) : null, is_greenfield: greenfield, mode: m ?? null,
    }).then((r) => setState({ s: 'ok', r })).catch((e: Error) => setState({ s: 'error', e: e.message }));
  };

  // new point: rerun automatically if there was a result
  useEffect(() => { if (state.s === 'ok') run(); }, [point.lat, point.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  const r = state.s === 'ok' ? state.r : null;
  const inputs: SiteInputs | null = r ? {
    site_id: 'planned', inputs: r.inputs, weather: {},
    flag_counts: r.inputs.reduce((a, i) => ({ ...a, [i.flag]: (a[i.flag] ?? 0) + 1 }), {} as Record<string, number>),
  } : null;

  return (
    <aside className="site-panel plan-panel" aria-label="Plan a new data center">
      <header>
        <div>
          <p className="eyebrow-sm">Plan a new data center</p>
          <h3>{name || 'New site'}</h3>
          <p className="muted">{num(point.lat, 3)}, {num(point.lng, 3)} · click the map to move it</p>
        </div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>

      <form className="plan-form" onSubmit={(e) => { e.preventDefault(); run(); }}>
        <label className="full">Name <input value={name} onChange={(e) => setName(e.target.value)} placeholder="optional" /></label>
        <label>IT load
          <span className="with-unit">
            <input inputMode="decimal" value={size} onChange={(e) => setSize(e.target.value)} aria-label="IT load" />
            <span className="seg">
              {(['MW', 'GW'] as const).map((u) => (
                <button type="button" key={u} className={unit === u ? 'on' : ''} onClick={() => setUnit(u)}>{u}</button>
              ))}
            </span>
          </span>
        </label>
        <label>Design PUE
          <input inputMode="decimal" value={pue} onChange={(e) => setPue(e.target.value)}
                 placeholder={profile?.pue_typical ? `typical ${profile.pue_typical}` : 'typical'} />
        </label>
        <label className="full">Cooling
          <select value={cooling} onChange={(e) => setCooling(e.target.value)}>
            {profiles.map((p) => (
              <option key={p.cooling_profile_id} value={p.cooling_profile_id}>
                {p.label}{p.heat_temp_c != null ? ` (heat at ${p.heat_temp_c} C)` : ''}
              </option>
            ))}
          </select>
        </label>
        <div className="full plan-row">
          <span className="seg" role="group" aria-label="Design">
            <button type="button" className={greenfield === 1 ? 'on' : ''} onClick={() => setGreenfield(1)}>Designed in (greenfield)</button>
            <button type="button" className={greenfield === 0 ? 'on' : ''} onClick={() => setGreenfield(0)}>Retrofit</button>
          </span>
          <button type="submit" className="btn btn-primary" disabled={state.s === 'loading'}>
            {state.s === 'loading' ? 'Running…' : r ? 'Update ranking' : 'Rank options'}
          </button>
        </div>
        {profile?.description && <p className="muted small full">{profile.description}</p>}
      </form>

      {r && (
        <nav className="tabs">
          <button className={tab === 'results' ? 'on' : ''} onClick={() => setTab('results')}>Results</button>
          <button className={tab === 'inputs' ? 'on' : ''} onClick={() => setTab('inputs')}>Inputs <small>{r.inputs.length}</small></button>
          <span className="seg tabs-mode">
            {['corrected', 'excel'].map((m) => (
              <button key={m} className={(mode ?? r.mode) === m ? 'on' : ''} onClick={() => { setMode(m); run(m); }}>{m}</button>
            ))}
          </span>
        </nav>
      )}
      <div className="panel-body">
        {state.s === 'idle' && <p className="muted">Enter the size and cooling, then rank the options for this location. 1 GW = 1000 MW.</p>}
        {state.s === 'loading' && <p className="muted">Fetching weather and running the model…</p>}
        {state.s === 'error' && <p className="error">{state.e}</p>}
        {r && tab === 'results' && <Results r={r} />}
        {r && tab === 'inputs' && inputs && <Inputs d={inputs} />}
      </div>
    </aside>
  );
}
