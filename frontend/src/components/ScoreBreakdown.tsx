import { ENGINE } from '../dsx/types';
import Pie from './Pie';

/**
 * Score charts: how each sub-score and its weight builds the viability score and the eco score.
 * Weights come from the engine itself, so the charts always match the calculation.
 */
const W = (ENGINE as unknown as { C: { weights: Record<string, number>; eco_weights: Record<string, number> } }).C;

export const VIABILITY_PARTS = [
  { key: 'p_thermo', w: W.weights.thermo, label: 'Thermodynamics', hint: 'share of delivered heat that is free, not heat-pump power', color: '#38bdf8' },
  { key: 'p_climate', w: W.weights.climate, label: 'Climate fit', hint: 'hours a year the heat user needs heat (or cooling)', color: '#a78bfa' },
  { key: 'p_econ', w: W.weights.econ, label: 'Economics', hint: 'payback: 3 years or less = 5, 15 years or more = 0', color: '#34d399' },
  { key: 'p_util', w: W.weights.util, label: 'Utilisation', hint: 'share of the site heat used, less pipe distance', color: '#fbbf24' },
];

export const ECO_PARTS = [
  { key: 'e_ghg', w: W.eco_weights.ghg, label: 'Climate (CO2)', hint: 'CO2 avoided per MWh, against a fully replaced gas boiler', color: '#22c55e' },
  { key: 'e_water', w: W.eco_weights.water, label: 'Water', hint: 'water used by the option, plus cooling-tower water saved', color: '#0ea5e9' },
  { key: 'e_local', w: W.eco_weights.local, label: 'Local impact', hint: 'land and ecosystem impact, reduced by mitigation', color: '#f97316' },
];

type Parts = typeof VIABILITY_PARTS;
const sub = (d: Record<string, unknown>, k: string) => (typeof d[k] === 'number' ? (d[k] as number) : null);

export function hasSubscores(d: Record<string, unknown> | undefined): boolean {
  return !!d && sub(d, 'p_thermo') != null;
}

/** Compact stacked bar for the ranking list: each coloured piece = weight × sub-score, full bar = 5. */
export function StackedScore({ details, total }: { details: Record<string, unknown>; total: number | null | undefined }) {
  return (
    <span className="stack-bar" title={VIABILITY_PARTS.map((p) => `${p.label}: ${(sub(details, p.key) ?? 0).toFixed(2)} × ${p.w.toFixed(2)}`).join('\n')}>
      {VIABILITY_PARTS.map((p) => {
        const v = sub(details, p.key) ?? 0;
        return <i key={p.key} style={{ width: `${(p.w * v / 5) * 100}%`, background: p.color }} />;
      })}
      <span className="sr-only">{total}</span>
    </span>
  );
}

/** Legend shown once above the ranking list. */
export function ScoreLegend() {
  return (
    <div className="stack-legend">
      {VIABILITY_PARTS.map((p) => (
        <span key={p.key}><i style={{ background: p.color }} />{p.label} {Math.round(p.w * 100)}%</span>
      ))}
    </div>
  );
}

