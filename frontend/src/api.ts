import type { CoolingProfile, ModelInfo, ModelResult, PlanRequest, SiteInputs, SiteSummary } from './types/api';
import { DSX_INPUT_MODEL, DSX_MODEL, runDsx } from './dsx/adapter';
import { isReference, referenceInputs, referenceSiteInputs, referenceSummaries } from './dsx/referenceSites';

/** Base URL of heatbeat_api. Empty = same origin (Vite proxies /api to the backend). */
const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '';

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && q.set(k, String(v)));
  const res = await fetch(`${BASE}/api${path}${q.size ? `?${q}` : ''}`);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(`${res.status}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(`${res.status}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
  }
  return res.json() as Promise<T>;
}

const backend = {
  coolingProfiles: () => get<CoolingProfile[]>('/cooling-profiles'),
  plan: (req: PlanRequest) => post<ModelResult>('/plan', req),
  sites: () => get<SiteSummary[]>('/sites'),
  models: () => get<ModelInfo[]>('/models'),
  inputs: (id: string, p: { model?: string; is_greenfield?: number }) => get<SiteInputs>(`/sites/${id}/inputs`, p),
  ranking: (id: string, p: { model?: string; mode?: string; is_greenfield?: number }) =>
    get<ModelResult>(`/sites/${id}/ranking`, p),
};

/*
 * This local build runs one model: the DSX evaluator (src/dsx), in the browser.
 * - Backend sites: it reuses the backend's 31 inputs and baseline of the Team Excel ranking (same keys).
 * - Reference sites (ids "ref-..."): real heat reuse sites from src/dsx/referenceSites.ts, evaluated fully
 *   locally from published facts and flagged estimates; they still work when the backend is offline.
 */
let sitesCache: Promise<SiteSummary[]> | null = null;
const backendSites = () => (sitesCache ??= backend.sites().catch((e) => { sitesCache = null; throw e; }));
const siteById = async (id: string) => {
  const s = (await backendSites()).find((x) => x.site_id === id);
  if (!s) throw new Error(`Unknown site ${id}`);
  return s;
};

export const api = {
  coolingProfiles: backend.coolingProfiles,
  /** Backend sites plus the reference sites; reference sites alone when the backend is offline. */
  sites: async (): Promise<SiteSummary[]> => {
    const refs = referenceSummaries();
    try { return [...(await backendSites()), ...refs]; } catch { return refs; }
  },
  models: async (): Promise<ModelInfo[]> => [{ ...DSX_MODEL, default: true }],
  inputs: (id: string, p: { model?: string; is_greenfield?: number }) =>
    isReference(id) ? Promise.resolve(referenceSiteInputs(id, p.is_greenfield))
      : backend.inputs(id, { is_greenfield: p.is_greenfield, model: DSX_INPUT_MODEL }),
  ranking: async (id: string, p: { model?: string; mode?: string; is_greenfield?: number }): Promise<ModelResult> => {
    if (isReference(id)) {
      const { inputs, used, baseline, site } = referenceInputs(id, p.is_greenfield);
      const r = await runDsx({ siteId: id, lat: site.lat, lon: site.lng, mode: p.mode, inputsUsed: used, inputs, baseline, weather: site.climate });
      if (site.note) r.warnings.unshift(site.note);
      if (p.is_greenfield !== 1 && used.is_greenfield === 1) r.warnings.unshift('Evaluated as designed-in (greenfield): heat reuse was built together with this site.');
      r.warnings.unshift('Reference site: inputs marked Real come from public sources, the rest are planning estimates (see Inputs).');
      return r;
    }
    const q = { model: DSX_INPUT_MODEL, is_greenfield: p.is_greenfield };
    const [ref, inp, site] = await Promise.all([backend.ranking(id, q), backend.inputs(id, q), siteById(id)]);
    return runDsx({ siteId: id, lat: site.lat, lon: site.lon, mode: p.mode, inputsUsed: ref.inputs_used,
      inputs: inp.inputs, baseline: ref.baseline, weather: inp.weather });
  },
  plan: async (req: PlanRequest): Promise<ModelResult> => {
    const ref = await backend.plan({ ...req, model: DSX_INPUT_MODEL, mode: null });
    return runDsx({ siteId: ref.site_id, lat: req.lat, lon: req.lon, mode: req.mode, inputsUsed: ref.inputs_used,
      inputs: ref.inputs, baseline: ref.baseline, keepInputs: true, planned: ref.planned_site });
  },
};
