import { type ReactNode, useEffect, useState } from "react";
import { fetchEvalCatalog } from "../api";
import type { CurrentRunResponse, EvalDescriptor } from "../types";
import { ConsolidateAuditPanel } from "./ConsolidateAuditPanel";
import { CostPanel } from "./CostPanel";
import { DecomposeAuditPanel } from "./DecomposeAuditPanel";
import { DiscoveryPanel } from "./DiscoveryPanel";
import { InvariantsEval } from "./evals/InvariantsEval";
import { RunnableEval, type RunMode } from "./evals/RunnableEval";
import { MatchAuditPanel } from "./MatchAuditPanel";
import { MetricsPanel } from "./MetricsPanel";

// "AI Quality" — the one surface for judging and inspecting the AI (developer/operator, not
// committee-facing). Two families of subtab under one roof:
//   OBSERVABILITY (what the AI did + cost): Discovery / Decomposition / Matching /
//     Consolidation (per-run), Cost, Trends (cross-run).
//   EVALS (is the AI any good): Invariants (free), Live scoring, Judge (agreement + stability).
// Evals need no Rank, so this tab shows even before a run — the eval subtabs are always
// available; the per-run observability subtabs appear once a run exists.

type Tab =
  | "discovery" | "decompose" | "match" | "consolidate" | "cost" | "metrics"
  | "invariants" | "live_scoring" | "judge";

export function InsightsView(props: { run: CurrentRunResponse | null }): ReactNode {
  const [catalog, setCatalog] = useState<EvalDescriptor[] | null>(null);
  useEffect(() => {
    fetchEvalCatalog()
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setCatalog(d.evals));
  }, []);

  const perRunTabs: { id: Tab; label: string }[] = props.run
    ? [
        { id: "discovery", label: "Pattern discovery" },
        { id: "decompose", label: "Decomposition" },
        { id: "match", label: "Matching" },
        { id: "consolidate", label: "Consolidation" },
      ]
    : [];
  // Observability group + eval group. Cost/Trends are cross-run (always shown); evals always shown.
  const tabs: { id: Tab; label: string; group: "obs" | "eval" }[] = [
    ...perRunTabs.map((t) => ({ ...t, group: "obs" as const })),
    { id: "cost", label: "Cost", group: "obs" },
    { id: "metrics", label: "Trends", group: "obs" },
    { id: "invariants", label: "Invariants", group: "eval" },
    { id: "live_scoring", label: "Live scoring", group: "eval" },
    { id: "judge", label: "Judge", group: "eval" },
  ];

  const [tab, setTab] = useState<Tab>(props.run ? "discovery" : "invariants");
  // A per-run tab is only valid with a run; otherwise fall back to the eval side.
  const perRunActive = ["discovery", "decompose", "match", "consolidate"].includes(tab);
  const activeTab: Tab = !props.run && perRunActive ? "invariants" : tab;

  const calls = (k: string) => catalog?.find((e) => e.key === k)?.estimatedCalls ?? 0;

  return (
    <div className="insights-view">
      <div className="insights-header">
        <h3>AI Quality</h3>
      </div>

      <div className="insights-subtabs" role="tablist" aria-label="AI quality sections">
        {tabs.map((t, i) => {
          // A thin divider before the first eval tab, separating observability from evals.
          const prev = tabs[i - 1];
          const divider = prev && prev.group === "obs" && t.group === "eval";
          return (
            <span key={t.id} style={{ display: "contents" }}>
              {divider ? <span className="insights-subtab-divider" aria-hidden="true" /> : null}
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === t.id}
                className={`insights-subtab${activeTab === t.id ? " active" : ""}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            </span>
          );
        })}
      </div>

      <div className="insights-subtab-body">
        {activeTab === "discovery" && props.run ? (
          <DiscoveryPanel run={props.run} />
        ) : activeTab === "decompose" ? (
          <DecomposeAuditPanel />
        ) : activeTab === "match" ? (
          <MatchAuditPanel />
        ) : activeTab === "consolidate" ? (
          <ConsolidateAuditPanel />
        ) : activeTab === "metrics" ? (
          <MetricsPanel />
        ) : activeTab === "invariants" ? (
          <InvariantsEval />
        ) : activeTab === "live_scoring" ? (
          <RunnableEval
            caseEvalKey="live_scoring"
            description="Run hand-authored synthetic applicants through the REAL scoring prompt + model, then grade each with deterministic assertions and the rubric judge. Tests the actual prompt, not a recorded artifact."
            modes={[{ evalKey: "live_scoring", label: "Run live scoring", rowLabel: "run", calls: calls("live_scoring") }]}
          />
        ) : activeTab === "judge" ? (
          <RunnableEval
            caseEvalKey="judge"
            groupBy="pass"
            harvestable
            description="The judge case set, run two ways over the SAME cases: a one-pass judge run reports judge-vs-human agreement; a stability run judges each case K times to see if a verdict flips. Cases are grouped by the production pass they exercise."
            modes={
              [
                { evalKey: "judge", label: "Run judge + agreement", rowLabel: "judge", calls: calls("judge") },
                { evalKey: "stability", label: "Run stability (K=5)", rowLabel: "stability", calls: calls("stability") },
              ] as RunMode[]
            }
          />
        ) : (
          <CostPanel />
        )}
      </div>
    </div>
  );
}
