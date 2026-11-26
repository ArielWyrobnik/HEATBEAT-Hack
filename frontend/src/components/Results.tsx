import { useEffect, useState } from 'react';
import { compact, num, usd, value } from '../format';
import type { CalcStep, Flag, InputValue, ModelResult, OptionResult } from '../types/api';
import Tornado from './Tornado';

/**
 * Compact results: a one line verdict, the best 2 to 3 options that change something, and per option
 * (click to open) the four key numbers with their definition, how it is built, the investment, the
 * step by step calculation with inputs and sources, and the sensitivity chart.
 */

const FLAG_LABEL: Record<Flag, string> = { real: 'real data', estimated: 'estimate', synthetic: 'synthetic', user: 'set by you' };

export function FlagBadge({ flag }: { flag: Flag }) {
  return <span className={`flag flag-${flag}`}>{FLAG_LABEL[flag]}</span>;
}

/** The four numbers shown per option, each with a plain definition. */
export const DEFS = {
  cash: 'Money saved per year: lower power and water bills plus heat or water sold, minus running costs.',
  payback: 'Years until the yearly gain (money plus water scarcity value) has paid back the investment.',
  co2: 'Tonnes of CO2 per year less than today (negative = more, e.g. dry coolers use more power).',
  water: 'Cubic metres of fresh water per year less than today.',
  npv: 'Value over 20 years: all yearly gains (incl. a water scarcity value) discounted at 7 %, minus the investment.',
};

const signed = (v: number | null | undefined, f: (x: number) => string) =>
  v == null ? 'n/a' : `${v < 0 ? '-' : ''}${f(Math.abs(v))}`;
export const money = (v?: number | null) => signed(v, (x) => usd(x));
const payback = (v?: number | null) => (v == null ? 'never' : v === 0 ? 'no extra cost' : `${num(v, 1)} yr`);
/** Tonnes: 950 t, 21 kt, 1.2 Mt */
export const tonnes = (v?: number | null) => {
  if (v == null) return 'n/a';
  const a = Math.abs(v);
  return a >= 1e6 ? `${num(v / 1e6, 1)} Mt` : a >= 1e4 ? `${num(v / 1e3, 0)} kt` : `${num(v, 0)} t`;
};

const VERDICT_TITLE: Record<string, string> = {
  no_gain: 'Already well set up',
  small_gain: 'Small gain possible',
  gain: 'Clear gain possible',
};

/** First sentence of the model's verdict (the rest is in the details). */
const firstSentence = (s: string) => s.split(/(?<=\.)\s/)[0];

function Verdict({ r }: { r: ModelResult }) {
  if (!r.verdict) return null;
  const level = r.verdict_level ?? 'gain';
  return (
    <div className={`verdict verdict-${level}`} title={r.verdict}>
      <strong>{VERDICT_TITLE[level] ?? 'Result'}</strong>
      <span>{firstSentence(r.verdict)}</span>
    </div>
  );
}

function Kpi({ label, v, def, neg }: { label: string; v: string; def: string; neg?: boolean }) {
  return (
    <div className="kpi">
      <span>{label}</span>
      <b className={neg ? 'neg' : ''}>{v}</b>
      <small>{def}</small>
    </div>
  );
}

