import { compact, num } from '../format';
import type { OptionResult } from '../types/api';

const LOOP_LABELS: Record<string, string> = { air: 'Air-side cooling loop', liquid: 'Liquid cooling loop' };
const annualHeat = (mwh: number) => `${mwh > 0 && mwh < 0.01 ? '<0.01' : compact(mwh)} MWh/yr`;

/** Where the server heat goes: total server heat, the part this option reuses, the rest to cooling. */
export default function HeatFlow({ option }: { option: OptionResult }) {
  if (!option.heat_loops?.length) return null;
  const total = option.heat_loops.reduce((sum, loop) => sum + loop.mwh_yr, 0);
  const recovered = option.heat_loops.flatMap((l) => l.routes).filter((r) => r.kind === 'reuse').reduce((a, r) => a + r.mwh_yr, 0);
  const share = total > 0 ? Math.min(100, (recovered / total) * 100) : 0;
  return (
    <figure className="heat-flow" aria-label="Annual server heat flow">
      <figcaption>
        <strong>Where the server heat goes</strong>
        <span><b>{share > 0 && share < 0.1 ? '<0.1%' : `${num(share, 1)}%`}</b> sent to reuse</span>
      </figcaption>
      <div className="heat-flow-meter" aria-hidden="true"><div style={{ width: `${share}%` }} /></div>
      <div className="heat-flow-totals">
        <span>Reuse <b>{annualHeat(recovered)}</b></span>
        <span>Cooling <b>{annualHeat(Math.max(0, total - recovered))}</b></span>
      </div>
      <div className="heat-flow-source"><b>Data center servers</b><span>{annualHeat(total)}</span></div>
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
