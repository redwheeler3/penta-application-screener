import { caseOutcomes } from "../../api/evals";
import type { EvalCaseOutcome, EvalRunSummary } from "../../types";

export type EvalCaseStatus = "ok" | "fail" | "contested";

/** Shared by case dots, detail headings, and run summaries. Contested divergence
 * calls for review; it is not a failure of a label that permits either outcome. */
export function evalCaseStatus(outcome: EvalCaseOutcome): EvalCaseStatus {
  const { mode, result } = outcome;
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
  const { eval: mode, result } = run;
  const outcomes = caseOutcomes(run);
  const total = totalCases || outcomes.length;
  const passing = outcomes.filter((outcome) => evalCaseStatus(outcome) !== "fail").length;
  if (mode === "judge") {
    const head = total ? `${passing}/${total} agree` : "";
    const agreement = result.agreement;
    if (!agreement) return head;
    const parts = head ? [head] : [];
    parts.push(`κ ${agreement.kappa !== null ? agreement.kappa.toFixed(2) : "n/a"}`);
    if (agreement.failureRecall !== null) {
      parts.push(`failure-recall ${agreement.failureCaught}/${agreement.failureTotal} = ${Math.round(agreement.failureRecall * 100)}%`);
    }
    return parts.join(" · ");
  }
  if (!total) return "";
  const stability = mode.endsWith("_stability") || mode === "stability";
  return `${passing}/${total} ${stability ? "stable" : "passed"}`;
}
