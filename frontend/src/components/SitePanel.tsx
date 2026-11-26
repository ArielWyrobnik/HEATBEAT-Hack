import { useEffect, useState } from 'react';
import { api } from '../api';
import { num } from '../format';
import type { CoolingProfile, ModelResult } from '../types/api';
import type { DataCenter } from '../types/datacenter';
import Results from './Results';

export type Load<T> = { state: 'loading' } | { state: 'error'; error: string } | { state: 'ok'; data: T };

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): Load<T> {
  const [s, setS] = useState<Load<T>>({ state: 'loading' });
  useEffect(() => {
    let alive = true;
    setS({ state: 'loading' });
    fn().then((data) => alive && setS({ state: 'ok', data }))
      .catch((e: Error) => alive && setS({ state: 'error', error: e.message }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return s;
}

const REJECTION_LABEL: Record<string, string> = {
  dry: 'Dry cooler (no water)', adiabatic: 'Adiabatic cooler (water in hot hours)', tower: 'Cooling tower (evaporates water all year)',
};

export type SetupOverrides = { cooling_profile?: string; baseline_rejection?: string };

/** One line on how the site cools today, with its source; the assumption can be changed in a fold. */
function TodaySetup({ r, ov, setOv }: { r: ModelResult; ov: SetupOverrides; setOv: (o: SetupOverrides) => void }) {
  const b = r.baseline;
  const [profiles, setProfiles] = useState<CoolingProfile[]>([]);
  useEffect(() => { api.coolingProfiles().then(setProfiles).catch(() => setProfiles([])); }, []);
  if (!b.heat_rejection) return null;
  const src = (b.current_setup ?? []).find((f) => f.field === 'heat_rejection' && f.source_url);
  const documented = b.setup_status === 'verified';
  return (
    <details className="setup">
      <summary>
        <span>Cooling today: <b>{REJECTION_LABEL[b.heat_rejection] ?? b.heat_rejection}</b></span>
        {documented ? <span className="flag flag-real">documented</span> : <span className="flag flag-estimated">assumed</span>}
      </summary>
      {src?.source_url && <p className="muted">Source: <a href={src.source_url} target="_blank" rel="noreferrer">{src.source_title ?? 'link'} ↗</a></p>}
      <div className="controls">
        <label>Cooling at the rack
          <select value={ov.cooling_profile ?? b.cooling_profile ?? ''} onChange={(e) => setOv({ ...ov, cooling_profile: e.target.value })}>
            {profiles.length === 0 && b.cooling_profile && <option value={b.cooling_profile}>{b.cooling_profile}</option>}
            {profiles.map((p) => <option key={p.cooling_profile_id} value={p.cooling_profile_id}>{p.label}</option>)}
          </select>
        </label>
        <label>Heat rejection today
          <select value={ov.baseline_rejection ?? b.heat_rejection} onChange={(e) => setOv({ ...ov, baseline_rejection: e.target.value })}>
            {Object.entries(REJECTION_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        {(ov.cooling_profile || ov.baseline_rejection) && <button className="link" onClick={() => setOv({})}>Reset</button>}
      </div>
    </details>
  );
}

export default function SitePanel({ site, onClose }: { site: DataCenter; onClose: () => void }) {
  const [ov, setOv] = useState<SetupOverrides>({});
  useEffect(() => setOv({}), [site.id]);
  const hasOv = Object.values(ov).some(Boolean);
  const ranking = useLoad(() => (hasOv
    ? api.evaluate({ site_id: site.id, overrides: ov })
    : api.ranking(site.id, {})), [site.id, ov.cooling_profile, ov.baseline_rejection]);

  const loc = [site.city, site.country].filter(Boolean).join(', ');
  const s = site as DataCenter & { it_load_mw?: number };

  return (
    <aside className="site-panel" aria-label={`Results for ${site.name}`}>
      <header>
        <div className="panel-title">
          <h3>{site.name}</h3>
          <p className="muted">{[loc, site.operator, s.it_load_mw != null && `${num(s.it_load_mw)} MW IT`].filter(Boolean).join(' · ')}</p>
        </div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <div className="panel-body">
        {ranking.state === 'loading' ? <p className="muted">Running the model…</p>
          : ranking.state === 'error' ? <p className="error">Could not run the model. {ranking.error}</p>
          : <><TodaySetup r={ranking.data} ov={ov} setOv={setOv} /><Results r={ranking.data} /></>}
      </div>
    </aside>
  );
}
