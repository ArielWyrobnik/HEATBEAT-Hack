import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { compact, num, usd, value } from '../format';
import type { Flag, ModelInfo, ModelResult, OptionResult, SiteInputs } from '../types/api';
import type { DataCenter } from '../types/datacenter';
import Tornado from './Tornado';

const FLAG_LABEL: Record<Flag, string> = { real: 'Real', estimated: 'Estimated', synthetic: 'Synthetic', user: 'User' };

export function FlagBadge({ flag }: { flag: Flag }) {
  return <span className={`flag flag-${flag}`}>{FLAG_LABEL[flag]}</span>;
}

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

function Kpi({ label, v, sub }: { label: string; v: string; sub?: string }) {
  return (
    <div className="kpi">
      <span>{label}</span>
      <b>{v}</b>
      {sub && <small>{sub}</small>}
    </div>
  );
}

function before(a?: number | null, b?: number | null, d = 2) {
  if (a == null || b == null) return 'n/a';
  return `${num(a, d)} → ${num(b, d)}`;
}

const COST_LABEL: Record<string, string> = { plant: 'Plant', heat_pump: 'Heat pump', pipeline: 'Pipeline' };

function OptionKpis({ o, placeholderCosts }: { o: OptionResult; placeholderCosts: boolean }) {
  const k = o.kpis;
  const costs = Object.entries(o.capex_breakdown ?? {});
  return (
    <>
    {(o.implementation || costs.length > 0) && (
      <div className="impl">
        {o.implementation && <p><b>How it is built:</b> {o.implementation}</p>}
        {costs.length > 0 && (
          <p className="costs"><b>Investment:</b> {costs.map(([c, v]) => `${COST_LABEL[c] ?? c.replace(/_/g, ' ')} ${usd(v)}`).join(' + ')}
            {' '}= {usd(k.capex_usd)}{placeholderCosts && <small> (placeholder costs)</small>}</p>
        )}
      </div>
    )}
    <div className="kpis">
      <Kpi label="Heat delivered" v={`${compact(k.heat_delivered_mwh_yr ?? k.heat_recovered_mwh_yr)} MWh/yr`} />
      <Kpi label="CO2 avoided" v={`${compact(k.co2_avoided_t_yr)} t/yr`} />
      <Kpi label="Water saved" v={`${compact(k.water_saved_m3_yr)} m3/yr`} />
      <Kpi label="Net value" v={`${usd(k.net_value_usd_yr)}/yr`} />
      <Kpi label="CAPEX" v={usd(k.capex_usd)} sub={placeholderCosts ? 'placeholder' : undefined} />
      <Kpi label="Payback" v={k.payback_yr == null ? 'never' : `${num(k.payback_yr, 1)} yr`} />
      <Kpi label="PUE" v={before(k.pue_baseline, k.pue_with, 3)} />
      <Kpi label="WUE L/kWh" v={before(k.wue_baseline_l_kwh, k.wue_with_l_kwh)} />
      <Kpi label="ERE" v={num(k.ere, 2)} />
      <Kpi label="COP" v={k.cop == null ? 'no heat pump' : num(k.cop, 1)} />
    </div>
    </>
  );
}

