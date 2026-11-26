/** Number formatting for the site panel. */
export function num(v: number | null | undefined, digits = 0): string {
  if (v == null || !Number.isFinite(v)) return 'n/a';
  return v.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

/** Compact: 12.3 k, 3.4 M, 5.6 B */
export function compact(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return 'n/a';
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(digits)} B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(digits)} M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(digits)} k`;
  return num(v, a < 10 ? 2 : 0);
}

export const usd = (v: number | null | undefined) => (v == null ? 'n/a' : `$${compact(v)}`);

export function value(v: unknown): string {
  if (typeof v === 'number') return Math.abs(v) >= 1000 ? num(v) : num(v, 3);
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (v == null) return 'n/a';
  return String(v);
}
