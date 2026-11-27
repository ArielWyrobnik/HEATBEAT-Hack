import { compact, num } from '../format';
import type { Cascade } from '../types/api';
import { money, tonnes } from './Results';

/** Colour per heat user, hottest (warm) to coolest. */
const COLOR: Record<string, string> = {
  biogas: '#e8743b', greenhouse: '#8fd400', fish: '#2bb3c0', ambient: '#6f8cff',
};
const deg = (t: number) => `${num(t, 0)}°`;
const gwh = (mwh: number) => (mwh >= 1e4 ? `${num(mwh / 1e3, 0)} GWh` : mwh >= 1e3 ? `${num(mwh / 1e3, 1)} GWh` : `${num(mwh, 0)} MWh`);

/** One cascade: a share bar, then the heat use loop from hot to cold, then the result in three numbers. */
export function CascadeCard({ c, rank }: { c: Cascade; rank: number }) {
  const rest = Math.max(0, 1 - c.heat_used_share);
  return (
    <figure className="cascade">
      <figcaption>
        <span className="cascade-rank">{rank}</span>
        <span className="cascade-title">{c.title}</span>
        <b className="cascade-share" title="Share of the server heat used">{num(c.heat_used_share * 100, c.heat_used_share < 0.1 ? 1 : 0)}%<small>heat used</small></b>
      </figcaption>

      <div className="cascade-bar" aria-hidden>
        {c.stages.map((s) => <i key={s.key} style={{ width: `${s.share * 100}%`, background: COLOR[s.key] ?? 'var(--green)' }} />)}
        <i className="rest" style={{ width: `${rest * 100}%` }} />
      </div>

      <ol className="cascade-flow">
        <li className="cascade-src">
          <span className="t">{deg(c.t_top_c)}</span>
          <span>Hot water from the servers</span>
        </li>
        {c.stages.map((s) => (
          <li key={s.key} style={{ ['--c' as string]: COLOR[s.key] ?? 'var(--green)' }}>
            <span className="t">{deg(s.t_in_c)}→{deg(s.t_out_c)}</span>
            <span className="name" title={s.size}><b>{s.label}</b>
              {s.heat_pump_cop ? <small className="hp-tag" title="The loop is too cold for this user, a heat pump lifts the heat">
                {' '}+ heat pump {deg(s.t_in_c)}→{deg(s.t_user_c ?? s.t_in_c)} (COP {num(s.heat_pump_cop, 1)})</small> : null}</span>
            <span className="e">{gwh(s.mwh_yr)}</span>
          </li>
        ))}
        <li className="cascade-end">
          <span className="t">{deg(c.t_back_c)}</span>
          <span>back to the servers · {num(rest * 100, 0)}% still cooled away</span>
        </li>
      </ol>

      <ul className="cascade-who">
        {c.stages.filter((s) => s.vendors?.length || s.references?.length).map((s) => {
          const v = s.vendors?.[0];
          const ref = s.references?.[0];
          return (
            <li key={s.key} style={{ ['--c' as string]: COLOR[s.key] ?? 'var(--green)' }}>
              <span className="who-name">{s.label}</span>
              {v && (v.url ? <a href={v.url} target="_blank" rel="noreferrer" title={v.one_line ?? ''}>{v.name} ↗</a> : <b>{v.name}</b>)}
              {v?.nvidia && <span className="v-nv">{v.nvidia}</span>}
              {ref && <span className="who-ref" title={ref.what ?? ''}>already at{' '}
                {ref.url ? <a href={ref.url} target="_blank" rel="noreferrer">{ref.project} ↗</a> : ref.project}</span>}
            </li>
          );
        })}
      </ul>

      <div className="cascade-kpis">
        <span><b>{compact(c.water_saved_m3_yr)} m3</b>water saved/yr</span>
        <span><b>{tonnes(c.co2_avoided_t_yr)}</b>CO2 avoided/yr</span>
        <span className={c.npv_usd < 0 ? 'neg' : ''}><b>{money(c.npv_usd)}</b>NPV 20 yr</span>
      </div>
    </figure>
  );
}

export default function Cascades({ items }: { items: Cascade[] }) {
  if (!items.length) return <p className="muted">No heat user can be reached from this site.</p>;
  return <div className="cascades">{items.slice(0, 2).map((c, i) => <CascadeCard key={c.title} c={c} rank={i + 1} />)}</div>;
}
