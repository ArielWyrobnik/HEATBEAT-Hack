import { useEffect, useState } from 'react';
import { compact, num } from '../format';
import type { Cascade } from '../types/api';
import { money, tonnes } from './Results';

/** Colour per heat user, hottest (warm) to coolest. */
const COLOR: Record<string, string> = {
  biogas: '#e8743b', greenhouse: '#8fd400', fish: '#2bb3c0', ambient: '#6f8cff',
};
const deg = (t: number) => `${num(t, 0)}°`;
const gwh = (mwh: number) => (mwh >= 1e4 ? `${num(mwh / 1e3, 0)} GWh` : mwh >= 1e3 ? `${num(mwh / 1e3, 1)} GWh` : `${num(mwh, 0)} MWh`);

const mwh = (v?: number) => `${compact(v ?? 0)} MWh/yr`;

/** Calculation behind one cascade: energy balance, value and one row per heat user. */
function CascadeDetails({ c }: { c: Cascade }) {
  const total = c.heat_used_mwh_yr + c.heat_rejected_mwh_yr;
  const tiles: [string, string, string][] = [
    ['Server heat', mwh(total), 'All heat the IT load produces per year.'],
    ['Heat used', mwh(c.heat_used_mwh_yr), 'Server heat taken by the users instead of being cooled away (line losses deducted).'],
    ['Straight from the GPU loop', mwh(c.direct_mwh_yr), 'Delivered through a plain heat exchanger, no heat pump.'],
    ['Via heat pump', mwh(c.heat_pump_mwh_yr), 'Delivered by a heat pump because the user needs hotter water than the loop.'],
    ['Heat pump electricity', mwh(c.heat_pump_elec_mwh_yr), 'Electricity of the heat pumps (heat delivered / COP).'],
    ['Pipe losses', mwh(c.line_loss_mwh_yr), 'Heat lost in the pipes to the users.'],
    ['Cooling electricity saved', mwh(c.electricity_saved_mwh_yr), 'Fans, pumps and chillers that no longer run for the heat used, minus heat pump electricity.'],
    ['Water saved', `${compact(c.water_saved_m3_yr)} m3/yr`, 'Water the cooling no longer evaporates.'],
    ['Investment', money(c.capex_usd), 'Heat exchangers, heat pumps, pipes and network. Team cost assumptions, not quotes.'],
    ['Net value per year', `${money(c.net_value_usd_yr ?? 0)}/yr`, 'Heat sales plus electricity and water saved minus maintenance.'],
    ['NPV 20 yr', money(c.npv_usd), 'Net value over 20 years, discounted, minus the investment.'],
  ];
  if (c.co2_avoided_t_yr >= 0) tiles.splice(8, 0, ['CO2 avoided', `${tonnes(c.co2_avoided_t_yr)}/yr`, 'Gas heat replaced plus electricity saved, at the grid carbon intensity.']);
  return (
    <div className="cascade-details">
      <div className="calc-tiles">
        {tiles.map(([l, v, d], i) => <div key={l} className="calc-tile" title={d}><span>{i + 1}. {l}</span><b>{v}</b></div>)}
      </div>
      <table className="cascade-table">
        <thead><tr><th>User</th><th>Size</th><th>Water</th><th>Heat</th><th>Peak</th><th>Value</th><th>Investment</th></tr></thead>
        <tbody>
          {c.stages.map((s) => (
            <tr key={s.key}>
              <td><i style={{ background: COLOR[s.key] ?? 'var(--green)' }} />{s.label}{s.heat_pump_cop ? <small> heat pump COP {num(s.heat_pump_cop, 1)}</small> : null}</td>
              <td>{s.size}</td>
              <td>{deg(s.t_in_c)}→{deg(s.t_out_c)}</td>
              <td>{gwh(s.mwh_yr)}</td>
              <td>{num(s.peak_mw, 1)} MW</td>
              <td>{money(s.value_usd_yr)}/yr</td>
              <td>{money(s.capex_usd ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One cascade: a share bar, then the heat use loop from hot to cold, then the result in three numbers.
 * Click the title to fold out the calculation; the corner button shows it full screen (Esc closes). */
export function CascadeCard({ c, rank }: { c: Cascade; rank: number }) {
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState(false);
  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setFull(false); };
    window.addEventListener('keydown', onKey);
    document.body.classList.add('opt-full-open');
    return () => { window.removeEventListener('keydown', onKey); document.body.classList.remove('opt-full-open'); };
  }, [full]);
  const card = <CascadeBody c={c} rank={rank} open={open || full} onToggle={() => setOpen(!open)}
                            full={full} onFull={() => setFull(!full)} />;
  if (!full) return card;
  return <div className="opt-full" role="dialog" aria-modal="true" aria-label={c.title}><div className="opt-full-inner">{card}</div></div>;
}

function CascadeBody({ c, rank, open, onToggle, full, onFull }:
  { c: Cascade; rank: number; open: boolean; onToggle: () => void; full: boolean; onFull: () => void }) {
  const rest = Math.max(0, 1 - c.heat_used_share);
  return (
    <figure className="cascade">
      <figcaption>
        <button type="button" className="cascade-head" onClick={onToggle} aria-expanded={open}>
          <span className="cascade-rank">{rank}</span>
          <span className="cascade-title">{c.title}</span>
          <b className="cascade-share" title="Share of the server heat used">{num(c.heat_used_share * 100, c.heat_used_share < 0.1 ? 1 : 0)}%<small>heat used</small></b>
          <span className="chev" aria-hidden>{open ? '−' : '+'}</span>
        </button>
        <button type="button" className="expand-btn" onClick={onFull} title={full ? 'Close (Esc)' : 'Full screen'}
                aria-label={full ? 'Close full screen' : 'Full screen'}>
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
            {full
              ? <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" fill="none" stroke="currentColor" strokeWidth="2" />
              : <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" fill="none" stroke="currentColor" strokeWidth="2" />}
          </svg>
        </button>
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
                {' '}+ heat pump to {deg(s.t_user_c ?? s.t_in_c)} (COP {num(s.heat_pump_cop, 1)})</small> : null}</span>
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
        {c.co2_avoided_t_yr >= 0 && <span><b>{tonnes(c.co2_avoided_t_yr)}</b>CO2 avoided/yr</span>}
        <span className={c.npv_usd < 0 ? 'neg' : ''}><b>{money(c.npv_usd)}</b>NPV 20 yr</span>
      </div>
      {open && <CascadeDetails c={c} />}
    </figure>
  );
}

export default function Cascades({ items }: { items: Cascade[] }) {
  if (!items.length) return <p className="muted">No heat reuse here. It needs hot water straight from liquid cooled GPUs (35° or more) and a heat user nearby.</p>;
  return <div className="cascades">{items.slice(0, 2).map((c, i) => <CascadeCard key={c.title} c={c} rank={i + 1} />)}</div>;
}
