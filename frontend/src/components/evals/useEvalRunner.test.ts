import { act, waitFor } from "@testing-library/react";
import { renderCommitteeHook as renderHook, deferred } from "../../testSupport";
import { beforeEach, expect, it, vi } from "vitest";
import type { LastEvalRun, ScoringEvalCaseResult } from "../../types";
import { useEvalRunner } from "./useEvalRunner";

const api = vi.hoisted(() => ({
  fetchEvalCases: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchEvalCases"]>(),
  fetchLastEvalRun: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["fetchLastEvalRun"]>(),
  runEval: vi.fn<ReturnType<typeof import("../../api/evals").createApi>["runEval"]>(),
}));

vi.mock("../../api/evals", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/evals")>(),
  createApi: () => api,
}));

const history = {
  ranAt: "2026-10-01T12:00:00Z", promptVersion: "v1", currentPromptVersion: "v1",
  modelId: "test-model", currentModelId: "test-model", supportsReasoningEffort: false,
  reasoningEffort: "", currentReasoningEffort: "", promptStale: false, modelStale: false,
  reasoningStale: false,
};
const scored = (key: string, score: number): ScoringEvalCaseResult => ({
  key, passed: true, score, confidence: "high", evidence: "Synthetic evidence.", failures: [],
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchEvalCases).mockResolvedValue({ cases: [{ key: "a" }, { key: "b" }] });
  vi.mocked(api.fetchLastEvalRun).mockResolvedValue({ runs: [] });
});

it("cancels an eval owned by a workspace that has closed", async () => {
  const pending = deferred<Response>();
  vi.mocked(api.runEval).mockReturnValue(pending.promise);
  const { result, unmount } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  let running!: Promise<void>;
  act(() => { running = result.current.runMode({ evalKey: "scoring", label: "Scoring", rowLabel: "Run", calls: 1 }); });
  const signal = vi.mocked(api.runEval).mock.calls[0][1]!.signal!;
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => { pending.resolve(new Response(null, { status: 503 })); await running; });
});

it("keeps newly completed results when initial history arrives late", async () => {
  const pending = deferred<{ runs: LastEvalRun[] }>();
  vi.mocked(api.fetchLastEvalRun).mockReturnValueOnce(pending.promise);
  vi.mocked(api.runEval).mockResolvedValue(new Response(`${JSON.stringify({
    type: "summary", eval: "scoring", savedPath: null, result: { cases: [scored("a", 0.8)] },
  })}\n`));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await act(async () => {
    await result.current.runMode({ evalKey: "scoring", label: "Scoring", rowLabel: "Run", calls: 1 });
  });
  await act(async () => pending.resolve({ runs: [
    { ...history, evalKey: "scoring", result: { cases: [scored("a", 0.2)] } },
  ] }));
  expect(result.current.caseResults.a?.scoring).toMatchObject({ result: { score: 0.8 } });
  expect(result.current.restored.scoring).toBeUndefined();
});

it("discards history from an eval family the member has left", async () => {
  const pending = deferred<{ runs: LastEvalRun[] }>();
  vi.mocked(api.fetchLastEvalRun).mockReturnValueOnce(pending.promise);
  const { result, rerender } = renderHook(({ matching }) => useEvalRunner({
    caseEvalKey: matching ? "matching" : "scoring", runKeys: matching ? ["matching"] : ["scoring"],
  }), { initialProps: { matching: false } });
  rerender({ matching: true });
  await act(async () => pending.resolve({ runs: [
    { ...history, evalKey: "scoring", result: { cases: [scored("a", 0.2)] } },
  ] }));
  expect(result.current.caseResults).toEqual({});
  expect(result.current.restored).toEqual({});
});

it("restores each mode and replaces only that mode's results after a whole-set run", async () => {
  const runs: LastEvalRun[] = [
    { ...history, evalKey: "scoring", result: { cases: [scored("a", 0.2), scored("b", 0.2)] } },
    { ...history, evalKey: "scoring_stability", result: { cases: ["a", "b"].map((key) => ({
      key, marker: "[stable]", agreement: 1, tally: { pass: 5 }, runs: [], scoreMin: 0.2, scoreMax: 0.2,
    })) } },
  ];
  vi.mocked(api.fetchLastEvalRun).mockResolvedValueOnce({ runs });
  vi.mocked(api.runEval).mockResolvedValue(new Response(`${JSON.stringify({
    type: "summary", eval: "scoring", savedPath: null, result: { cases: [scored("a", 0.8)] },
  })}\n`));
  const { result } = renderHook(() => useEvalRunner({
    caseEvalKey: "scoring", runKeys: ["scoring", "scoring_stability"],
  }));
  await waitFor(() => expect(result.current.caseResults.a?.scoring).toMatchObject({
    mode: "scoring", result: { score: 0.2 },
  }));
  expect(result.current.caseResults.b?.scoring_stability).toMatchObject({
    mode: "scoring_stability", result: { marker: "[stable]" },
  });

  await act(async () => {
    await result.current.runMode({ evalKey: "scoring", label: "Scoring", rowLabel: "Run", calls: 2 });
  });
  expect(result.current.caseResults.a?.scoring).toMatchObject({
    mode: "scoring", result: { score: 0.8 },
  });
  expect(result.current.caseResults.b?.scoring).toBeUndefined();
  expect(result.current.caseResults.b?.scoring_stability).toMatchObject({
    mode: "scoring_stability", result: { marker: "[stable]" },
  });
  expect(result.current.run).toMatchObject({ running: false, error: null });
});

