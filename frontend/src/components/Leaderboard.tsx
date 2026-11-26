import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { siteScope } from '../data';
import { compact } from '../format';
import type { LeaderboardRow } from '../types/api';
import { DEFS, money, tonnes } from './Results';

type Metric = 'npv' | 'cash' | 'water' | 'co2';
const METRICS: Record<Metric, { label: string; get: (r: LeaderboardRow) => number | null | undefined; show: (v: number) => string; def: string }> = {
  npv: { label: 'Value', get: (r) => r.npv_usd, show: (v) => money(v), def: DEFS.npv },
  cash: { label: '$/yr', get: (r) => r.cash_value_usd_yr, show: (v) => `${money(v)}/yr`, def: DEFS.cash },
  water: { label: 'Water', get: (r) => r.water_saved_m3_yr, show: (v) => `${compact(v)} m3`, def: DEFS.water },
  co2: { label: 'CO2', get: (r) => r.co2_avoided_t_yr, show: (v) => tonnes(v), def: DEFS.co2 },
};

/** Short name of an option: the part before the first "+" plus how many more parts follow. */
const shortName = (s?: string | null) => {
  if (!s) return 'nothing feasible';
  const parts = s.split(' + ');
  return parts.length > 1 ? `${parts[0]} + ${parts.slice(1).map((p) => p.replace(/\s*\(.*\)/, '')).join(' + ')}` : parts[0];
};

/** Data centers ranked by how much the best improvement over today's setup is worth. Click flies to the site. */
export default function Leaderboard({ selectedId, onPick, onClose }: {
  selectedId: string | null; onPick: (id: string) => void; onClose: () => void;
}) {
  const [rows, setRows] = useState<LeaderboardRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric>('npv');
  useEffect(() => { api.leaderboard(siteScope()).then(setRows).catch((e: Error) => setErr(e.message)); }, []);

  const m = METRICS[metric];
  const sorted = useMemo(() => [...(rows ?? [])].sort((a, b) => (m.get(b) ?? -Infinity) - (m.get(a) ?? -Infinity)), [rows, m]);
  const max = Math.max(1, ...sorted.map((r) => Math.abs(m.get(r) ?? 0)));

  return (
    <aside className="leaderboard" aria-label="Where we can do the most">
      <header>
        <div>
          <h3>Where we can do the most</h3>
          <p className="muted" title={m.def}>Best improvement per data center ⓘ</p>
        </div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <div className="seg" role="group" aria-label="Rank by">
        {(Object.keys(METRICS) as Metric[]).map((k) => (
          <button key={k} className={metric === k ? 'on' : ''} onClick={() => setMetric(k)} title={METRICS[k].def}>{METRICS[k].label}</button>
        ))}
      </div>
      {err && <p className="error">Could not load the ranking. {err}</p>}
      {!rows && !err && <p className="muted">Running the model for every site…</p>}
      <ol>
        {sorted.map((r, i) => {
          const v = m.get(r);
          const flat = r.verdict_level === 'no_gain';
          return (
            <li key={r.site_id} className={`${r.site_id === selectedId ? 'on' : ''}${flat ? ' flat' : ''}`}>
              <button onClick={() => onPick(r.site_id)}>
                <span className="lb-rank">{i + 1}</span>
                <span className="lb-name">
                  {r.name}
                  <small>{flat ? 'already well set up' : shortName(r.option_name)}</small>
                </span>
                <span className={`lb-val${(v ?? 0) < 0 ? ' neg' : ''}`}>
                  {v == null ? 'n/a' : m.show(v)}
                  <i style={{ width: `${(Math.abs(v ?? 0) / max) * 100}%` }} />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