function Breakdown({ title, parts, details, total, gate }: { title: string; parts: Parts; details: Record<string, unknown>; total: number | null | undefined; gate?: boolean }) {
  const rows = parts.map((p) => {
    const v = sub(details, p.key) ?? 0;
    return { ...p, v, pts: p.w * v };
  });
  const sum = rows.reduce((a, r) => a + r.pts, 0);
  return (
    <div className="breakdown">
      <h5>{title}</h5>
      <table className="breakdown-table">
        <thead><tr><th>Part</th><th className="n">Sub-score (0–5)</th><th className="n">Weight</th><th className="n">Points</th><th className="chart-col">Points out of 5</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td><i className="dot" style={{ background: r.color }} />{r.label}<small>{r.hint}</small></td>
              <td className="n">{r.v.toFixed(2)}</td>
              <td className="n">× {r.w.toFixed(2)}</td>
              <td className="n"><b>{r.pts.toFixed(2)}</b></td>
              <td className="chart-col"><span className="hbar"><i style={{ width: `${(r.v / 5) * 100}%`, background: r.color, opacity: 0.35 }} /><i className="pts" style={{ width: `${(r.pts / (r.w * 5)) * 100}%`, background: r.color }} /></span></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3}>Total{gate === false ? ' before the knock-out gate' : ''}</td>
            <td className="n"><b>{(typeof total === 'number' && Math.abs(total - sum) < 0.02 ? total : sum).toFixed(2)}</b></td>
            <td className="chart-col">
              <span className="stack-bar wide">{rows.map((r) => <i key={r.key} style={{ width: `${(r.pts / 5) * 100}%`, background: r.color }} />)}</span>
            </td>
          </tr>
          {gate === false && <tr><td colSpan={5} className="muted small">A knock-out gate failed, so the final score is 0 (shown: {total ?? 0}).</td></tr>}
        </tfoot>
      </table>
    </div>
  );
}

/** Full breakdown of viability and eco score for one option. */
export function ScoreBreakdown({ details, score, ecoScore, feasible, pies = true }: { details: Record<string, unknown>; score: number | null | undefined; ecoScore?: unknown; feasible: boolean; pies?: boolean }) {
  if (!hasSubscores(details)) return null;
  return (
    <div className="breakdowns">
      {pies && <ScorePies details={details} score={score} ecoScore={ecoScore} />}
      <Breakdown title={`Viability ${score ?? 0} of 5`} parts={VIABILITY_PARTS} details={details} total={score} gate={feasible} />
      <Breakdown title={`Eco score ${typeof ecoScore === 'number' ? ecoScore.toFixed(2) : ''} of 5 (A ≥ 4.2, B ≥ 3.4, C ≥ 2.6, D ≥ 1.8)`} parts={ECO_PARTS} details={details} total={ecoScore as number} />
    </div>
  );
}