it("reports incomplete eval progress and preserves the displayed results", async () => {
  vi.mocked(api.fetchLastEvalRun).mockResolvedValueOnce({ runs: [
    { ...history, evalKey: "scoring", result: { cases: [scored("a", 0.2)] } },
  ] });
  vi.mocked(api.runEval).mockResolvedValue(new Response(`${JSON.stringify({
    type: "progress", phase: "scoring", processed: 1, total: 2,
  })}\n`));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await waitFor(() => expect(result.current.caseResults.a?.scoring).toMatchObject({ result: { score: 0.2 } }));
  await act(() => result.current.runMode({ evalKey: "scoring", label: "Scoring", rowLabel: "Run", calls: 2 }));
  expect(result.current.run.running).toBe(false);
  expect(result.current.run.error).toContain("interrupted before completion was confirmed");
  expect(result.current.caseResults.a?.scoring).toMatchObject({ result: { score: 0.2 } });
});

it("accepts a final eval summary without a newline", async () => {
  vi.mocked(api.runEval).mockResolvedValue(new Response(JSON.stringify({
    type: "summary", eval: "scoring", savedPath: null, result: { cases: [scored("a", 0.8)] },
  })));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await act(() => result.current.runMode({ evalKey: "scoring", label: "Scoring", rowLabel: "Run", calls: 1 }));
  expect(result.current.caseResults.a?.scoring).toMatchObject({ result: { score: 0.8 } });
  expect(result.current.run).toMatchObject({ running: false, error: null });
});

it("keeps the server's fatal eval error as the outcome", async () => {
  vi.mocked(api.runEval).mockResolvedValue(new Response(JSON.stringify({
    type: "error", phase: "scoring", message: "Synthetic model failure.",
  })));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await act(() => result.current.runMode({ evalKey: "scoring", label: "Scoring", rowLabel: "Run", calls: 1 }));
  expect(result.current.run).toMatchObject({ running: false, error: "Synthetic model failure." });
});

it("keeps accepted case data when the initial fixture read arrives late", async () => {
  const pending = deferred<{ cases: Record<string, unknown>[] }>();
  vi.mocked(api.fetchEvalCases).mockReturnValueOnce(pending.promise);
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: [] }));
  act(() => result.current.setCases([{ key: "saved-case" }]));
  await act(async () => { pending.resolve({ cases: [{ key: "old-case" }] }); });
  expect(result.current.cases).toEqual([{ key: "saved-case" }]);
});


it("clears other current dots when a partial run changes experiment", async () => {
  api.fetchLastEvalRun.mockResolvedValueOnce({ runs: [
    { ...history, evalKey: "scoring", result: { experimentId: "old", cases: [scored("a", 0.2), scored("b", 0.2)] } },
  ] });
  api.runEval.mockResolvedValue(new Response(JSON.stringify({ type: "summary", eval: "scoring", savedPath: null,
    result: { experimentId: "new", cases: [scored("a", 0.8)] } })));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await waitFor(() => expect(result.current.caseResults.b?.scoring).toBeDefined());
  await act(() => result.current.runMode({ evalKey: "scoring", label: "Scoring", rowLabel: "Run", calls: 1 }, "a"));
  expect(result.current.caseResults.a?.scoring).toMatchObject({ result: { score: 0.8 } });
  expect(result.current.caseResults.b?.scoring).toBeUndefined();
});

it("keeps same-experiment partial coverage and expires changed labels on fixture save", async () => {
  const saved: LastEvalRun = { ...history, evalKey: "scoring", currentCaseFingerprints: { a: "a1", b: "b1" },
    result: { experimentId: "same", cases: [{ ...scored("a", 0.2), inputFingerprint: "a1" }, { ...scored("b", 0.2), inputFingerprint: "b1" }] } };
  api.fetchLastEvalRun.mockResolvedValueOnce({ runs: [saved] }).mockResolvedValueOnce({ runs: [saved] }).mockResolvedValue({ runs: [{ ...saved, corpusStale: true,
    currentCaseFingerprints: { a: "a2", b: "b1" } }] });
  api.runEval.mockResolvedValue(new Response(JSON.stringify({ type: "summary", eval: "scoring", savedPath: null,
    result: { experimentId: "same", cases: [{ ...scored("b", 0.8), inputFingerprint: "b1" }] } })));
  const { result } = renderHook(() => useEvalRunner({ caseEvalKey: "scoring", runKeys: ["scoring"] }));
  await waitFor(() => expect(result.current.caseResults.a?.scoring).toBeDefined());
  await act(() => result.current.runMode({ evalKey: "scoring", label: "Scoring", rowLabel: "Run", calls: 1 }, "b"));
  expect(result.current.caseResults.a?.scoring).toBeDefined();
  act(() => result.current.setCases([{ key: "a" }, { key: "b" }]));
  await waitFor(() => expect(result.current.caseResults.a?.scoring).toBeUndefined());
  expect(result.current.caseResults.b?.scoring).toBeDefined();
  expect(result.current.restored.scoring.corpusStale).toBe(true);
});
