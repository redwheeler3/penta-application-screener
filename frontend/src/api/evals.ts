import { type ApiClient, publicClient } from "./client";
import type {
  EvalCaseOutcome,
  EvalDescriptor,
  EvalRunSummary,
  EvalRunMode,
  InvariantsResult,
  JudgeBackground,
  LastEvalRun,
} from "../types";

export function createApi(client: ApiClient) {
  const { getJson, request, streamRequest } = client;
  // --- Evals tab -------------------------------------------------------------

  // The runnable evals + their spend estimates (free; no model calls).
  const fetchEvalCatalog = () => getJson<{ evals: EvalDescriptor[] }>("/evals/catalog");

  // Deterministic invariants over the baseline fixture (free).
  const fetchEvalInvariants = () => getJson<InvariantsResult>("/evals/invariants");

  // Re-record the invariant baseline fixture from the current Rank (writes the committed
  // rank_baseline.json — commit to git afterward). Returns the fresh invariants.
  function rebaselineEval(): Promise<Response> {
    return request("/evals/baseline", { method: "POST" });
  }

  // The eval's cases, straight from its committed JSON fixture (free).
  const fetchEvalCases = (evalKey: string) =>
    getJson<{ cases: Record<string, unknown>[] }>(`/evals/cases/${evalKey}`);

  // The per-pass judge_background briefs (what each pass does) the Judge tab lists + edits,
  // with each pass's golden case count. Free (reads the committed golden files).
  const fetchJudgeBackgrounds = () =>
    getJson<{ backgrounds: JudgeBackground[] }>("/evals/judge-backgrounds");

  // Write one pass's judge_background to its golden file (operator commits deliberately).
  function saveJudgeBackground(passName: string, background: string): Promise<Response> {
    return request(`/evals/judge-backgrounds/${passName}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ background }),
    });
  }

  // The most recent persisted run among `keys` (comma-joined), to restore a tab on remount.
  // Result JSON only (no thinking narration); identifies prompt and model drift separately.
  const fetchLastEvalRun = (keys: EvalRunMode[]) =>
    getJson<{ runs: LastEvalRun[] }>(`/evals/last-run?keys=${encodeURIComponent(keys.join(","))}`);

  // Upsert one case (by its `key`) into the eval's fixture FILE. Validated server-side;
  // the operator commits the changed file to git deliberately.
  function saveEvalCase(evalKey: string, evalCase: unknown): Promise<Response> {
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
  function runEval(
    key: EvalRunMode,
    opts?: { k?: number; caseKey?: string; signal?: AbortSignal },
  ): Promise<Response> {
    const stabilityMode = key === "stability" || key.endsWith("_stability");
    // The base pass owns the route; the judge's stability variant ("stability") maps to /judge.
    const basePass = key === "stability" ? "judge" : key.replace(/_stability$/, "");
    const params = new URLSearchParams();
    if (stabilityMode) params.set("mode", "stability");
    if (stabilityMode && opts?.k) params.set("k", String(opts.k));
    if (opts?.caseKey) params.set("case", opts.caseKey);
    const q = params.toString() ? `?${params}` : "";
    return streamRequest(`/evals/${basePass}${q}`, opts?.signal);
  }

  /** Narrow the whole run before attaching its mode to individual case results. */
  function caseOutcomes(run: EvalRunSummary): EvalCaseOutcome[] {
    switch (run.eval) {
      case "scoring":
        return (run.result.cases ?? []).map((result) => ({ mode: run.eval, result }));
      case "scoring_stability":
        return (run.result.cases ?? []).map((result) => ({ mode: run.eval, result }));
      case "screening":
        return (run.result.cases ?? []).map((result) => ({ mode: run.eval, result }));
      case "judge":
        return (run.result.cases ?? []).map((result) => ({ mode: run.eval, result }));
      case "consolidation":
      case "matching":
      case "decomposition":
        return (run.result.cases ?? []).map((result) => ({ mode: run.eval, result }));
      default:
        return (run.result.cases ?? []).map((result) => ({ mode: run.eval, result }));
    }
  }

  /** Saved runs use evalKey; streamed summaries use eval. Keep the payload correlation
   * while adapting those wire names, without asserting an independently paired payload. */
  function savedRunSummary(run: LastEvalRun): EvalRunSummary {
    switch (run.evalKey) {
      case "scoring":
        return {
  eval: run.evalKey, result: run.result,
};
      case "scoring_stability":
        return {
  eval: run.evalKey, result: run.result,
};
      case "screening":
        return {
  eval: run.evalKey, result: run.result,
};
      case "screening_stability":
        return {
  eval: run.evalKey, result: run.result,
};
      case "judge":
        return {
  eval: run.evalKey, result: run.result,
};
      case "stability":
        return {
  eval: run.evalKey, result: run.result,
};
      case "consolidation":
        return {
  eval: run.evalKey, result: run.result,
};
      case "consolidation_stability":
        return {
  eval: run.evalKey, result: run.result,
};
      case "matching":
        return {
  eval: run.evalKey, result: run.result,
};
      case "matching_stability":
        return {
  eval: run.evalKey, result: run.result,
};
      case "decomposition":
        return {
  eval: run.evalKey, result: run.result,
};
      case "decomposition_stability":
        return {
  eval: run.evalKey, result: run.result,
};
    }
  }
  return {
    fetchEvalCatalog, fetchEvalInvariants, rebaselineEval, fetchEvalCases, fetchJudgeBackgrounds,
    saveJudgeBackground, fetchLastEvalRun, saveEvalCase, runEval, caseOutcomes, savedRunSummary,
  };
}

// Public/bootstrap callers and manual harnesses use the unbound client.
export const {
  fetchEvalCatalog, fetchEvalInvariants, rebaselineEval, fetchEvalCases, fetchJudgeBackgrounds,
  saveJudgeBackground, fetchLastEvalRun, saveEvalCase, runEval, caseOutcomes, savedRunSummary,
} = createApi(publicClient);
