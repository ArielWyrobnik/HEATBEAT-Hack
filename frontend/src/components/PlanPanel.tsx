import { useEffect, useState } from 'react';
import { api } from '../api';
import { num } from '../format';
import type { CoolingProfile, ModelResult } from '../types/api';
import Results, { Vendors } from './Results';

export interface PlanPoint { lat: number; lng: number }

/**
 * Plan a future data center: the user clicked a point on the map, enters the IT size and the cooling,
 * and gets the best options in the same compact view as for an existing site (POST /api/plan).
 */
export default function PlanPanel({ point, onClose }: { point: PlanPoint; onClose: () => void }) {
  const [profiles, setProfiles] = useState<CoolingProfile[]>([]);
  const [size, setSize] = useState('100');
  const [unit, setUnit] = useState<'MW' | 'GW'>('MW');
  const [cooling, setCooling] = useState('dlc_warm');
  const [pue, setPue] = useState('');
  const [greenfield, setGreenfield] = useState(1);
  const [state, setState] = useState<{ s: 'idle' | 'loading' } | { s: 'error'; e: string } | { s: 'ok'; r: ModelResult }>({ s: 'idle' });
  useEffect(() => { api.coolingProfiles().then(setProfiles).catch(() => setProfiles([])); }, []);

  const itMw = (parseFloat(size.replace(',', '.')) || 0) * (unit === 'GW' ? 1000 : 1);
  const profile = profiles.find((p) => p.cooling_profile_id === cooling);

  const run = () => {
    if (itMw <= 0) { setState({ s: 'error', e: 'Enter an IT load above 0.' }); return; }
    setState({ s: 'loading' });
    api.plan({
      lat: point.lat, lon: point.lng, it_mw: itMw, cooling_profile: cooling, name: null,
      pue: pue ? parseFloat(pue.replace(',', '.')) : null, is_greenfield: greenfield, mode: null, model: null,
    }).then((r) => setState({ s: 'ok', r })).catch((e: Error) => setState({ s: 'error', e: e.message }));
  };

  // new point: rerun automatically if there was a result
  useEffect(() => { if (state.s === 'ok') run(); }, [point.lat, point.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  const r = state.s === 'ok' ? state.r : null;

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

      <form className="plan-form" onSubmit={(e) => { e.preventDefault(); run(); }}>
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
        <label>Cooling
          <select value={cooling} onChange={(e) => setCooling(e.target.value)} title={profile?.description ?? ''}>
            {profiles.map((p) => <option key={p.cooling_profile_id} value={p.cooling_profile_id}>{p.label}</option>)}
          </select>
        </label>
        <details className="full more">
          <summary>More settings</summary>
          <div className="more-grid">
            <label>Design PUE
              <input inputMode="decimal" value={pue} onChange={(e) => setPue(e.target.value)}
                     placeholder={profile?.pue_typical ? `typical ${profile.pue_typical}` : 'typical'} />
            </label>
            <span className="seg" role="group" aria-label="Design">
              <button type="button" className={greenfield === 1 ? 'on' : ''} onClick={() => setGreenfield(1)}>New build</button>
              <button type="button" className={greenfield === 0 ? 'on' : ''} onClick={() => setGreenfield(0)}>Retrofit</button>
            </span>
          </div>
        </details>
        <button type="submit" className="btn btn-primary full" disabled={state.s === 'loading'}>
          {state.s === 'loading' ? 'Running…' : r ? 'Update' : 'Find the best options'}
        </button>
      </form>

      <div className="panel-body">
        {state.s === 'loading' && <p className="muted">Fetching weather and running the model…</p>}
        {state.s === 'error' && <p className="error">{state.e}</p>}
        {r && <Results r={r} />}
        {r && <Vendors vendors={r.cooling_vendors} title={`Who supplies the ${profile?.label ?? 'cooling'}`} />}
      </div>
    </aside>
  );
}
