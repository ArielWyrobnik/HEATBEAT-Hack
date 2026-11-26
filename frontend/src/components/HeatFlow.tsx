import { compact, num } from '../format';
import type { OptionResult } from '../types/api';

export type HeatOrder = 'heat' | 'value';

export function heatFirst(a: OptionResult, b: OptionResult) {
  return (b.kpis.heat_recovered_mwh_yr ?? 0) - (a.kpis.heat_recovered_mwh_yr ?? 0)
    || (a.rank ?? Infinity) - (b.rank ?? Infinity);
}

const annualHeat = (mwh: number) => `${mwh > 0 && mwh < 0.01 ? '<0.01' : compact(mwh)} MWh/yr`;
const heatShare = (heat: number, total: number) => total > 0 ? Math.min(100, heat / total * 100) : 0;

export function reuseShare(o: OptionResult, total?: number | null) {
  if (!total) return 'n/a';
  const share = heatShare(o.kpis.heat_recovered_mwh_yr ?? 0, total);
  return share > 0 && share < 0.1 ? '<0.1%' : `${num(share, 1)}%`;
}

export function HeatOrderSelect({ order, onChange }: { order: HeatOrder; onChange: (order: HeatOrder) => void }) {
  return (
    <label className="heat-order">Rank by
      <select value={order} onChange={(e) => onChange(e.target.value === 'value' ? 'value' : 'heat')}>
        <option value="heat">Most heat sent to reuse</option>
        <option value="value">Highest net present value</option>
      </select>
    </label>
  );
}

const LOOP_LABELS: Record<string, string> = { air: 'Air-side cooling loop', liquid: 'Liquid cooling loop' };

export default function HeatFlow({ option }: { option: OptionResult }) {
  if (!option.heat_loops?.length) return null;
  const total = option.heat_loops.reduce((sum, loop) => sum + loop.mwh_yr, 0);
  const recovered = option.kpis.heat_recovered_mwh_yr ?? 0;
  const share = heatShare(recovered, total);
  return (
    <figure className="heat-flow" aria-label="Annual server heat flow">
      <figcaption>
        <strong>Where the server heat goes</strong>
        <span><b>{reuseShare(option, total)}</b> sent to reuse</span>
      </figcaption>
      <div className="heat-flow-meter" aria-hidden="true">
        <div style={{ width: `${share}%` }} />
      </div>
      <div className="heat-flow-totals">
        <span>Reuse <b>{annualHeat(recovered)}</b></span>
        <span>Cooling <b>{annualHeat(Math.max(0, total - recovered))}</b></span>
      </div>
      <div className="heat-flow-source">
        <b>Data center servers</b>
        <span>{annualHeat(total)}</span>
      </div>
      <ul className="heat-flow-loops">
        {option.heat_loops.map((loop) => (
          <li key={loop.name}>
            <div className="heat-flow-loop">
              <div><b>{LOOP_LABELS[loop.name] ?? loop.name}</b><small>{num(loop.return_c, 1)} °C return</small></div>
              <span>{annualHeat(loop.mwh_yr)}</span>
            </div>
            <ul className="heat-flow-routes">
              {loop.routes.map((route) => (
                <li key={route.name} className={`heat-flow-route ${route.kind}`}>
                  <div><small>{route.kind === 'reuse' ? 'Heat reuse' : 'Cooling'}</small>{route.name}</div>
                  <span>{annualHeat(route.mwh_yr)}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <p>Amounts count server heat only, measured before transfer and conversion losses.</p>
    </figure>
  );
}