/** A source string with a URL becomes a link. */
function Source({ s }: { s?: string | null }) {
  if (!s) return null;
  const m = s.match(/https?:\/\/\S+/);
  if (!m) return <span className="src">{s}</span>;
  const label = s.replace(m[0], '').replace(/[\s,;:(]+$/, '').trim() || new URL(m[0]).hostname;
  return <a className="src" href={m[0]} target="_blank" rel="noreferrer">{label} ↗</a>;
}

const fmt = (v: number | string | null | undefined, unit?: string | null) => {
  if (v == null) return 'n/a';
  if (typeof v === 'string') return v;
  const s = Math.abs(v) >= 1e4 ? compact(v, 2) : Math.abs(v) < 10 ? num(v, 3) : num(v, 1);
  return unit && unit !== '-' ? `${s} ${unit}` : s;
};

/** Each step on two lines: name and result, then the formula; inputs as small chips with status and source. */
function Steps({ steps }: { steps: CalcStep[] }) {
  return (
    <ol className="calc-list">
      {steps.map((st, i) => (
        <li key={i}>
          <div className="st-head"><b>{st.title}</b><em>{fmt(st.result, st.unit)}</em></div>
          <code>{st.formula}</code>
          {st.terms.length > 0 && (
            <div className="st-in">
              {st.terms.map((t) => (
                <span key={t.key} className={`term term-${t.flag ?? 'calc'}`}
                      title={t.flag ? `${FLAG_LABEL[t.flag]}${t.source ? `: ${t.source}` : ''}` : 'result of an earlier step'}>
                  {t.label ?? t.key} <b>{fmt(t.value, t.unit)}</b>
                </span>
              ))}
            </div>
          )}
          {st.note && <p className="st-note">{st.note}</p>}
        </li>
      ))}
    </ol>
  );
}

function InputsList({ inputs }: { inputs: InputValue[] }) {
  const order: Flag[] = ['real', 'user', 'estimated', 'synthetic'];
  const sorted = [...inputs].sort((a, b) => order.indexOf(a.flag) - order.indexOf(b.flag));
  return (
    <table className="inputs">
      <tbody>
        {sorted.map((i) => (
          <tr key={i.key}>
            <td>{i.label ?? i.key}<Source s={i.source} /></td>
            <td className="v">{value(i.value)} {i.unit && i.unit !== '-' && <small>{i.unit}</small>}</td>
            <td><FlagBadge flag={i.flag} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Details({ o, r }: { o: OptionResult; r: ModelResult }) {
  const k = o.kpis;
  const costs = Object.entries(o.capex_breakdown ?? {});
  const inputs = o.calculation_inputs?.length ? o.calculation_inputs : r.inputs;
  const nReal = inputs.filter((i) => i.flag === 'real' || i.flag === 'user').length;
  return (
    <div className="opt-body">
      <div className="kpis">
        <Kpi label="Saved per year" v={`${money(k.cash_value_usd_yr ?? k.net_value_usd_yr)}`} def={DEFS.cash}
             neg={(k.cash_value_usd_yr ?? 0) < 0} />
        <Kpi label="Payback" v={payback(k.payback_yr)} def={DEFS.payback} />
        <Kpi label="CO2 avoided" v={`${tonnes(k.co2_avoided_t_yr)}/yr`} def={DEFS.co2} neg={(k.co2_avoided_t_yr ?? 0) < 0} />
        <Kpi label="Water saved" v={`${compact(k.water_saved_m3_yr)} m3/yr`} def={DEFS.water} neg={(k.water_saved_m3_yr ?? 0) < 0} />
      </div>

      {o.already_in_place?.map((t) => <p key={t} className="already-line"><span className="already">already in place</span> {t}</p>)}
      {o.implementation && <p className="impl-line"><b>How it is built.</b> {o.implementation}</p>}
      {costs.length > 0 && (
        <p className="impl-line"><b>Investment {money(k.capex_usd)}.</b>{' '}
          {costs.map(([c, v]) => `${c.replace(/_/g, ' ')} ${money(v)}`).join(', ')}
          <span className="muted"> (cost figures are team assumptions, not quotes)</span></p>
      )}

      {o.calculation?.length ? (
        <>
          <h5>Calculation <small>hourly over a full weather year</small></h5>
          <Steps steps={o.calculation} />
          <p className="legend">
            <span className="term term-real">real data</span>
            <span className="term term-estimated">estimate</span>
            <span className="term term-synthetic">synthetic</span>
            <span className="term term-calc">earlier step</span>
            <span className="muted">hover an input for its source</span>
          </p>
        </>
      ) : null}

      {r.tornado && r.tornado.option_id === o.option_id && (
        <>
          <h5>What moves the result</h5>
          <Tornado data={r.tornado} optionName={o.name} />
        </>
      )}

      {inputs.length > 0 && (
        <details className="all-inputs">
          <summary>All {inputs.length} inputs with sources ({nReal} real site data)</summary>
          <InputsList inputs={inputs} />
        </details>
      )}
    </div>
  );
}

/** Best options that change something (today's setup is left out, the verdict covers it). */
export function topOptions(r: ModelResult, n = 3) {
  return r.options.filter((o) => o.feasible && !o.is_today && !/today's setup/.test(o.name)).slice(0, n);
}

export default function Results({ r }: { r: ModelResult }) {
  const top = topOptions(r);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => setOpen(r.verdict_level === 'no_gain' ? null : top[0]?.option_id ?? null), [r]); // eslint-disable-line react-hooks/exhaustive-deps
  const b = r.baseline;
  return (
    <div className="results">
      <Verdict r={r} />
      <p className="today-line">
        <b>Today</b> PUE {num(b.pue, 2)} · water {compact(b.water_use_m3_yr)} m3/yr · {tonnes(b.co2_t_yr)} CO2/yr · power {money(b.electricity_cost_usd_yr)}/yr
      </p>

      <h4>Best options <small title={DEFS.npv}>ranked by value over 20 years (NPV) ⓘ</small></h4>
      {top.length === 0 && <p className="muted">No option passes the technical checks at this site.</p>}
      <ol className="options">
        {top.map((o, i) => {
          const on = open === o.option_id;
          const k = o.kpis;
          const npv = o.score;
          return (
            <li key={o.option_id} className={on ? 'open' : ''}>
              <button className="opt-head" onClick={() => setOpen(on ? null : o.option_id)} aria-expanded={on}>
                <span className="opt-rank">{i + 1}</span>
                <span className="opt-name">
                  {o.name}
                  <small>
                    {(npv ?? 0) < 0 ? 'loses money here'
                      : (k.cash_value_usd_yr ?? 0) < 0 ? `costs ${money(-(k.cash_value_usd_yr ?? 0))}/yr more, pays off through water saved`
                      : `saves ${money(k.cash_value_usd_yr ?? k.net_value_usd_yr)}/yr · ${k.payback_yr === 0 ? 'no extra investment' : `payback ${payback(k.payback_yr)}`}`}
                  </small>
                </span>
                <span className={`opt-npv${(npv ?? 0) < 0 ? ' neg' : ''}`}>
                  {npv == null ? 'n/a' : `${npv < 0 ? '-' : '+'}$${num(Math.abs(npv), 1)} M`}
                  <small>NPV</small>
                </span>
                <span className="chev" aria-hidden>{on ? '−' : '+'}</span>
              </button>
              {on && <Details o={o} r={r} />}
            </li>
          );
        })}
      </ol>

      {r.warnings.length > 0 && (
        <details className="notes">
          <summary>{r.warnings.length} note{r.warnings.length > 1 ? 's' : ''} on the data</summary>
          <ul>{r.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
