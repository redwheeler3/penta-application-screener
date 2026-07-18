// Typed wrappers over the backend HTTP API. These do fetch + JSON only; callers
// own state, toasts, and streaming orchestration.
import { apiBaseUrl } from "./constants";
import type {
  AppFilter,
  AppSettings,
  ApplicationDetail,
  ApplicationSummary,
  AppFacets,
  ConsolidateAuditResponse,
  CostReport,
  Coverage,
  CurrentUser,
  DashboardCounts,
  DecomposeAuditResponse,
  FanOutAuditResponse,
  LastRunsReport,
  MatchAuditResponse,
  MetricsReport,
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
  if (args.filter.statusSource) params.set("statusSource", args.filter.statusSource);
  if (args.search) params.set("search", args.search);
  if (args.sort) {
    params.set("sort", args.sort.key);
    params.set("direction", args.sort.direction);
  }
  params.set("page", String(args.page));
  params.set("pageSize", String(args.pageSize));
  return getJson<ApplicationsResponse>(`/applications?${params}`);
}

export function fetchApplication(id: number): Promise<ApplicationDetail> {
  return getJson<{ application: ApplicationDetail }>(`/applications/${id}`).then((p) => p.application);
}

export function syncApplications(): Promise<Response> {
  return fetch(url("/sync/applications"), { method: "POST", credentials: "include" });
}

export const fetchRankingCurrent = () => fetch(url("/ranking/current"), { credentials: "include" });

// The current run's carry-forward audit (M13 per-run AI legibility). Null when no
// run exists or the run predates match-audit capture.
export const fetchMatchAudit = () => getJson<MatchAuditResponse | null>("/ranking/current/match-audit");

// The current run's decomposition audit — how the K fan-out discovery reports were
// settled into one set (settled axes + merge reasoning + D9 folded-request trail).
// Null on runs that predate the fan-out redesign.
export const fetchDecomposeAudit = () =>
  getJson<DecomposeAuditResponse | null>("/ranking/current/decompose-audit");

export const fetchConsolidateAudit = () =>
  getJson<ConsolidateAuditResponse | null>("/ranking/current/consolidate-audit");

// The current run's fan-out audit — each of the K parallel discoverers' dimensions +
// reasoning. Null on runs that predate the fan-out redesign.
export const fetchFanOutAudit = () =>
  getJson<FanOutAuditResponse | null>("/ranking/current/fan-out-audit");

// Aggregated AI spend (M13 Pillar 1): cumulative, grouped by run.
export const fetchCostReport = () => getJson<CostReport>("/ranking/insights/cost");

// The most recent Screen and Rank runs, each with fresh spend + cache savings.
export const fetchLastRuns = () => getJson<LastRunsReport>("/ranking/insights/last-runs");

// Operational trends across all runs (M13 Pillar 3): cost/tokens/latency/cache/failures.
export const fetchMetrics = () => getJson<MetricsReport>("/ranking/insights/metrics");

export const fetchScreeningEstimate = () => fetch(url("/screening/estimate"), { credentials: "include" });
export const runScreening = () => fetch(url("/screening/run"), { method: "POST", credentials: "include" });

export const fetchRankEstimate = () => fetch(url("/ranking/estimate"), { credentials: "include" });
export const runRank = () => fetch(url("/ranking/run"), { method: "POST", credentials: "include" });
export const fetchScoreCurrentEstimate = () =>
  fetch(url("/ranking/score-current/estimate"), { credentials: "include" });
export const scoreCurrent = () => fetch(url("/ranking/score-current"), { method: "POST", credentials: "include" });

export function fetchRanking(): Promise<Response> {
  return fetch(url("/ranking"), { credentials: "include" });
}

export function fetchTiers(): Promise<Response> {
  return fetch(url("/ranking/tiers"), { credentials: "include" });
}

export function saveTiers(next: Tier[], acknowledgedKeys: string[]): Promise<Response> {
  return fetch(url("/ranking/tiers"), {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tiers: next, acknowledgedKeys }),
  });
}

// Persist pending free-text proposals for the current run. The next Rank reads these
// from the run, so they take effect on its discovery pass. (Keeping an existing axis
// across re-runs is tier placement — see saveTiers — not a seed.)
export function saveSeeds(seeds: { proposedDimensions?: string[] }): Promise<Response> {
  return fetch(url("/ranking/seeds"), {
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

export function savePrivateNote(id: number, note: string): Promise<Response> {
  return fetch(url(`/applications/${id}/note`), {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
}

// --- Evals tab -------------------------------------------------------------

// The runnable evals + their spend estimates (free; no model calls).
export function fetchEvalCatalog(): Promise<Response> {
  return fetch(url("/evals/catalog"), { credentials: "include" });
}

// Deterministic invariants over the baseline fixture (free).
export function fetchEvalInvariants(): Promise<Response> {
  return fetch(url("/evals/invariants"), { credentials: "include" });
}

// Re-record the invariant baseline fixture from the current Rank (writes the committed
// rank_baseline.json — commit to git afterward). Returns the fresh invariants.
export function rebaselineEval(): Promise<Response> {
  return fetch(url("/evals/baseline"), { method: "POST", credentials: "include" });
}

// The eval's cases, straight from its committed JSON fixture (free).
export function fetchEvalCases(evalKey: string): Promise<Response> {
  return fetch(url(`/evals/cases/${evalKey}`), { credentials: "include" });
}

// Propose unlabelled judge cases from the CURRENT run's scoring/screening output (the
// fidelity-preserving harvest). Guard-gated server-side; 409 no run, 422 non-synthetic pool.
export function harvestEvalCases(family: "scoring" | "screening"): Promise<Response> {
  return fetch(url(`/evals/harvest/${family}`), { credentials: "include" });
}

// Upsert one case (by its `key`) into the eval's fixture FILE. Validated server-side;
// the operator commits the changed file to git deliberately.
export function saveEvalCase(evalKey: string, evalCase: unknown): Promise<Response> {
  return fetch(url(`/evals/cases/${evalKey}`), {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case: evalCase }),
  });
}

// Start a streaming eval run (live_scoring | judge | stability). Returns the raw
// Response so the caller reads its NDJSON body via streamNdjson. Spends model $.
// `caseKey` runs just that one case (per-row run); `k` sets stability repeats.
export function runEval(
  key: "live_scoring" | "judge" | "stability",
  opts?: { k?: number; caseKey?: string },
): Promise<Response> {
  const path = key === "live_scoring" ? "/evals/live-scoring" : `/evals/${key}`;
  const params = new URLSearchParams();
  if (key === "stability" && opts?.k) params.set("k", String(opts.k));
  if (opts?.caseKey) params.set("case", opts.caseKey);
  const q = params.toString() ? `?${params}` : "";
  return fetch(url(path + q), { method: "POST", credentials: "include" });
}

// Read an NDJSON stream, invoking `onEvent` for each parsed line. Used by the
// screening and Rank runs, which stream progress then a summary.
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
