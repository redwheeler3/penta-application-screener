import { act, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { deferred, renderCommitteeHook as renderHook } from "../../testSupport";
import type { EvalCasesResponse, EvalHistory, EvalRunOption, LastEvalRun, ScoringEvalCaseResult } from "../../types";
import { useEvalRunner } from "./useEvalRunner";

const api = vi.hoisted(() => ({ fetchEvalCases: vi.fn(), fetchLastEvalRun: vi.fn(), runEval: vi.fn() }));
vi.mock("../../api/evals", async (original) => ({ ...await original<typeof import("../../api/evals")>(), createApi: () => api }));

const config = { modelId: "synthetic", promptVersion: "v1", reasoningEffort: "", caseFingerprints: { a: "a1", b: "b1" } };
const mode: EvalRunOption = { evalKey: "scoring", label: "Scoring", rowLabel: "Run", repetitions: 1 };
const scored = (key: string, score: number): ScoringEvalCaseResult => ({ key, score, inputFingerprint: `${key}1`,
  passed: score >= 0.5, confidence: "high", evidence: "Synthetic", failures: [] });
function saved(runId: number, cases: ScoringEvalCaseResult[], experimentId = "same", caseRunIds = Object.fromEntries(cases.map((c) => [c.key, runId]))): LastEvalRun {
  return { runId, evalKey: "scoring", ranAt: "2026-10-01T12:00:00Z", modelId: config.modelId,
    promptVersion: config.promptVersion, reasoningEffort: "", supportsReasoningEffort: false, caseRunIds,
    result: { experimentId, scoringModel: config.modelId, scoringPromptVersion: config.promptVersion, cases } };
}
const history = (runs: LastEvalRun[] = []): EvalHistory => ({ runs, current: { scoring: config } });
function completion(score = 0.8, storedRunId: number | null = null, experimentId = "same", key = "a") {
  return new Response(JSON.stringify({ type: "summary", eval: "scoring", storedRunId,
    result: { experimentId, scoringModel: config.modelId, scoringPromptVersion: config.promptVersion, cases: [scored(key, score)] } }));
}
beforeEach(() => {
  vi.resetAllMocks();
  api.fetchEvalCases.mockResolvedValue({ cases: [{ key: "a" }, { key: "b" }], caseFingerprints: config.caseFingerprints });
  api.fetchLastEvalRun.mockResolvedValue(history());
  api.runEval.mockImplementation(() => Promise.resolve(completion()));
});

it.each([null, 3])("keeps delivered output through repeated older history and fixture refreshes (receipt %s)", async (runId) => {
  api.fetchLastEvalRun.mockResolvedValue(history([saved(2, [scored("a", 0.1), scored("b", 0.9)])]));
  api.runEval.mockResolvedValue(completion(0.8, runId));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await waitFor(() => expect(result.current.caseResults.a).toBeDefined());
  await act(() => result.current.runMode(mode, "a"));
  await act(() => result.current.refreshHistory());
  await act(async () => result.current.setCases({ cases: [{ key: "a" }, { key: "b" }], caseFingerprints: config.caseFingerprints }));
  expect(result.current.caseResults.a.scoring).toMatchObject({ result: { score: 0.8 } });
  expect(result.current.caseResults.b.scoring).toMatchObject({ result: { score: 0.9 } });
  expect(result.current.restored.scoring).toBeUndefined();
});

it.each([null, 3])("does not revive a known-stale other case when a partial run refresh fails (receipt %s)", async (runId) => {
  const known = history([saved(1, [scored("a", 0.8), scored("b", 0.9)])]);
  known.current.scoring = { ...config, caseFingerprints: { a: "a1", b: "b2" } };
  api.fetchLastEvalRun.mockResolvedValueOnce(known).mockRejectedValue(new Error("Offline"));
  api.runEval.mockResolvedValue(completion(0.8, runId));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await waitFor(() => expect(result.current.caseResults.a).toBeDefined());
  expect(result.current.caseResults.b?.scoring).toBeUndefined();
  await act(() => result.current.runMode(mode, "a"));
  expect(result.current.caseResults.a?.scoring).toMatchObject({ result: { score: 0.8 } });
  expect(result.current.caseResults.b?.scoring).toBeUndefined();
  expect(result.current.currentConfigurations.scoring?.caseFingerprints.b).toBe("b2");
  api.fetchLastEvalRun.mockResolvedValue(known);
  await act(() => result.current.refreshHistory());
  expect(result.current.caseResults.b?.scoring).toBeUndefined();
});

it("uses each historical case's source run when a newer partial aggregate arrives", async () => {
  api.runEval.mockResolvedValue(completion(0.8, 3));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await act(() => result.current.runMode(mode, "a"));
  api.fetchLastEvalRun.mockResolvedValue(history([saved(4, [scored("a", 0.1), scored("b", 0.9)], "same", { a: 2, b: 4 })]));
  await act(() => result.current.refreshHistory());
  expect(result.current.caseResults.a.scoring).toMatchObject({ result: { score: 0.8 } });
  api.fetchLastEvalRun.mockResolvedValue(history([saved(5, [scored("a", 0.7), scored("b", 0.9)], "same", { a: 5, b: 4 })]));
  await act(() => result.current.refreshHistory());
  expect(result.current.caseResults.a.scoring).toMatchObject({ result: { score: 0.7 } });
  expect(result.current.restored.scoring.runId).toBe(5);
});

it.each(["labels", "prompt", "model", "reasoning"])("expires unrecorded output after %s changes with no stored history", async (change) => {
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await act(() => result.current.runMode(mode, "a"));
  const next = { ...config, ...(change === "labels" ? { caseFingerprints: { a: "a2", b: "b1" } }
    : change === "prompt" ? { promptVersion: "v2" } : change === "model" ? { modelId: "another" } : { reasoningEffort: "high" }) };
  api.fetchLastEvalRun.mockResolvedValue({ runs: [], current: { scoring: next } });
  await act(async () => result.current.setCases({ cases: [{ key: "a" }], caseFingerprints: config.caseFingerprints }));
  expect(result.current.caseResults.a?.scoring).toBeUndefined();
  api.fetchLastEvalRun.mockResolvedValue(history());
  await act(() => result.current.refreshHistory());
  expect(result.current.caseResults.a?.scoring).toBeUndefined();
});

it("keeps compatible partial receipts and clears them for a new experiment", async () => {
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await act(() => result.current.runMode(mode, "a"));
  api.runEval.mockResolvedValue(completion(0.9, null, "same", "b"));
  await act(() => result.current.runMode(mode, "b"));
  expect(result.current.caseResults.a.scoring).toBeDefined();
  expect(result.current.caseResults.b.scoring).toBeDefined();
  api.runEval.mockResolvedValue(completion(0.7, null, "another", "a"));
  await act(() => result.current.runMode(mode, "a"));
  expect(result.current.caseResults.a.scoring).toMatchObject({ result: { score: 0.7 } });
  expect(result.current.caseResults.b?.scoring).toBeUndefined();
});

it.each(["label", "input", "editorial"])("applies %s edit evidence before a failed history refresh", async (change) => {
  api.fetchLastEvalRun.mockResolvedValue(history([saved(1, [scored("a", 0.8), scored("b", 0.9)])]));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await waitFor(() => expect(result.current.caseResults.a).toBeDefined());
  api.fetchLastEvalRun.mockRejectedValue(new Error("Offline"));
  const fingerprint = change === "editorial" ? "a1" : "a2";
  await act(async () => result.current.setCases({ cases: [{ key: "a" }, { key: "b" }],
    caseFingerprints: { a: fingerprint, b: "b1" } }));
  expect(!!result.current.caseResults.a?.scoring).toBe(change === "editorial");
  expect(result.current.caseResults.b?.scoring).toBeDefined();
  expect(result.current.retainedResults.a?.scoring).toMatchObject({ result: { score: 0.8 } });
});

it.each(["receipt-first", "edit-first"])("keeps an acknowledged label change ahead of a pending run (%s)", async (order) => {
  const request = deferred<Response>();
  api.fetchLastEvalRun.mockResolvedValueOnce(history([saved(1, [scored("a", 0.5)])]))
    .mockRejectedValue(new Error("Offline"));
  api.runEval.mockReturnValue(request.promise);
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await waitFor(() => expect(result.current.caseResults.a).toBeDefined());
  let running!: Promise<void>;
  act(() => { running = result.current.runMode(mode, "a"); });
  const edit = () => result.current.setCases({ cases: [{ key: "a" }], caseFingerprints: { a: "a2" } });
  await act(async () => {
    if (order === "edit-first") edit();
    request.resolve(completion());
    await running;
    if (order === "receipt-first") edit();
  });
  expect(result.current.caseResults.a?.scoring).toBeUndefined();
  expect(result.current.currentConfigurations.scoring?.caseFingerprints.a).toBe("a2");
});

it("keeps other modes when a receipt completes and disposes unrecorded output on remount", async () => {
  const stable: LastEvalRun = { ...saved(1, []), evalKey: "scoring_stability", caseRunIds: { a: 1 }, result: { cases: [
    { key: "a", inputFingerprint: "a1", marker: "[stable]", agreement: 1, tally: { pass: 5 }, runs: [], scoreMin: 0.8, scoreMax: 0.8 },
  ] } };
  api.fetchLastEvalRun.mockResolvedValue({ runs: [stable], current: { scoring: config, scoring_stability: config } });
  const options = { caseEvalKey: "scoring" as const, runKeys: ["scoring", "scoring_stability"] as const };
  const mount = () => renderHook(() => useEvalRunner({ ...options, runKeys: [...options.runKeys] }));
  const first = mount();
  await waitFor(() => expect(first.result.current.caseResults.a?.scoring_stability).toBeDefined());
  await act(() => first.result.current.runMode(mode, "a"));
  expect(first.result.current.caseResults.a.scoring_stability).toBeDefined();
  first.unmount();
  const second = mount();
  await waitFor(() => expect(second.result.current.caseResults.a?.scoring_stability).toBeDefined());
  expect(second.result.current.caseResults.a.scoring).toBeUndefined();
});

it("rejects initial history arriving after a new run and preserves output when the refresh fails", async () => {
  const pending = deferred<EvalHistory>();
  api.fetchLastEvalRun.mockReturnValueOnce(pending.promise).mockRejectedValue(new Error("Offline"));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await act(() => result.current.runMode(mode, "a"));
  await act(async () => pending.resolve(history([saved(1, [scored("a", 0.1)])])));
  expect(result.current.retainedResults.a.scoring).toMatchObject({ result: { score: 0.8 } });
  expect(result.current.caseResults.a?.scoring).toBeUndefined();
  api.fetchLastEvalRun.mockResolvedValue(history());
  await act(() => result.current.refreshHistory());
  expect(result.current.caseResults.a?.scoring).toMatchObject({ result: { score: 0.8 } });
  expect(api.runEval).toHaveBeenCalledOnce();
});

it.each(["history-first", "cases-first"])("does not certify results against different visible inputs (%s)", async (order) => {
  const input = deferred<EvalCasesResponse>();
  const stored = deferred<EvalHistory>();
  api.fetchEvalCases.mockReturnValue(input.promise);
  api.fetchLastEvalRun.mockReturnValue(stored.promise);
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  const casesReady = () => input.resolve({ cases: [{ key: "a" }], caseFingerprints: { a: "a2" } });
  const historyReady = () => stored.resolve(history([saved(1, [scored("a", 0.8)])]));
  await act(async () => { if (order === "history-first") historyReady(); else casesReady(); });
  expect(result.current.caseResults.a?.scoring).toBeUndefined();
  await act(async () => { if (order === "history-first") casesReady(); else historyReady(); });
  expect(result.current.caseResults.a?.scoring).toBeUndefined();
  expect(result.current.retainedResults.a?.scoring).toMatchObject({ result: { score: 0.8 } });
});

it("discards old-family reads and cancels work when its view closes", async () => {
  const pending = deferred<EvalHistory>();
  api.fetchLastEvalRun.mockReturnValueOnce(pending.promise);
  const { result, rerender, unmount } = renderHook(({ matching }) => useEvalRunner({ caseEvalKey: matching ? "matching" : "scoring",
    runKeys: matching ? ["matching"] : ["scoring"] }), { initialProps: { matching: false } });
  rerender({ matching: true });
  await act(async () => pending.resolve(history([saved(1, [scored("a", 0.1)])])));
  expect(result.current.caseResults).toEqual({});
  const response = deferred<Response>();
  api.runEval.mockReturnValue(response.promise);
  let running!: Promise<void>;
  act(() => { running = result.current.runMode({ ...mode, evalKey: "matching" }); });
  const signal = api.runEval.mock.calls[0][1].signal;
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => { response.resolve(new Response(null, { status: 503 })); await running; });
});

