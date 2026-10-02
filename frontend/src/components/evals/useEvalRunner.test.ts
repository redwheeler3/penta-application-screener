import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "../../api/evals";
import type { LastEvalRun, ScoringEvalCaseResult } from "../../types";
import { deferred } from "../../testSupport";
import { useEvalRunner } from "./useEvalRunner";

vi.mock("../../api/evals", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/evals")>(),
  fetchEvalCases: vi.fn(),
  fetchLastEvalRun: vi.fn(),
  runEval: vi.fn(),
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
