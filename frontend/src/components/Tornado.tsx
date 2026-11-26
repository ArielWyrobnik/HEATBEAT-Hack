import type { Tornado as T } from '../types/api';
import { compact, value } from '../format';

/** Horizontal tornado chart: effect of each input's low and high value on one metric, largest first. */
export default function Tornado({ data, optionName }: { data: T; optionName: string }) {
  const bars = data.bars.slice(0, 8);
  if (!bars.length) return null;
  const all = bars.flatMap((b) => [b.metric_low, b.metric_high]);
  const lo = Math.min(data.base, ...all);
  const hi = Math.max(data.base, ...all);
  const W = 420, labelW = 170, rowH = 26, top = 20, plotW = W - labelW - 12;
  const x = (v: number) => labelW + ((v - lo) / (hi - lo || 1)) * plotW;
  const H = top + bars.length * rowH + 22;
  const name = (b: T['bars'][number]) => b.label ?? b.input;
  return (
    <figure className="tornado">
      <figcaption>
        Sensitivity of <b>{optionName}</b>: {data.metric.replace(/_usd_yr$|_mwh_yr$|_t_yr$/, '').replace(/_/g, ' ')} ({data.unit})
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Tornado chart">
        {bars.map((b, i) => {
          const y = top + i * rowH;
          const seg = (v: number, cls: string, end: unknown) => {
            const a = Math.min(x(v), x(data.base));
            const w = Math.max(1, Math.abs(x(v) - x(data.base)));
            return (
              <rect x={a} y={y + 4} width={w} height={rowH - 10} className={cls}>
                <title>{`${name(b)} = ${value(end)}: ${compact(v)}`}</title>
              </rect>
            );
          };
          return (
            <g key={b.input}>
              <text x={labelW - 8} y={y + rowH / 2 + 4} textAnchor="end" className="t-label">
                {name(b)}{b.flag && b.flag !== 'real' ? ' *' : ''}
              </text>
              {seg(b.metric_low, 't-low', b.low_value)}
              {seg(b.metric_high, 't-high', b.high_value)}
            </g>
          );
        })}
        <line x1={x(data.base)} x2={x(data.base)} y1={top - 4} y2={H - 18} className="t-base" />
        <text x={x(data.base)} y={12} className="t-axis" textAnchor="middle">base {compact(data.base)}</text>
        <text x={labelW} y={H - 4} className="t-axis">{compact(lo)}</text>
        <text x={W - 12} y={H - 4} className="t-axis" textAnchor="end">{compact(hi)}</text>
      </svg>
      <div className="t-legend">
        <span><i className="t-low" /> input at low end</span>
        <span><i className="t-high" /> input at high end</span>
        <span>* not site data</span>
      </div>
    </figure>
  );
}
