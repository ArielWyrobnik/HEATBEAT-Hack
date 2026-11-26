import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { siteScope } from '../data';
import { num } from '../format';
import { PERSPECTIVES, type Perspective } from '../perspectives';
import type { LeaderboardRow } from '../types/api';
import { money } from './Results';

/** Short name of an option: the part before the first "+" plus the other parts without brackets. */
const shortName = (s?: string | null) => {
  if (!s) return 'nothing feasible';
  const parts = s.split(' + ');
  return parts.length > 1 ? `${parts[0]} + ${parts.slice(1).map((p) => p.replace(/\s*[(,].*$/, '')).join(' + ')}` : parts[0];
};

const coolingValue = (r: LeaderboardRow) => r.cooling_npv_usd ?? null;
/** Heat waste order: designs that pay off first (most heat), then the rest by reuse NPV. */
const heatKey = (r: LeaderboardRow) => (r.heat_pays_off ? 1e15 + (r.heat_reused_mwh_yr ?? 0) : (r.heat_reuse_npv_usd ?? -1e15));

/** Data centers ranked from two perspectives: cooling (money saved) and heat waste (heat reused). */
export default function Leaderboard({ selectedId, onPick, onClose }: {
  selectedId: string | null; onPick: (id: string) => void; onClose: () => void;
}) {
  const [rows, setRows] = useState<LeaderboardRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Perspective>('cooling');
  useEffect(() => { api.leaderboard(siteScope()).then(setRows).catch((e: Error) => setErr(e.message)); }, []);

  const sorted = useMemo(() => [...(rows ?? [])].sort((a, b) => tab === 'cooling'
    ? (coolingValue(b) ?? -Infinity) - (coolingValue(a) ?? -Infinity)
    : heatKey(b) - heatKey(a)), [rows, tab]);
  const max = Math.max(1, ...sorted.map((r) => Math.abs((tab === 'cooling' ? coolingValue(r) : r.heat_pays_off ? r.heat_reused_mwh_yr : 0) ?? 0)));

  return (
    <aside className="leaderboard" aria-label="Where we can do the most">
      <header>
        <div>
          <h3>Where we can do the most</h3>
          <p className="muted" title={PERSPECTIVES[tab].def}>{tab === 'cooling' ? 'Money saved through cooling' : 'Heat waste put to use'} ⓘ</p>
        </div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <div className="seg" role="group" aria-label="Perspective">
        {(Object.keys(PERSPECTIVES) as Perspective[]).map((k) => (
          <button key={k} className={tab === k ? 'on' : ''} aria-pressed={tab === k} onClick={() => setTab(k)}
                  title={PERSPECTIVES[k].def}>{PERSPECTIVES[k].label}</button>
        ))}
      </div>
      {err && <p className="error">Could not load the ranking. {err}</p>}
      {!rows && !err && <p className="muted">Running the model for every site…</p>}
      <ol>
        {sorted.map((r, i) => {
          let v: number | null; let show: string; let sub: string; let flat: boolean;
          if (tab === 'cooling') {
            v = coolingValue(r);
            flat = v == null || v <= 0;
            show = v == null ? 'n/a' : money(v);
            sub = flat ? 'cooling already well chosen' : shortName(r.cooling_option_name);
          } else {
            flat = !r.heat_pays_off;
            v = flat ? null : r.heat_reused_mwh_yr ?? null;
            show = v == null ? 'no' : `${num(v / 1000, v < 10000 ? 1 : 0)} GWh/yr`;
            sub = flat ? 'no heat reuse pays off here' : shortName(r.heat_option_name);
          }
          return (
            <li key={r.site_id} className={`${r.site_id === selectedId ? 'on' : ''}${flat ? ' flat' : ''}`}>
              <button onClick={() => onPick(r.site_id)}>
                <span className="lb-rank">{i + 1}</span>
                <span className="lb-name">
                  {r.name}
                  <small>{sub}</small>
                </span>
                <span className={`lb-val${(v ?? 0) < 0 ? ' neg' : ''}`}>
                  {show}
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
