// Typed wrappers over the backend HTTP API. These do fetch + JSON only; callers
// own state, toasts, and streaming orchestration.
import { apiBaseUrl } from "./constants";
import type {
  AllowlistEntry,
  DeniedSignInAttempt,
  AppSettings,
  ApplicationDetail,
  ApplicationSummary,
  CommitteeOpening,
  ConsolidateAuditResponse,
  CostReport,
  Coverage,
  CurrentRunResponse,
  CurrentUser,
  DashboardCounts,
  DecomposeAuditResponse,
  EligibilityRules,
  EligibilityCheckCatalog,
  EligibilityRulesResponse,
  EvalDescriptor,
  EvalRunMode,
  EvalStreamEvent,
  FanOutAuditResponse,
  FeedbackItem,
  InvariantsResult,
  JudgeBackground,
  LastEvalRun,
  LastRunsReport,
  MatchAuditResponse,
  MetricsReport,
  Opening,
  OpeningWrite,
  RankEstimateResponse,
  RankingResponse,
  RankingStreamEvent,
  ScoreCurrentEstimateResponse,
  ScreeningEstimateResponse,
  ScreeningStreamEvent,
  SettingsResponse,
  Tier,
  WorkflowState,
} from "./types";

function url(path: string): string {
  return `${apiBaseUrl}${path}`;
}

const GET_TIMEOUT_MS = 15_000;
const ACTION_REQUEST_TIMEOUT_MS = 30_000;
const SYNC_RETRY_DELAY_MS = 500;

export async function request(path: string, init: RequestInit = {}, timeoutMs = ACTION_REQUEST_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const callerSignal = init.signal;
  const abortForCaller = () => controller.abort();
  if (callerSignal?.aborted) {
    controller.abort();
  } else {
    callerSignal?.addEventListener("abort", abortForCaller, { once: true });
  }
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url(path), { ...init, credentials: "include", signal: controller.signal });
  } catch (error) {
    // A caller-initiated abort is control flow, not a failed request. Let that caller
    // suppress its own stale result while preserving the timeout response below.
    if (callerSignal?.aborted) throw error;
    // Callers already turn non-OK Responses into inline errors or toasts. Represent an aborted
    // or dropped request the same way so a timed-out mutation clears its busy state instead of
    // escaping its handler as an unhandled rejection.
    const detail = error instanceof DOMException && error.name === "AbortError"
      ? "Request timed out. Please try again."
      : "Network request failed. Please try again.";
    return new Response(JSON.stringify({ detail }), {
      status: 503,
      headers: { "Content-Type": "application/problem+json" },
    });
  } finally {
    window.clearTimeout(timeout);
    callerSignal?.removeEventListener("abort", abortForCaller);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  // A browser fetch has no deadline by default. Abort a request that stalls so callers such as
  // the initial settings load can use their existing retry/error path instead of waiting forever.
  const response = await request(path, { signal }, GET_TIMEOUT_MS);
  if (!response.ok) {
    throw new Error(`GET ${path} failed (HTTP ${response.status})`);
  }
  return (await response.json()) as T;
}

export type AuthState = {
  user: CurrentUser | null;
  emailSignInEnabled: boolean;
};

export function fetchAuthState(): Promise<AuthState> {
  return getJson<AuthState>("/auth/me");
}

export function googleSignInUrl(rememberDevice = false): string {
  return url(`/auth/google/login?remember_device=${rememberDevice}`);
}

export function requestCommitteeMagicLink(email: string, rememberDevice: boolean): Promise<Response> {
  return request("/auth/magic-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, rememberDevice }),
  });
}

export function inspectCommitteeMagicLink(token: string): Promise<Response> {
  return request("/auth/magic-link/inspect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export function consumeCommitteeMagicLink(token: string, switchCurrent = false): Promise<Response> {
  return request("/auth/magic-link/consume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, switchCurrent }),
  });
}

export function regenerateCommitteeMagicLink(token: string): Promise<Response> {
  return request("/auth/magic-link/regenerate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export function logout(): Promise<Response> {
  return request("/auth/logout", { method: "POST" });
}

export const fetchSettings = () => getJson<SettingsResponse>("/settings");

// --- Openings (admin only) --------------------------------------------------

export const fetchOpenings = () =>
  getJson<{ openings: Opening[] }>("/openings").then((payload) => payload.openings);

export function createOpening(opening: OpeningWrite): Promise<Response> {
  return request("/openings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opening),
  });
}