export function Results({ r }: { r: ModelResult }) {
  const feasible = r.options.filter((o) => o.feasible);
  const ko = r.options.filter((o) => !o.feasible);
  const [open, setOpen] = useState<string | null>(feasible[0]?.option_id ?? null);
  useEffect(() => setOpen(feasible[0]?.option_id ?? null), [r]); // eslint-disable-line react-hooks/exhaustive-deps
  const b = r.baseline;
  // score scale differs per model (0 to 5, or NPV in million USD that can be negative)
  const maxScore = Math.max(1e-9, ...feasible.map((o) => Math.abs(o.score ?? 0)));
  const placeholderCosts = r.model === 'excel_ranking';
  const best = feasible[0];
  return (
    <>
      {r.warnings.length > 0 && (
        <ul className="warnings">{r.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      )}

      <h4>Baseline (without a solution)</h4>
      <div className="kpis kpis-baseline">
        <Kpi label="IT energy" v={`${compact(b.it_energy_mwh_yr)} MWh/yr`} />
        <Kpi label="Heat rejected" v={`${compact(b.heat_rejected_mwh_yr)} MWh/yr`} />
        <Kpi label="PUE" v={num(b.pue, 2)} />
        <Kpi label="Water" v={`${compact(b.water_use_m3_yr)} m3/yr`} />
        <Kpi label="CO2" v={`${compact(b.co2_t_yr)} t/yr`} />
        <Kpi label="Power bill" v={`${usd(b.electricity_cost_usd_yr)}/yr`} />
      </div>

      <h4>Ranking ({feasible.length} feasible of {r.options.length}) <small className="scale">score: {r.score_scale}</small></h4>
      {feasible.length === 0 && <p className="muted">No option passes the knock-out gates at this site.</p>}
      <ol className="options">
        {feasible.map((o) => (
          <li key={o.option_id} className={open === o.option_id ? 'open' : ''}>
            <button className="opt-head" onClick={() => setOpen(open === o.option_id ? null : o.option_id)}>
              <span className="opt-rank">{o.rank ?? '-'}</span>
              <span className="opt-name">
                {o.name}
                {o.product && <small>{o.product}</small>}
              </span>
              <span className="opt-score">
                <span className="bar"><i className={(o.score ?? 0) < 0 ? 'neg' : ''} style={{ width: `${(Math.abs(o.score ?? 0) / maxScore) * 100}%` }} /></span>
                {num(o.score, 2)}
              </span>
              {o.eco_grade && <span className={`grade grade-${o.eco_grade[0]}`}>{o.eco_grade}</span>}
            </button>
            {open === o.option_id && <OptionKpis o={o} placeholderCosts={placeholderCosts} />}
          </li>
        ))}
      </ol>
      {ko.length > 0 && (
        <details className="ko">
          <summary>{ko.length} options knocked out</summary>
          <ul>{ko.map((o) => <li key={o.option_id}><b>{o.name}</b> {o.ko_reasons[0] ?? ''}</li>)}</ul>
        </details>
      )}

      {r.tornado && best && <Tornado data={r.tornado} optionName={r.options.find((o) => o.option_id === r.tornado!.option_id)?.name ?? best.name} />}
      <p className="muted small">Model {r.model}, mode {r.mode}. Score: {r.score_scale}.</p>
    </>
  );
}

export function Inputs({ d }: { d: SiteInputs }) {
  const [filter, setFilter] = useState<Flag | 'all'>('all');
  const rows = d.inputs.filter((i) => filter === 'all' || i.flag === filter);
  const w = d.weather as Record<string, number | string | null>;
  return (
    <>
      <div className="flag-filter">
        <button className={filter === 'all' ? 'on' : ''} onClick={() => setFilter('all')}>All {d.inputs.length}</button>
        {(Object.keys(FLAG_LABEL) as Flag[]).filter((f) => d.flag_counts[f]).map((f) => (
          <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>
            <FlagBadge flag={f} /> {d.flag_counts[f]}
          </button>
        ))}
      </div>
      <table className="inputs">
        <tbody>
          {rows.map((i) => (
            <tr key={i.key} title={[i.source && `Source: ${i.source}`, i.description].filter(Boolean).join('\n')}>
              <td>{i.label ?? i.key}<small>{i.key}</small></td>
              <td className="v">{value(i.value)} {i.unit && <small>{i.unit}</small>}</td>
              <td><FlagBadge flag={i.flag} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {Object.keys(w).length > 0 && <h4>Weather and prices (2024)</h4>}
      {Object.keys(w).length === 0 ? null : 'error' in w ? <p className="muted">{String(w.error)}</p> : (
        <div className="kpis">
          <Kpi label="Mean temperature" v={`${num(w.t_db_mean_c as number, 1)} C`} sub={`${num(w.t_db_min_c as number, 1)} to ${num(w.t_db_max_c as number, 1)} C`} />
          <Kpi label="Heating degree hours" v={compact(w.heating_degree_hours_18c as number)} sub="base 18 C" />
          <Kpi label="Wet bulb p99" v={`${num(w.t_wb_p99_c as number, 1)} C`} />
          <Kpi label="Mean power price" v={`$${num(w.price_mean_usd_mwh as number, 1)}/MWh`}
               sub={(w.price_is_synthetic_share as number) > 0 ? `${num(100 * (w.price_is_synthetic_share as number))} % synthetic` : 'real hourly'} />
        </div>
      )}
      <p className="muted small">Hover a row for its source.</p>
    </>
  );
}

export default function SitePanel({ site, onClose }: { site: DataCenter; onClose: () => void }) {
  const [tab, setTab] = useState<'results' | 'inputs'>('results');
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string | undefined>();
  const [mode, setMode] = useState<string | undefined>();
  const [greenfield, setGreenfield] = useState<number | undefined>();

  useEffect(() => { api.models().then(setModels).catch(() => setModels([])); }, []);
  const info = useMemo(() => models.find((m) => m.name === model) ?? models.find((m) => m.default) ?? models[0], [models, model]);

  const params = { model: info?.name, mode, is_greenfield: greenfield };
  const ranking = useLoad(() => api.ranking(site.id, params), [site.id, info?.name, mode, greenfield]);
  const inputs = useLoad(() => api.inputs(site.id, { model: info?.name, is_greenfield: greenfield }), [site.id, info?.name, greenfield]);

  const loc = [site.city, site.country].filter(Boolean).join(', ');
  const s = site as DataCenter & { it_load_mw?: number; cooling_type?: string; grid_region?: string };

  return (
    <aside className="site-panel" aria-label={`Results for ${site.name}`}>
      <header>
        <div>
          <h3>{site.name}</h3>
          <p className="muted">{loc}{site.operator ? ` · ${site.operator}` : ''}</p>
        </div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <div className="chips">
        {s.it_load_mw != null && <span>IT {num(s.it_load_mw)} MW</span>}
        {s.cooling_type && <span>{s.cooling_type.replace(/_/g, ' ')}</span>}
        {site.pue != null && <span>PUE {site.pue}</span>}
        {s.grid_region && <span>{s.grid_region}</span>}
      </div>

      <div className="controls">
        {models.length > 1 && (
          <label>Model
            <select value={info?.name} onChange={(e) => { setModel(e.target.value); setMode(undefined); }}>
              {models.map((m) => <option key={m.name} value={m.name}>{m.label}</option>)}
            </select>
          </label>
        )}
        {info && info.modes.length > 1 && (
          <div className="seg" role="group" aria-label="Mode">
            {info.modes.map((m) => (
              <button key={m} className={(mode ?? info.default_mode) === m ? 'on' : ''} onClick={() => setMode(m)}>{m}</button>
            ))}
          </div>
        )}
        <div className="seg" role="group" aria-label="Site type">
          <button className={greenfield !== 1 ? 'on' : ''} onClick={() => setGreenfield(undefined)}>Existing</button>
          <button className={greenfield === 1 ? 'on' : ''} onClick={() => setGreenfield(1)}>Greenfield</button>
        </div>
      </div>

      <nav className="tabs">
        <button className={tab === 'results' ? 'on' : ''} onClick={() => setTab('results')}>Results</button>
        <button className={tab === 'inputs' ? 'on' : ''} onClick={() => setTab('inputs')}>
          Inputs {inputs.state === 'ok' && <small>{inputs.data.inputs.length}</small>}
        </button>
      </nav>

      <div className="panel-body">
        {tab === 'results' && (ranking.state === 'loading' ? <p className="muted">Running the model…</p>
          : ranking.state === 'error' ? <p className="error">Could not run the model. {ranking.error}</p>
          : <Results r={ranking.data} />)}
        {tab === 'inputs' && (inputs.state === 'loading' ? <p className="muted">Loading inputs…</p>
          : inputs.state === 'error' ? <p className="error">{inputs.error}</p>
          : <Inputs d={inputs.data} />)}
      </div>
    </aside>
  );
}
