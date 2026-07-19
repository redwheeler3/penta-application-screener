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

// The developer/operator surface for inspecting + judging the AI (not committee-facing),
// split into two top-level tabs by PURPOSE (App.tsx passes `family`):
//   OBSERVABILITY — what the AI did + cost: the per-run pass traces (Pattern discovery,
//     Decomposition, Matching, Consolidation) plus cross-run Cost + Trends.
//   EVALS — is the AI any good: Invariants (whole-rank), the four live per-pass evals, Judge.
// Subtabs run in PIPELINE ORDER, start→end (discovery → decompose → match → score →
// consolidate), so both tabs read left-to-right along the process. Eval subtabs drop the
// "Live" prefix — the tab is already "Evals", so the pass name alone reads clean.

export type InsightsFamily = "obs" | "eval";

type Tab =
  | "discovery" | "decompose" | "match" | "consolidate" | "cost" | "metrics"
  | "invariants" | "live_scoring" | "live_consolidation" | "live_matching" | "live_decomposition" | "live_screening" | "judge";

export function InsightsView(props: { family: InsightsFamily; run: CurrentRunResponse | null }): ReactNode {
  const { family } = props;
  const [catalog, setCatalog] = useState<EvalDescriptor[] | null>(null);
  useEffect(() => {
    fetchEvalCatalog()
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setCatalog(d.evals));
  }, []);

  // Observability subtabs in pipeline order; the per-run trace tabs exist only once a run
  // does, then the cross-run aggregates (Cost, Trends) trail.
  // `group` marks a boundary: a thin divider renders where the group changes.
  const obsTabs: { id: Tab; label: string; group: string }[] = [
    ...(props.run
      ? [
          { id: "discovery" as Tab, label: "Pattern discovery", group: "trace" },
          { id: "decompose" as Tab, label: "Decomposition", group: "trace" },
          { id: "match" as Tab, label: "Matching", group: "trace" },
          { id: "consolidate" as Tab, label: "Consolidation", group: "trace" },
        ]
      : []),
    { id: "cost", label: "Cost", group: "aggregate" },
    { id: "metrics", label: "Trends", group: "aggregate" },
  ];
  // Eval subtabs in two groups: the per-pass LIVE evals in pipeline order (screening runs
  // before Rank, then the Rank chain decompose → match → score → consolidate), then the
  // cross-cutting evals that aren't a single pass — Invariants (whole-rank fixture) and Judge
  // (cross-pass label audit).
  const evalTabs: { id: Tab; label: string; group: string }[] = [
    { id: "live_screening", label: "Screening", group: "pass" },
    { id: "live_decomposition", label: "Decomposition", group: "pass" },
    { id: "live_matching", label: "Matching", group: "pass" },
    { id: "live_scoring", label: "Scoring", group: "pass" },
    { id: "live_consolidation", label: "Consolidation", group: "pass" },
    { id: "invariants", label: "Invariants", group: "cross" },
    { id: "judge", label: "Judge", group: "cross" },
  ];
  const tabs = family === "obs" ? obsTabs : evalTabs;

  const [tab, setTab] = useState<Tab | null>(null);
  // Default to the family's first tab; fall back if the current pick isn't in it (e.g. a
  // per-run obs tab after the run cleared).
  const activeTab: Tab = tabs.some((t) => t.id === tab) ? (tab as Tab) : tabs[0].id;

  const calls = (k: string) => catalog?.find((e) => e.key === k)?.estimatedCalls ?? 0;

  return (
    <div className="insights-view">
      <div className="insights-header">
        <h3>{family === "obs" ? "Observability" : "Evals"}</h3>
      </div>

      <div className="insights-subtabs" role="tablist" aria-label={`${family === "obs" ? "Observability" : "Evals"} sections`}>
        {tabs.map((t, i) => {
          // A thin divider where the group changes (per-pass → cross-cutting; traces → aggregates).
          const divider = i > 0 && tabs[i - 1].group !== t.group;
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
            runKeys={["live_scoring", "live_scoring_stability"]}
            description="Run hand-authored synthetic applicants through the REAL scoring prompt + model, then grade each with deterministic assertions and the rubric judge. Stability runs each case K times to see if its pass/fail wanders (the score crossing the assertion boundary). Tests the actual prompt, not a recorded artifact."
            modes={
              [
                { evalKey: "live_scoring", label: "Run live scoring", rowLabel: "Run", calls: calls("live_scoring") },
                { evalKey: "live_scoring_stability", label: "Run stability (K=5)", rowLabel: "Run stability", calls: calls("live_scoring_stability") },
              ] as RunMode[]
            }
          />
        ) : activeTab === "live_consolidation" ? (
          <RunnableEval
            caseEvalKey="live_consolidation"
            runKeys={["live_consolidation", "live_consolidation_stability"]}
            description="Run golden dimension pairs through the REAL consolidation prompt + model, then grade merge/keep against the label by exact match. Stability runs each pair K times to see if the verdict flips. Tests the actual prompt, not a recorded artifact. Contested pairs are shown but not scored."
            modes={
              [
                { evalKey: "live_consolidation", label: "Run live consolidation", rowLabel: "Run", calls: calls("live_consolidation") },
                { evalKey: "live_consolidation_stability", label: "Run stability (K=5)", rowLabel: "Run stability", calls: calls("live_consolidation_stability") },
              ] as RunMode[]
            }
          />
        ) : activeTab === "live_matching" ? (
          <RunnableEval
            caseEvalKey="live_matching"
            runKeys={["live_matching", "live_matching_stability"]}
            description="Run golden prior/new dimension pairs through the REAL identity-match prompt + model, then grade matches/mismatches against the label by exact match. Stability runs each pair K times to see if the verdict flips. Tests the actual prompt, not a recorded artifact. A wrong match corrupts a carried-forward score, so the constructed mismatch pair guards that direction."
            modes={
              [
                { evalKey: "live_matching", label: "Run live matching", rowLabel: "Run", calls: calls("live_matching") },
                { evalKey: "live_matching_stability", label: "Run stability (K=5)", rowLabel: "Run stability", calls: calls("live_matching_stability") },
              ] as RunMode[]
            }
          />
        ) : activeTab === "live_decomposition" ? (
          <RunnableEval
            caseEvalKey="live_decomposition"
            runKeys={["live_decomposition", "live_decomposition_stability"]}
            description="Run golden discovery-report sets through the REAL decomposition prompt + model; the merge/keep verdict is derived from the settled set (all carvings folded into one axis = merge; kept across ≥2 = keep), graded against the label by exact match. Stability runs each set K times to see if the fold flips. Guards both over-fold (collapsing distinct axes) and under-fold (weighting one concept N times)."
            modes={
              [
                { evalKey: "live_decomposition", label: "Run live decomposition", rowLabel: "Run", calls: calls("live_decomposition") },
                { evalKey: "live_decomposition_stability", label: "Run stability (K=5)", rowLabel: "Run stability", calls: calls("live_decomposition_stability") },
              ] as RunMode[]
            }
          />
        ) : activeTab === "live_screening" ? (
          <RunnableEval
            caseEvalKey="live_screening"
            runKeys={["live_screening", "live_screening_stability"]}
            description="Run golden synthetic applicants through the REAL screening prompt + model, then grade the produced flags per-category: expected flags must fire, over-reach guards must stay absent (flagging a benign thing is the costly error since flags gate eligibility), and a clean applicant must raise none. Stability runs each applicant K times to see if the flag set holds."
            modes={
              [
                { evalKey: "live_screening", label: "Run live screening", rowLabel: "Run", calls: calls("live_screening") },
                { evalKey: "live_screening_stability", label: "Run stability (K=5)", rowLabel: "Run stability", calls: calls("live_screening_stability") },
              ] as RunMode[]
            }
          />
        ) : activeTab === "judge" ? (
          <RunnableEval
            caseEvalKey="judge"
            runKeys={["judge", "stability"]}
            groupBy="pass"
            harvestable
            description="The judge case set, run two ways over the SAME cases: a one-pass judge run reports judge-vs-human agreement; a stability run judges each case K times to see if a verdict flips. Cases are grouped by the production pass they exercise."
            modes={
              [
                { evalKey: "judge", label: "Run judge + agreement", rowLabel: "Run judge", calls: calls("judge") },
                { evalKey: "stability", label: "Run stability (K=5)", rowLabel: "Run stability", calls: calls("stability") },
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
