import { caseOutcomes } from "../../api/evals";
import type { EvalCaseOutcome, EvalRunSummary } from "../../types";

export type EvalCaseStatus = "ok" | "fail" | "contested";

/** Shared by case dots, detail headings, and run summaries. Contested divergence
 * calls for review; it is not a failure of a label that permits either outcome. */
export function evalCaseStatus(outcome: EvalCaseOutcome): EvalCaseStatus {
  const { mode, result } = outcome;
  if (result.error) return "fail";
  switch (mode) {
    case "judge":
      if (result.marker === "[contested]" || result.contested) return "contested";
      return result.marker === "[ok]" ? "ok" : "fail";
    case "consolidation":
    case "matching":
    case "decomposition":
      if (result.contested) return result.verdict === result.expected ? "ok" : "contested";
      return result.passed ? "ok" : "fail";
    case "screening":
      return result.passed ? "ok" : result.contested ? "contested" : "fail";
    case "scoring":
      return result.passed ? "ok" : "fail";
    default:
      if (result.marker === "[contested-split]") return "contested";
      return result.marker === "[stable]" ? "ok" : "fail";
  }
}

export function runSummary(run: EvalRunSummary, totalCases: number): string {
  const { eval: mode } = run;
  const outcomes = caseOutcomes(run);
  const total = totalCases || outcomes.length;
  if (!total) return "No cases · 0 attempts";
  const passing = outcomes.filter((outcome) => evalCaseStatus(outcome) !== "fail").length;
  if (mode === "judge") {
    const decisive = outcomes.filter((outcome) => !outcome.result.error && evalCaseStatus(outcome) !== "contested");
    const agreeing = decisive.filter((outcome) => evalCaseStatus(outcome) === "ok").length;
    const errors = outcomes.filter((outcome) => !!outcome.result.error).length;
    const contested = outcomes.length - decisive.length - errors;
    const missing = Math.max(0, total - outcomes.length);
    return [decisive.length ? `${agreeing}/${decisive.length} agree` : "No decisive results",
      contested ? `${contested} contested` : "", errors ? `${errors} error${errors === 1 ? "" : "s"}` : "", missing ? `${missing} not run` : ""].filter(Boolean).join(" · ");
  }
  const stability = mode.endsWith("_stability") || mode === "stability";
  if (stability) {
    const stable = outcomes.filter((outcome) => evalCaseStatus(outcome) === "ok").length;
    const incomplete = outcomes.filter(({ result }) => "marker" in result && result.marker === "[incomplete]").length;
    const split = outcomes.filter((outcome) => evalCaseStatus(outcome) === "contested").length;
    return [`${stable}/${total} stable`, incomplete ? `${incomplete} incomplete` : "",
      split ? `${split} contested split` : ""].filter(Boolean).join(" · ");
  }
  const errors = outcomes.filter((outcome) => !!outcome.result.error).length;
  return [`${passing}/${total} passed`, errors ? `${errors} incomplete` : ""].filter(Boolean).join(" · ");
}