export function updateOpening(id: number, opening: OpeningWrite): Promise<Response> {
  return request(`/openings/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opening),
  });
}

export const publishOpening = (id: number) =>
  request(`/openings/${id}/publish`, { method: "POST" });

export function exchangeSheetCode(code: string): Promise<Response> {
  return request("/settings/exchange-sheet-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}

// --- Access allowlist (admin only) -----------------------------------------

export const fetchAllowlist = () =>
  getJson<{ entries: AllowlistEntry[] }>("/allowlist").then((p) => p.entries);

export const fetchDeniedSignInAttempts = () =>
  getJson<{ attempts: DeniedSignInAttempt[] }>("/allowlist/denied-attempts").then((p) => p.attempts);

export function upsertAllowlistEntry(email: string, role: "admin" | "member"): Promise<Response> {
  return request("/allowlist", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, role }),
  });
}

export function removeAllowlistEntry(email: string): Promise<Response> {
  return request(`/allowlist/${encodeURIComponent(email)}`, {
    method: "DELETE",
  });
}

// --- Feedback (submit: any member; read/resolve: admin only) ----------------

export function submitFeedback(payload: {
  body: string;
  route: string | null;
  activeTab: string | null;
  analysisId: number | null;
  applicantId: number | null;
}): Promise<Response> {
  return request("/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export const fetchFeedback = (includeResolved: boolean) =>
  getJson<{ items: FeedbackItem[] }>(
    `/feedback${includeResolved ? "?includeResolved=true" : ""}`,
  ).then((p) => p.items);

export const resolveFeedback = (id: number) =>
  request(`/feedback/${id}/resolve`, { method: "POST" });

export const reopenFeedback = (id: number) =>
  request(`/feedback/${id}/reopen`, { method: "POST" });

export function saveSettings(draft: AppSettings): Promise<Response> {
  return request("/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
}

// --- Eligibility rules (per member) ----------------------------------------
// The numeric screening rules each member tunes for themselves. A member reads the
// shared committee default until they save their own (see EligibilityRulesResponse).

export const fetchEligibilityRules = () =>
  getJson<EligibilityRulesResponse>("/eligibility-rules");

export const fetchEligibilityCheckCatalog = () =>
  getJson<EligibilityCheckCatalog>("/eligibility-rules/catalog");

export function saveEligibilityRules(rules: EligibilityRules): Promise<Response> {
  return request("/eligibility-rules", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rules),
  });
}

// Remove the member override and return the committee defaults now in effect.
export function resetEligibilityRules(): Promise<Response> {
  return request("/eligibility-rules", { method: "DELETE" });
}

// The shared baseline a member follows until they save an override.
export const fetchCommitteeDefaultRules = () =>
  getJson<EligibilityRules>("/eligibility-rules/committee-default");

// Editing the committee default does not rewrite member override rows.
export function saveCommitteeDefaultRules(rules: EligibilityRules): Promise<Response> {
  return request("/eligibility-rules/committee-default", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rules),
  });
}

export const fetchDashboard = () =>
  getJson<{ counts: DashboardCounts; workflow: WorkflowState; coverage: Coverage }>("/dashboard");

// The whole pool, unpaginated — the client derives filtering/sorting/facets from it.
export type ApplicationsResponse = {
  applications: ApplicationSummary[];
  openings: CommitteeOpening[];
};

export function fetchApplications(): Promise<ApplicationsResponse> {
  return getJson<ApplicationsResponse>("/applications");
}

export function fetchApplication(id: number): Promise<ApplicationDetail> {
  return getJson<{ application: ApplicationDetail }>(`/applications/${id}`).then((p) => p.application);
}

export function syncApplications(): Promise<Response> {
  return retrySyncRequest();
}

async function retrySyncRequest(): Promise<Response> {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await syncRequest();
      if (!isRetryableSyncResponse(response) || attempt === 1) return response;
    } catch (error) {
      if (attempt === 1) throw error;
    }
    await new Promise((resolve) => window.setTimeout(resolve, SYNC_RETRY_DELAY_MS));
  }

  throw new Error("Sync retry loop exhausted without returning a response.");
}

async function syncRequest(): Promise<Response> {
  // Unlike GETs, this request may spend time reading the source sheet. It still needs a
  // finite deadline: browser fetch otherwise leaves the Sync dialog running forever when
  // the production edge or an upstream dependency is unavailable. The import is idempotent,
  // so retrySyncRequest can safely retry a timed-out attempt once.
  return request("/sync/applications", { method: "POST" });
}

function isRetryableSyncResponse(response: Response): boolean {
  // Import upserts applications and leaves byte-identical rows untouched, so retrying after a
  // lost response is safe. Do not retry configuration or permission responses: the member
  // needs the error message those carry.
  return response.status === 408 || response.status === 429 || response.status >= 500;
}

// Save the sheet the admin picked in the Google Picker as the linked source (and designate
// them the reader). Returns the updated SettingsResponse on success. The drive.file grant +
// token exchange happen in googlePicker.ts (GIS code model) before this is called.
export function linkSheet(fileId: string): Promise<Response> {
  return request("/settings/link-sheet", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fileId }),
  });
}

export const fetchRankingCurrent = () => getJson<CurrentRunResponse | null>("/ranking/current");

// The current run's carry-forward audit, or null when none is stored.
export const fetchMatchAudit = () => getJson<MatchAuditResponse | null>("/ranking/current/match-audit");

// The current run's decomposition audit — how the K fan-out discovery reports were
// settled into one set (settled axes + merge reasoning + D9 folded-request trail).
// Null when no decomposition audit is stored.
export const fetchDecomposeAudit = () =>
  getJson<DecomposeAuditResponse | null>("/ranking/current/decompose-audit");

export const fetchConsolidateAudit = () =>
  getJson<ConsolidateAuditResponse | null>("/ranking/current/consolidate-audit");

// The current run's fan-out audit — each of the K parallel discoverers' dimensions +
// reasoning. Null when no fan-out audit is stored.
export const fetchFanOutAudit = () =>
  getJson<FanOutAuditResponse | null>("/ranking/current/fan-out-audit");

// Aggregated AI spend, grouped by run.
export const fetchCostReport = () => getJson<CostReport>("/observability/cost");

// The most recent Screen and Rank runs, each with fresh spend + cache savings.
export const fetchLastRuns = () => getJson<LastRunsReport>("/observability/last-runs");

// Operational trends across all runs: cost, tokens, latency, cache use, and failures.
export const fetchMetrics = () => getJson<MetricsReport>("/observability/metrics");

export const fetchScreeningEstimate = (signal?: AbortSignal) =>
  getJson<ScreeningEstimateResponse>("/screening/run/estimate", signal);
// Streaming runs carry heartbeats for their multi-minute lifetimes. Bound only the time to
// receive the Response; fetch resolves at that point, so this deadline never aborts a healthy
// active stream.
function streamRequest(path: string): Promise<Response> {
  return request(path, { method: "POST" });
}

export const runScreening = () => streamRequest("/screening/run");

export const fetchRankEstimate = (signal?: AbortSignal) =>
  getJson<RankEstimateResponse>("/ranking/run/estimate", signal);
export const runRank = () => streamRequest("/ranking/run");
export const fetchScoreCurrentEstimate = (signal?: AbortSignal) =>
  getJson<ScoreCurrentEstimateResponse>("/ranking/score-current/estimate", signal);
export const scoreCurrent = () => streamRequest("/ranking/score-current");

export const fetchRanking = () => getJson<RankingResponse>("/ranking");

export const fetchTiers = () => getJson<{ tiers: Tier[] }>("/ranking/tiers");

// analysisId is the analysis the client is viewing; the server rejects a save against a
// superseded one (409 stale_analysis) so a member's edit never lands on the wrong board.
export function saveTiers(
  analysisId: number,
  next: Tier[],
  acknowledgedKeys: string[],
  acknowledgedRequestedKeys: string[] = [],
): Promise<Response> {
  return request("/ranking/tiers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysisId, tiers: next, acknowledgedKeys, acknowledgedRequestedKeys }),
  });
}

// Persist pending free-text proposals for the current analysis. The next Rank reads these,
// so they take effect on its discovery pass. (Keeping an existing axis across re-runs is
// tier placement — see saveTiers — not a seed.) analysisId guards against a stale save.
export function saveSeeds(
  analysisId: number,
  seeds: { proposedDimensions?: string[] },
): Promise<Response> {
  return request("/ranking/seeds", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysisId, ...seeds }),
  });
}

export function overrideStatus(id: number, status: string): Promise<Response> {
  return request(`/applications/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

export function clearStatusOverride(id: number): Promise<Response> {
  return request(`/applications/${id}/status`, { method: "DELETE" });
}

export function savePrivateNote(id: number, note: string): Promise<Response> {
  return request(`/applications/${id}/note`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
}

// Toggle the current member's star on an applicant. PUT adds, DELETE removes —
// the row's existence is the state, so both are idempotent.
export function setStar(id: number, starred: boolean): Promise<Response> {
  return request(`/applications/${id}/star`, {
    method: starred ? "PUT" : "DELETE",
  });
}

// --- Evals tab -------------------------------------------------------------

// The runnable evals + their spend estimates (free; no model calls).
export const fetchEvalCatalog = () => getJson<{ evals: EvalDescriptor[] }>("/evals/catalog");

// Deterministic invariants over the baseline fixture (free).
export const fetchEvalInvariants = () => getJson<InvariantsResult>("/evals/invariants");

// Re-record the invariant baseline fixture from the current Rank (writes the committed
// rank_baseline.json — commit to git afterward). Returns the fresh invariants.
export function rebaselineEval(): Promise<Response> {
  return request("/evals/baseline", { method: "POST" });
}

// The eval's cases, straight from its committed JSON fixture (free).
export const fetchEvalCases = (evalKey: string) =>
  getJson<{ cases: Record<string, unknown>[] }>(`/evals/cases/${evalKey}`);

// The per-pass judge_background briefs (what each pass does) the Judge tab lists + edits,
// with each pass's golden case count. Free (reads the committed golden files).
export const fetchJudgeBackgrounds = () =>
  getJson<{ backgrounds: JudgeBackground[] }>("/evals/judge-backgrounds");

// Write one pass's judge_background to its golden file (operator commits deliberately).
export function saveJudgeBackground(passName: string, background: string): Promise<Response> {
  return request(`/evals/judge-backgrounds/${passName}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ background }),
  });
}

// The most recent persisted run among `keys` (comma-joined), to restore a tab on remount.
// Result JSON only (no thinking narration); identifies prompt and model drift separately.
export const fetchLastEvalRun = (keys: string[]) =>
  getJson<{ runs: LastEvalRun[] }>(`/evals/last-run?keys=${encodeURIComponent(keys.join(","))}`);

// Upsert one case (by its `key`) into the eval's fixture FILE. Validated server-side;
// the operator commits the changed file to git deliberately.
export function saveEvalCase(evalKey: string, evalCase: unknown): Promise<Response> {
  return request(`/evals/cases/${evalKey}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case: evalCase }),
  });
}

