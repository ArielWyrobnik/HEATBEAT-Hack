/**
 * 365-day daily min / max air temperature for a location, as the DSX evaluator needs it.
 * 1) Open-Meteo historical archive for 2024 (ERA5, free, no key), same weather year as the backend.
 * 2) Fallback: a synthetic year shaped from the backend's weather summary (mean, min, max, warmest month).
 */
export interface DailyClimate {
  t_min: number[];
  t_max: number[];
  source: string;
  synthetic: boolean;
}

const cache = new Map<string, Promise<DailyClimate>>();

async function openMeteo(lat: number, lon: number): Promise<DailyClimate> {
  const url = 'https://archive-api.open-meteo.com/v1/archive'
    + `?latitude=${lat.toFixed(3)}&longitude=${lon.toFixed(3)}&start_date=2024-01-01&end_date=2024-12-31`
    + '&daily=temperature_2m_max,temperature_2m_min&timezone=auto';
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Open-Meteo ${res.status}`);
  const j = await res.json();
  const tmax: (number | null)[] = j?.daily?.temperature_2m_max ?? [];
  const tmin: (number | null)[] = j?.daily?.temperature_2m_min ?? [];
  if (tmax.length < 365 || tmin.length !== tmax.length) throw new Error('Open-Meteo returned an incomplete year');
  // fill rare gaps with the neighbouring day
  const fill = (a: (number | null)[]) => a.map((v, i) => (v ?? a[i - 1] ?? a[i + 1] ?? 0) as number);
  return { t_min: fill(tmin), t_max: fill(tmax), source: 'Open-Meteo archive (ERA5), 2024 daily min/max', synthetic: false };
}

/** Annual sine through the summary statistics; diurnal range takes a third of the half-spread. */
export function syntheticYear(w: Record<string, unknown>): DailyClimate {
  const mean = Number(w.t_db_mean_c), lo = Number(w.t_db_min_c), hi = Number(w.t_db_max_c);
  if (![mean, lo, hi].every(Number.isFinite)) throw new Error('No weather summary for this site');
  const warm = Number.isFinite(Number(w.warmest_month)) ? Number(w.warmest_month) : 7;
  const half = Math.max(1, (hi - lo) / 2);
  const diurnal = half / 3, seasonal = half - diurnal;
  const peakDay = (warm - 1) * 30.4 + 15;
  const t_min: number[] = [], t_max: number[] = [];
  for (let d = 1; d <= 365; d++) {
    const m = mean + seasonal * Math.cos((2 * Math.PI * (d - peakDay)) / 365);
    t_min.push(m - diurnal); t_max.push(m + diurnal);
  }
  return { t_min, t_max, source: 'synthetic year from the site weather summary (mean, min, max, warmest month)', synthetic: true };
}

export function dailyClimate(lat: number, lon: number, weather?: Record<string, unknown>): Promise<DailyClimate> {
  const key = `${lat.toFixed(2)},${lon.toFixed(2)}`;
  let p = cache.get(key);
  if (!p) {
    p = openMeteo(lat, lon).catch((e) => {
      cache.delete(key); // retry next time
      if (weather) return { ...syntheticYear(weather), source: `${syntheticYear(weather).source}; Open-Meteo unavailable (${(e as Error).message})` };
      throw e;
    });
    cache.set(key, p);
  }
  return p;
}
