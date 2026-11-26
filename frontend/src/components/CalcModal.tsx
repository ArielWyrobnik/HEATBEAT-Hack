import { useEffect, useState } from 'react';
import { compact, num, value } from '../format';
import type { CalcTerm, EnergyFlow, Flag, InputValue, ModelResult, OptionResult } from '../types/api';
import { FlagBadge } from './SitePanel';
import { ScoreBreakdown } from './ScoreBreakdown';

const fmt = (v: number | string | null | undefined, unit?: string | null) => {
  if (v == null) return 'n/a';
  if (typeof v === 'string') return v;
  const s = Math.abs(v) >= 1e4 ? compact(v, 2) : Math.abs(v) < 10 ? num(v, 3) : num(v, 1);
  return unit && unit !== '-' ? `${s} ${unit}` : s;
};

/** A source string that is a URL becomes a link. */
function Source({ s }: { s?: string | null }) {
  if (!s) return <span className="muted">no source given</span>;
  const m = s.match(/https?:\/\/\S+/);
  if (!m) return <>{s}</>;
  const [before, after] = s.split(m[0]);
  return <>{before}<a href={m[0]} target="_blank" rel="noreferrer">{m[0]}</a>{after}</>;
}

function Term({ t }: { t: CalcTerm }) {
  return (
    <tr>
      <td>{t.label ?? t.key}{t.label && t.label !== t.key && <small>{t.key}</small>}</td>
      <td className="n">{fmt(t.value, t.unit)}</td>
      <td>{t.flag ? <FlagBadge flag={t.flag} /> : <span className="flag flag-calc">Computed</span>}</td>
      <td className="src">{t.flag ? <Source s={t.source} /> : <span className="muted">model result</span>}</td>
    </tr>
  );
}

function Flows({ flows }: { flows: EnergyFlow[] }) {
  const rows = flows.filter((f) => f.mwh_yr > 0.5);
  if (!rows.length) return null;
  return (
    <table className="calc-terms">
      <thead><tr><th>From</th><th>To</th><th className="n">MWh/yr</th><th>Kind</th></tr></thead>
      <tbody>{rows.map((f, i) => (
        <tr key={i}><td>{f.source}</td><td>{f.target}</td><td className="n">{compact(f.mwh_yr)}</td><td>{f.kind}</td></tr>
      ))}</tbody>
    </table>
  );
}

/**
 * Popup with the whole calculation of one option: every step with formula, the numbers put in,
 * their status (real / estimated / synthetic / user / computed) and source, then all inputs.
 */
export default function CalcModal({ o, r, onClose }: { o: OptionResult; r: ModelResult; onClose: () => void }) {
  const [filter, setFilter] = useState<Flag | 'all'>('all');
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); onClose(); } };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);
  const steps = o.calculation ?? [];
  const inputs: InputValue[] = o.calculation_inputs?.length ? o.calculation_inputs : r.inputs;
  const counts = inputs.reduce((a, i) => ({ ...a, [i.flag]: (a[i.flag] ?? 0) + 1 }), {} as Record<string, number>);
  const shown = inputs.filter((i) => filter === 'all' || i.flag === filter);
  const total = inputs.length || 1;

  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={`Calculation of ${o.name}`}>
        <header>
          <div className="panel-title">
            <p className="eyebrow-sm">How the numbers are calculated</p>
            <h3>{o.rank ? `#${o.rank} ` : ''}{o.name}</h3>
            <p className="muted">Model {r.model} {r.model_version ?? ''}, mode {r.mode}. Hourly simulation over 8760 h of the site's weather year.</p>
          </div>
          <button className="close" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="modal-body">
          {inputs.length > 0 && (
            <div className="flag-share" title="Share of inputs by status">
              {(['real', 'estimated', 'synthetic', 'user'] as Flag[]).filter((f) => counts[f]).map((f) => (
                <span key={f} className={`fs fs-${f}`} style={{ flex: counts[f] }}>
                  {f} {num((100 * counts[f]) / total)} %
                </span>
              ))}
            </div>
          )}
          {o.implementation && <p className="impl-text"><b>How it is built:</b> {o.implementation}</p>}

          <h4>Score breakdown</h4>
          <ScoreBreakdown details={o.details} score={o.score} ecoScore={o.details?.eco_score} feasible={o.feasible} />

          {steps.length === 0 ? (
            <p className="muted">This model does not report a step by step calculation yet. The inputs it used are listed below.</p>
          ) : (
            <ol className="calc-steps">
              {steps.map((st, i) => (
                <li key={i}>
                  <div className="calc-head">
                    <span className="calc-n">{i + 1}</span>
                    <b>{st.title}</b>
                    <span className="calc-res">{fmt(st.result, st.unit)}</span>
                  </div>
                  <code className="formula">{st.formula}</code>
                  {st.terms.length > 0 && (
                    <table className="calc-terms"><tbody>{st.terms.map((t) => <Term key={t.key} t={t} />)}</tbody></table>
                  )}
                  {st.note && <p className="muted small">{st.note}</p>}
                </li>
              ))}
            </ol>
          )}

          {o.energy_balance.length > 0 && (<><h4>Energy flows (MWh/yr)</h4><Flows flows={o.energy_balance} /></>)}

          <h4>All inputs of this option ({inputs.length})</h4>
          <div className="flag-filter">
            <button className={filter === 'all' ? 'on' : ''} onClick={() => setFilter('all')}>All {inputs.length}</button>
            {(['real', 'estimated', 'synthetic', 'user'] as Flag[]).filter((f) => counts[f]).map((f) => (
              <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}><FlagBadge flag={f} /> {counts[f]}</button>
            ))}
          </div>
          <table className="calc-terms">
            <thead><tr><th>Input</th><th className="n">Value</th><th>Status</th><th>Source</th></tr></thead>
            <tbody>
              {shown.map((i) => (
                <tr key={i.key}>
                  <td>{i.label ?? i.key}{i.label && i.label !== i.key && <small>{i.key}</small>}</td>
                  <td className="n">{value(i.value)} {i.unit && <small>{i.unit}</small>}
                    {i.sens_low != null && i.sens_high != null && <small className="range">range {value(i.sens_low)} to {value(i.sens_high)}</small>}</td>
                  <td><FlagBadge flag={i.flag} /></td>
                  <td className="src"><Source s={i.source} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Real = measured or published site data. Estimated = literature value or team estimate. Synthetic = generated where no data exists.
            Computed = result of an earlier step. Ranges feed the tornado chart.
          </p>
        </div>
      </div>
    </div>
  );
}