const usd = (v: number) => (Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(2)} M` : Math.abs(v) >= 1e3 ? `$${(v / 1e3).toFixed(0)} k` : `$${v.toFixed(0)}`);
const mwh = (v: number) => (v >= 1e3 ? `${(v / 1e3).toFixed(1)} GWh` : `${v.toFixed(0)} MWh`);
const PRODUCT_LABEL: Record<string, string> = {
  heat: 'Heat sold (replaces gas boiler)', stored_heat: 'Stored heat sold', steam: 'Steam saved', cooling: 'Chiller power saved',
  power: 'Electricity sold', water: 'Water sold', co2: 'CO2 captured and sold',
};

/** Pie charts: weights, points of this option, money per year, investment and energy. */
export function ScorePies({ details: d, score, ecoScore }: { details: Record<string, unknown>; score: number | null | undefined; ecoScore?: unknown }) {
  const num = (k: string) => (typeof d[k] === 'number' ? (d[k] as number) : 0);
  const pts = (parts: Parts) => parts.map((p) => ({ label: p.label, value: p.w * num(p.key), color: p.color }));
  const vPts = pts(VIABILITY_PARTS), ePts = pts(ECO_PARTS);
  const vMissed = Math.max(0, 5 - vPts.reduce((a, x) => a + x.value, 0));
  const eMissed = Math.max(0, 5 - ePts.reduce((a, x) => a + x.value, 0));
  const product = typeof d.product === 'string' ? d.product : 'heat';
  const income = num('money_product_usd') + num('money_carbon_usd');
  const costs = num('money_hp_usd') + num('money_om_usd');
  const capex = num('capex_plant_usd') + num('capex_pipe_usd') + num('capex_hp_usd');
  const hasMoney = income > 0 || costs > 0;
  return (
    <div className="pies">
      <h5>At a glance</h5>
      <div className="pie-grid">
        <Pie title="Viability weights (same for every option)" fmt={(v) => `${Math.round(v * 100)} %`} pct={false}
          slices={VIABILITY_PARTS.map((p) => ({ label: p.label, value: p.w, color: p.color, note: p.hint }))}
          caption="How much each part counts towards the 0–5 viability score." />
        <Pie title="This option's viability points" fmt={(v) => v.toFixed(2)} center={(score ?? 0).toFixed(2)} centerSub="of 5"
          slices={[...vPts, { label: 'Points missed', value: vMissed, color: '#52525b' }]}
          caption="Each slice = sub-score × weight. The grey slice is what the option loses against a perfect 5." />
        <Pie title="Eco grade weights" fmt={(v) => `${Math.round(v * 100)} %`} pct={false}
          slices={ECO_PARTS.map((p) => ({ label: p.label, value: p.w, color: p.color, note: p.hint }))}
          caption="The eco grade is scored separately, so a profitable option cannot hide harm." />
        <Pie title="This option's eco points" fmt={(v) => v.toFixed(2)} center={typeof ecoScore === 'number' ? ecoScore.toFixed(2) : ''} centerSub="of 5"
          slices={[...ePts, { label: 'Points missed', value: eMissed, color: '#52525b' }]} />
        {hasMoney && (
          <Pie title="Money in per year" fmt={usd} center={usd(income)} centerSub="per year"
            slices={[
              { label: PRODUCT_LABEL[product] ?? 'Product sold', value: num('money_product_usd'), color: '#34d399', note: 'amount × local price' },
              { label: 'Carbon credit', value: num('money_carbon_usd'), color: '#22c55e', note: 'net CO2 avoided × carbon price' },
            ]} />
        )}
        {hasMoney && (
          <Pie title="Money out per year" fmt={usd} center={usd(costs)} centerSub="per year"
            slices={[
              { label: 'Heat-pump electricity', value: num('money_hp_usd'), color: '#f87171', note: 'heat-pump MWh × electricity price' },
              { label: 'Operation and maintenance', value: num('money_om_usd'), color: '#fb923c', note: '2 % of the investment each year' },
            ]}
            caption={`Net = ${usd(income)} − ${usd(costs)} = ${usd(num('money_net_usd'))} per year.`} />
        )}
        {capex > 0 && (
          <Pie title="Investment (one-off)" fmt={usd} center={usd(capex)} centerSub="total"
            slices={[
              { label: 'Plant', value: num('capex_plant_usd'), color: '#60a5fa', note: 'heat used (kW) × plant cost per kW' },
              { label: 'Pipes', value: num('capex_pipe_usd'), color: '#a78bfa', note: 'distance (m) × pipe cost per m' },
              { label: 'Heat pump', value: num('capex_hp_usd'), color: '#f472b6', note: 'peak heat (kW) × $600/kW' },
            ]}
            caption={num('money_net_usd') > 0 ? `Payback = ${usd(capex)} ÷ ${usd(num('money_net_usd'))} per year = ${(capex / num('money_net_usd')).toFixed(1)} years.` : 'Net money per year is not positive, so it never pays back.'} />
        )}
        {num('energy_del_mwh') > 0 && (
          <Pie title={product === 'power' ? 'Energy per year (server heat → electricity)' : 'Where the delivered heat comes from'} fmt={mwh}
            center={mwh(num('energy_del_mwh'))} centerSub={product === 'power' ? 'electricity out' : 'delivered'}
            slices={product === 'power'
              ? [{ label: 'Electricity generated', value: num('energy_del_mwh'), color: '#fbbf24' },
                 { label: 'Heat rejected by the ORC', value: Math.max(0, num('energy_src_mwh') - num('energy_del_mwh')), color: 'var(--border)' }]
              : [{ label: 'Free server heat', value: num('energy_src_mwh'), color: '#38bdf8', note: 'taken from the data center coolant' },
                 { label: 'Heat-pump electricity', value: num('energy_hp_mwh'), color: '#f87171', note: 'power added to lift the temperature' }]}
            caption={product === 'power' ? undefined : 'Delivered heat = server heat + heat-pump electricity. More blue = better thermodynamics score.'} />
        )}
      </div>
    </div>
  );
}