it.each(["interrupted", "fatal"])("reports a %s stream without discarding previous output", async (failure) => {
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await act(() => result.current.runMode(mode, "a"));
  api.runEval.mockResolvedValue(new Response(failure === "fatal" ? JSON.stringify({ type: "error", message: "Synthetic failure" }) : ""));
  await act(() => result.current.runMode(mode, "a"));
  expect(result.current.run.error).toContain(failure === "fatal" ? "Synthetic failure" : "interrupted");
  expect(result.current.caseResults.a.scoring).toMatchObject({ result: { score: 0.8 } });
});

it("distinguishes a failed fixture read from an empty corpus and keeps accepted edits ahead of late reads", async () => {
  api.fetchEvalCases.mockRejectedValueOnce(new Error("Offline"));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await waitFor(() => expect(result.current.casesLoadState).toBe("error"));
  expect(result.current.cases).toBeNull();
  const pending = deferred<EvalCasesResponse>();
  api.fetchEvalCases.mockReturnValueOnce(pending.promise);
  let retry!: Promise<void>;
  act(() => { retry = result.current.retryCases(); });
  act(() => result.current.setCases({ cases: [{ key: "saved" }], caseFingerprints: {} }));
  await act(async () => { pending.resolve({ cases: [], caseFingerprints: {} }); await retry; });
  expect(result.current.cases).toEqual([{ key: "saved" }]);
  expect(result.current.casesLoadState).toBe("ready");
});


