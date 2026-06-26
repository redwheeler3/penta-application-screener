// Typed wrappers over the backend HTTP API. These do fetch + JSON only; callers
// own state, toasts, and streaming orchestration.
import { apiBaseUrl } from "./constants";
import type {
  AppFilter,
  AppSettings,
  ApplicationDetail,
  ApplicationSummary,
  AppFacets,
  Coverage,
  CurrentUser,
  DashboardCounts,
  QualityFlagEstimate,
  RankEstimate,
  SettingsResponse,
  SortState,
  Tier,
  WorkflowState,
} from "./types";

function url(path: string): string {
  return `${apiBaseUrl}${path}`;
}

function getJson<T>(path: string): Promise<T> {
  return fetch(url(path), { credentials: "include" }).then((r) => r.json() as Promise<T>);
}

export const authLoginUrl = () => url("/auth/google/login");

export function fetchCurrentUser(): Promise<CurrentUser | null> {
  return getJson<{ user: CurrentUser | null }>("/auth/me").then((p) => p.user);
}

export function logout(): Promise<Response> {
  return fetch(url("/auth/logout"), { method: "POST", credentials: "include" });
}

export const fetchSettings = () => getJson<SettingsResponse>("/settings");

export function saveSettings(draft: AppSettings): Promise<Response> {
  return fetch(url("/settings"), {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
}

export const fetchDashboard = () =>
  getJson<{ counts: DashboardCounts; workflow: WorkflowState; coverage: Coverage }>("/dashboard");

export type ApplicationsResponse = {
  applications: ApplicationSummary[];
  total: number;
  page: number;
  pageSize: number;
  facets: AppFacets;
};

export function fetchApplications(args: {
  filter: AppFilter;
  page: number;
  search: string;
  pageSize: number;
  sort: SortState;
}): Promise<ApplicationsResponse> {
  const params = new URLSearchParams();
  if (args.filter.status) params.set("status", args.filter.status);
  if (args.filter.status_source) params.set("status_source", args.filter.status_source);
  if (args.search) params.set("search", args.search);
  if (args.sort) {
    params.set("sort", args.sort.key);
    params.set("direction", args.sort.direction);
  }
  params.set("page", String(args.page));
  params.set("page_size", String(args.pageSize));
  return getJson<ApplicationsResponse>(`/applications?${params}`);
}

export function fetchApplication(id: number): Promise<ApplicationDetail> {
  return getJson<{ application: ApplicationDetail }>(`/applications/${id}`).then((p) => p.application);
}

export function syncApplications(): Promise<Response> {
  return fetch(url("/sync/applications"), { method: "POST", credentials: "include" });
}

export const fetchScreeningCurrent = () => fetch(url("/screening/current"), { credentials: "include" });

export const fetchQualityFlagsEstimate = () => fetch(url("/quality-flags/estimate"), { credentials: "include" });
export const runQualityFlags = () => fetch(url("/quality-flags/run"), { method: "POST", credentials: "include" });

export const fetchRankEstimate = () => fetch(url("/screening/rank/estimate"), { credentials: "include" });
export const runRank = () => fetch(url("/screening/rank/run"), { method: "POST", credentials: "include" });

export function fetchRanking(): Promise<Response> {
  return fetch(url("/screening/ranking"), { credentials: "include" });
}

export function fetchTiers(): Promise<Response> {
  return fetch(url("/screening/tiers"), { credentials: "include" });
}

export function saveTiers(next: Tier[], acknowledgedKeys: string[]): Promise<Response> {
  return fetch(url("/screening/tiers"), {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tiers: next, acknowledged_keys: acknowledgedKeys }),
  });
}

// Persist discovery seeds for the current run. Each field is optional so the UI can
// update favourites without touching proposals (and vice versa). The next Rank reads
// these from the run, so they take effect on its discovery pass.
export function saveSeeds(seeds: { favourited_keys?: string[]; proposed_dimensions?: string[] }): Promise<Response> {
  return fetch(url("/screening/seeds"), {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(seeds),
  });
}

export function overrideStatus(id: number, status: string): Promise<Response> {
  return fetch(url(`/applications/${id}/status`), {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

export function clearStatusOverride(id: number): Promise<Response> {
  return fetch(url(`/applications/${id}/status`), { method: "DELETE", credentials: "include" });
}

// Read an NDJSON stream, invoking `onEvent` for each parsed line. Used by the
// quality-flag and Rank runs, which stream progress then a summary.
export async function streamNdjson(body: ReadableStream<Uint8Array>, onEvent: (event: any) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? ""; // keep any partial line for the next chunk
    for (const line of lines) {
      if (!line.trim()) continue;
      onEvent(JSON.parse(line));
    }
  }
}
