import type { DataCenter } from './types/datacenter';

const isValid = (d: any): d is DataCenter =>
  d && typeof d.name === 'string' && Number.isFinite(+d.lat) && Number.isFinite(+d.lng);

export async function loadDataCenters(): Promise<DataCenter[]> {
  try {
    const res = await fetch(`${import.meta.env.BASE_URL}datacenters.json`);
    if (!res.ok) return [];
    const raw = await res.json();
    const list = Array.isArray(raw) ? raw : raw.datacenters ?? [];
    return list.filter(isValid).map((d: any, i: number) => ({
      ...d,
      id: String(d.id ?? i),
      lat: +d.lat,
      lng: +d.lng,
    }));
  } catch {
    return [];
  }
}