// Start a streaming eval run. Returns the raw Response so the caller reads its NDJSON
// body via streamNdjson. Spends model $. `caseKey` runs just that one case (per-row run);
// `k` sets stability repeats.
//
// Each pass is ONE route (POST /evals/{pass}); the internal `<pass>_stability` key selects
// the K-repeat mode via `?mode=stability`. The judge's stability variant is `stability`
// (its base pass is `judge`), matching the persisted eval keys.
export function runEval(
  key: EvalRunMode,
  opts?: { k?: number; caseKey?: string },
): Promise<Response> {
  const stabilityMode = key === "stability" || key.endsWith("_stability");
  // The base pass owns the route; the judge's stability variant ("stability") maps to /judge.
  const basePass = key === "stability" ? "judge" : key.replace(/_stability$/, "");
  const params = new URLSearchParams();
  if (stabilityMode) params.set("mode", "stability");
  if (stabilityMode && opts?.k) params.set("k", String(opts.k));
  if (opts?.caseKey) params.set("case", opts.caseKey);
  const q = params.toString() ? `?${params}` : "";
  return streamRequest(`/evals/${basePass}${q}`);
}

// Read an NDJSON stream, invoking `onEvent` for each parsed line. Used by the
// screening and Rank runs, which stream progress then a summary.
export async function streamNdjson<TEvent extends ScreeningStreamEvent | RankingStreamEvent | EvalStreamEvent>(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: TEvent) => void,
): Promise<void> {
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
      onEvent(JSON.parse(line) as TEvent);
    }
  }
}
