import { api } from './api';
import type { DataCenter } from './types/datacenter';

const isValid = (d: any): d is DataCenter =>
  d && typeof d.name === 'string' && Number.isFinite(+d.lat) && Number.isFinite(+d.lng);

export interface LoadResult {
  dataCenters: DataCenter[];
  /** true when the pins come from the backend (clicking a pin can then load results) */
  fromApi: boolean;
}

/** ?sites=all or ?sites=verified in the browser address overrides the server default. */
export function siteScope(): string | undefined {
  const v = new URLSearchParams(window.location.search).get('sites');
  return v === 'all' || v === 'verified' ? v : undefined;
}

/** Pins from the backend (GET /api/sites); falls back to public/datacenters.json without a backend. */
export async function loadDataCenters(): Promise<LoadResult> {
  try {
    const sites = await api.sites(siteScope());
    return {
      fromApi: true,
      dataCenters: sites.map((s) => ({
        ...s,
        id: s.site_id,
        name: s.name,
        lat: s.lat,
        lng: s.lon,
        operator: s.operator ?? undefined,
        city: s.city ?? undefined,
        country: s.country ?? undefined,
        capacityMW: s.capacity_mw ?? s.it_load_mw ?? undefined,
        pue: s.pue ?? undefined,
      })),
    };
  } catch {
    /* backend not running: static file */
  }
  try {
    const res = await fetch(`${import.meta.env.BASE_URL}datacenters.json`);
    if (!res.ok) return { dataCenters: [], fromApi: false };
    const raw = await res.json();
    const list = Array.isArray(raw) ? raw : raw.datacenters ?? [];
    return {
      fromApi: false,
      dataCenters: list.filter(isValid).map((d: any, i: number) => ({ ...d, id: String(d.id ?? i), lat: +d.lat, lng: +d.lng })),
    };
  } catch {
    return { dataCenters: [], fromApi: false };
  }
}
