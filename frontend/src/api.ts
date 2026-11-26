import type { CoolingProfile, LeaderboardRow, ModelInfo, ModelResult, PlanRequest, SiteInputs, SiteSummary } from './types/api';

export interface EvaluateRequest {
  site_id: string;
  model?: string;
  mode?: string;
  is_greenfield?: number;
  overrides: Record<string, unknown>;
  tornado?: boolean;
}

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

export const api = {
  config: () => get<{ feedback_url: string | null; sites_scope?: string; n_sites_all?: number; n_sites_verified?: number }>('/config'),
  coolingProfiles: () => get<CoolingProfile[]>('/cooling-profiles'),
  plan: (req: PlanRequest) => post<ModelResult>('/plan', req),
  evaluate: (req: EvaluateRequest) => post<ModelResult>('/evaluate', req),
  /** scope: 'verified' (sites with documented cooling) or 'all'; omitted = server default (HEATBEAT_SITES) */
  sites: (scope?: string) => get<SiteSummary[]>('/sites', { scope }),
  leaderboard: (scope?: string) => get<LeaderboardRow[]>('/leaderboard', { scope }),
  models: () => get<ModelInfo[]>('/models'),
  inputs: (id: string, p: { model?: string; is_greenfield?: number }) => get<SiteInputs>(`/sites/${id}/inputs`, p),
  ranking: (id: string, p: { model?: string; mode?: string; is_greenfield?: number }) =>
    get<ModelResult>(`/sites/${id}/ranking`, p),
};
