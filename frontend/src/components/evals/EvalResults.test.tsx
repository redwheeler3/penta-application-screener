import { render, screen } from "@testing-library/react";
import { describe, expect, expectTypeOf, it } from "vitest";

import type { CategoricalEvalCaseResult, EvalCaseOutcome, EvalRunSummary, EvalStreamEvent, LastEvalRun } from "../../types";
import { EvalCaseResultView, EvalRunHistoryMarker } from "./EvalResults";
import { evalCaseStatus, runSummary } from "./evalResultPresentation";

const contested: CategoricalEvalCaseResult = {
  key: "boundary", passed: true, verdict: "keep", expected: "merge",
  contested: true, reason: "Both are defensible.", failures: [],
};

describe("eval result presentation", () => {
  it("derives history drift from the same independent metadata used by case results", () => {
    const run: LastEvalRun = { evalKey: "scoring", runId: 1, ranAt: "2026-10-01T12:00:00Z",
      promptVersion: "v1", modelId: "synthetic-old", reasoningEffort: "low", supportsReasoningEffort: true,
      caseRunIds: { a: 1 }, result: { cases: [{ key: "a", score: 0.8, passed: true,
        confidence: "high", evidence: "Synthetic", failures: [], inputFingerprint: "a1" }] } };
    render(<EvalRunHistoryMarker run={run} totalCases={1} current={{ promptVersion: "v2", modelId: "synthetic-new",
      reasoningEffort: "high", caseFingerprints: { a: "a2" } }} />);
    const marker = screen.getByText(/last run/);
    expect(marker).toHaveClass("stale");
    expect(marker).toHaveTextContent("prompt is now v2");
    expect(marker).toHaveTextContent("model is now synthetic-new");
    expect(marker).toHaveTextContent("reasoning is now high");
    expect(marker).toHaveTextContent("case inputs or labels changed");
  });
  it("renders a missing score without inventing zero or confidence", () => {
    render(<EvalCaseResultView outcome={{ mode: "scoring", result: {
      key: "missing", passed: false, score: null, confidence: "?", evidence: "",
      failures: ["model returned no score"],
    } }} />);
    expect(screen.getByText("No score returned")).toBeInTheDocument();
    expect(screen.getByText("model returned no score")).toBeInTheDocument();
    expect(screen.queryByText(/confidence/)).toBeNull();
  });

  it("renders the live and saved all-missing stability shape without crashing", () => {
    const result = { key: "missing", marker: "[incomplete]", agreement: null, tally: { error: 2 },
      scoreMin: null, scoreMax: null, runs: [{ outcome: "fail", detail: "model returned no score" }] };
    const saved = JSON.parse(JSON.stringify(result)) as typeof result;
    render(<EvalCaseResultView outcome={{ mode: "scoring_stability", result: saved }} />);
    expect(screen.getByText(/No scores returned/)).toBeInTheDocument();
    expect(screen.getByText("incomplete")).toBeInTheDocument();
    expect(screen.queryByText(/0%|100%/)).toBeNull();
    expect(screen.getByText("model returned no score")).toBeInTheDocument();
  });
  it("rejects mismatched modes and payloads in both live and saved run contracts", () => {
    type CategoricalPayload = { cases: CategoricalEvalCaseResult[] };
    expectTypeOf<{ eval: "matching"; result: CategoricalPayload }>().toMatchTypeOf<EvalRunSummary>();
    expectTypeOf<{
      type: "summary"; eval: "scoring"; savedPath: null; result: CategoricalPayload;
    }>().not.toMatchTypeOf<EvalStreamEvent>();
    expectTypeOf<
      Omit<LastEvalRun, "evalKey" | "result"> & { evalKey: "scoring"; result: CategoricalPayload }
    >().not.toMatchTypeOf<LastEvalRun>();
  });

  it("keeps contested agreement green and contested divergence amber", () => {
    expect(evalCaseStatus({ mode: "matching", result: { ...contested, verdict: "merge" } })).toBe("ok");
    const outcome: EvalCaseOutcome = { mode: "matching", result: contested };
    render(<EvalCaseResultView outcome={outcome} />);
    expect(screen.getByText("contested").closest(".eval-case-result")).toHaveClass("contested");
    expect(runSummary({ eval: "matching", result: { cases: [contested] } }, 3)).toBe("1/3 passed");
  });

  it("uses the judge's verdict when displayed labels have different shapes", () => {
    render(<EvalCaseResultView outcome={{ mode: "judge", result: {
      key: "neutral-score", marker: "[ok]", humanLabel: "[-0.15, 0.15]", judgeLabel: "+0.00",
      contested: false, detail: "Inside the expected band.", labelRationale: "Neutral evidence.",
    } }} />);
    expect(screen.getByText("passed").closest(".eval-case-result")).toHaveClass("ok");
    expect(screen.queryByText(/disagrees/)).toBeNull();
  });

  it("shows the score spread and each run's reasoning for an unstable scoring case", () => {
    render(<EvalCaseResultView outcome={{ mode: "scoring_stability", result: {
      key: "flip", marker: "[UNSTABLE]", agreement: 0.5, tally: { pass: 1, fail: 1 },
      scoreMin: -0.2, scoreMax: 0.3,
      runs: [{ outcome: "pass", detail: "**Grounded** evidence." }, { outcome: "fail", detail: "Outside the band." }],
    } }} />);
    expect(screen.getByText("failed").closest(".eval-case-result")).toHaveClass("fail");
    expect(screen.getByText(/score -0.20..0.30/)).toBeInTheDocument();
    expect(screen.getByText("Grounded").tagName).toBe("STRONG");
    expect(screen.getByText("Outside the band.")).toBeInTheDocument();
  });
});


it("summarizes only decisive Judge results and reports contested/unrun cases separately", () => {
  const ok = { key: "a", passName: "matching", marker: "[ok]", humanLabel: "matches", judgeLabel: "matches", contested: false, detail: "Synthetic", labelRationale: "" };
  const disputed = { ...ok, key: "b", marker: "[contested]", contested: true, judgeLabel: "mismatches" };
  expect(runSummary({ eval: "judge", result: { cases: [ok, disputed] } }, 3)).toBe("1/1 agree · 1 contested · 1 not run");
  expect(runSummary({ eval: "judge", result: { cases: [disputed] } }, 1)).toBe("No decisive results · 1 contested");
  expect(runSummary({ eval: "judge", result: { cases: [{ ...ok, marker: "[review]" }] } }, 1)).toBe("0/1 agree");
});


it("keeps invalid contested output out of successful summaries", () => {
  const invalid = { ...contested, verdict: "?", error: "No verdict returned" };
  expect(evalCaseStatus({ mode: "consolidation", result: invalid })).toBe("fail");
  expect(runSummary({ eval: "consolidation", result: { cases: [invalid] } }, 1)).toBe("0/1 passed");
});


it("does not describe incomplete attempts or contested flips as stable", () => {
  const incomplete = { key: "error", marker: "[incomplete]", agreement: null, tally: { error: 3 }, runs: [] };
  const split = { ...incomplete, key: "split", marker: "[contested-split]", agreement: 0.5, tally: { keep: 1, merge: 1 } };
  expect(runSummary({ eval: "matching_stability", result: { cases: [incomplete, split] } }, 2))
    .toBe("0/2 stable · 1 incomplete · 1 contested split");
});
