import { type ReactNode, useState } from "react";
import type { CurrentRunResponse } from "../types";
import { DiscoveryPanel } from "./DiscoveryPanel";
import { MatchAuditPanel } from "./MatchAuditPanel";

// The run-level AI observability surface (M13). Home for the general, non-applicant-
// specific audits: what pattern discovery found this run, and how those dimensions
// carried forward from the prior run — and, as the milestone builds out, cost
// attribution and operational metrics. Applicant-specific traces live on the candidate
// detail page instead, co-located with the candidate.
//
// Deliberately separate from the Ranking tab: that view is a decision surface (read the
// stack rank, tier the criteria), whereas these are inspection surfaces. Sections show
// as SUBTABS (one at a time) rather than stacked panels — the tab will hold four
// concerns by the end of M13, and subtabs keep the page short and scannable as they
// land, instead of a growing scroll of accordions.
type InsightsTab = "discovery" | "carryForward";

export function InsightsView(props: { run: CurrentRunResponse }): ReactNode {
  const [tab, setTab] = useState<InsightsTab>("discovery");
  const tabs: { id: InsightsTab; label: string }[] = [
    { id: "discovery", label: "Pattern discovery" },
    { id: "carryForward", label: "Carry-forward" },
  ];
  return (
    <div className="insights-view">
      <div className="insights-header">
        <h3>AI insights</h3>
        <p className="insights-subhead">Inspection detail for the current run — not part of the ranking decision.</p>
      </div>

      <div className="insights-subtabs" role="tablist" aria-label="AI insights sections">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`insights-subtab${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="insights-subtab-body">
        {tab === "discovery" ? <DiscoveryPanel run={props.run} /> : <MatchAuditPanel />}
      </div>
    </div>
  );
}
