/** Small SVG donut chart with a legend. Slices with value 0 are skipped. */
export type Slice = { label: string; value: number; color: string; note?: string };

const fmtDefault = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 2 });

export default function Pie({ title, slices, center, centerSub, fmt = fmtDefault, size = 120, caption, pct = true }: {
  title: string;
  slices: Slice[];
  center?: string;
  centerSub?: string;
  fmt?: (v: number) => string;
  size?: number;
  caption?: string;
  /** show the share column (off when the values already are shares) */
  pct?: boolean;
}) {
  const shown = slices.filter((s) => s.value > 0);
  const total = shown.reduce((a, s) => a + s.value, 0);
  const r = 42, c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <figure className="pie">
      <figcaption>{title}</figcaption>
      <div className="pie-body">
        <svg viewBox="0 0 100 100" width={size} height={size} role="img" aria-label={title}>
          <circle cx="50" cy="50" r={r} fill="none" stroke="var(--border)" strokeWidth="14" />
          {total > 0 && shown.map((s) => {
            const len = (s.value / total) * c;
            const el = (
              <circle key={s.label} cx="50" cy="50" r={r} fill="none" stroke={s.color} strokeWidth="14"
                strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} transform="rotate(-90 50 50)">
                <title>{`${s.label}: ${fmt(s.value)} (${((s.value / total) * 100).toFixed(0)} %)`}</title>
              </circle>
            );
            offset += len;
            return el;
          })}
          {center && <text x="50" y={centerSub ? 49 : 54} textAnchor="middle" className="pie-center">{center}</text>}
          {centerSub && <text x="50" y="62" textAnchor="middle" className="pie-center-sub">{centerSub}</text>}
        </svg>
        <ul className={`pie-legend${pct ? '' : ' no-pct'}`}>
          {shown.map((s) => (
            <li key={s.label}>
              <i style={{ background: s.color }} />
              <span>{s.label}{s.note && <small>{s.note}</small>}</span>
              <b>{fmt(s.value)}</b>
              {pct && <em>{total > 0 ? `${((s.value / total) * 100).toFixed(0)} %` : ''}</em>}
            </li>
          ))}
          {shown.length === 0 && <li className="muted">Nothing to show</li>}
        </ul>
      </div>
      {caption && <p className="pie-caption">{caption}</p>}
    </figure>
  );
}
