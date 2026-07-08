import { type ReactNode } from "react";
import { MatchAuditPanel } from "./MatchAuditPanel";

// The run-level AI observability surface (M13). Home for the general, non-applicant-
// specific audits: how discovery's dimensions carried forward this run, and — as the
// milestone builds out — cost attribution and operational metrics. Applicant-specific
// traces live on the candidate detail page instead, co-located with the candidate.
//
// This is deliberately separate from the Ranking tab: that view is a decision surface
// (read the stack rank, tier the criteria), whereas these are inspection surfaces for
// understanding what the AI did. Keeping them apart stops the ranked view from getting
// busy with operator concerns.
export function InsightsView(): ReactNode {
  return (
    <div className="insights-view">
      <div className="insights-header">
        <h3>AI insights</h3>
        <p className="insights-subhead">
          How the current run's AI behaved — what the model discovered and carried forward. Inspection detail, not
          part of the ranking decision.
        </p>
      </div>
      <MatchAuditPanel defaultOpen />
    </div>
  );
}