it("retains unrecorded incomplete stability evidence through failed history refreshes", async () => {
  api.fetchLastEvalRun.mockResolvedValueOnce({ runs: [], current: { scoring_stability: config } })
    .mockRejectedValue(new Error("Offline"));
  const evidence = { key: "a", inputFingerprint: "a1", marker: "[incomplete]", agreement: null,
    scoreMin: 0.8, scoreMax: 0.8, tally: { pass: 1, error: 1 }, runs: [
      { outcome: "pass", detail: "Paid output" }, { outcome: "error", detail: "Timeout", error: "Timeout" },
    ] };
  api.runEval.mockResolvedValue(new Response(JSON.stringify({ type: "summary", eval: "scoring_stability", storedRunId: null,
    result: { scoringModel: config.modelId, scoringPromptVersion: config.promptVersion, cases: [evidence] } })));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring_stability"] }));
  await waitFor(() => expect(result.current.currentConfigurations.scoring_stability).toBeDefined());
  await act(() => result.current.runMode({ ...mode, evalKey: "scoring_stability", repetitions: 2 }, "a"));
  await act(() => result.current.refreshHistory());
  expect(result.current.retainedResults.a.scoring_stability?.result).toEqual(evidence);
  expect(api.runEval).toHaveBeenCalledOnce();
});
