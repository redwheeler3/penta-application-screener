import { useCommitteeApi } from "../../api/identity";
import { type ReactNode, useEffect, useState } from "react";
import * as evalsApi from "../../api/evals";
import { AI_PASS_PIPELINE_ORDER } from "../../constants";
import type { CurrentRunResponse, EvalDescriptor, EvalFixtureKey, EvalRunMode } from "../../types";
import { InvariantsEval } from "../evals/InvariantsEval";
import { JudgeBackgrounds } from "../evals/JudgeBackgrounds";
import { RunnableEval } from "../evals/RunnableEval";
import { ConsolidateAuditPanel } from "../observability/ConsolidateAuditPanel";
import { CostPanel } from "../observability/CostPanel";
import { DecomposeAuditPanel } from "../observability/DecomposeAuditPanel";
import { DiscoveryPanel } from "../observability/DiscoveryPanel";
import { MatchAuditPanel } from "../observability/MatchAuditPanel";
import { MetricsPanel } from "../observability/MetricsPanel";

// The developer/operator surface for inspecting + judging the AI (not committee-facing),
// split into two top-level tabs by PURPOSE (CommitteeWorkspace passes `family`):
//   OBSERVABILITY — what the AI did + cost: the per-run pass traces (Pattern discovery,
//     Decomposition, Matching, Consolidation) plus cross-run Cost + Trends.
//   EVALS — is the AI any good: Invariants (whole-rank), the five per-pass evals, Judge.
// Subtabs run in PIPELINE ORDER, start→end (discovery → decompose → match → score →
// consolidate), so both tabs read left-to-right along the process. Eval subtabs drop the
// "Live" prefix — the tab is already "Evals", so the pass name alone reads clean.

export type AIWorkspaceFamily = "obs" | "eval";

type Tab =
  | "discovery" | "decompose" | "match" | "consolidate" | "cost" | "metrics"
  | "invariants" | "scoring" | "consolidation" | "matching" | "decomposition" | "screening" | "judge";

type PassTab = Exclude<EvalFixtureKey, "judge">;
const PASS_EVALS = {
  scoring: { stability: "scoring_stability",
    description: "Run hand-authored synthetic applicants through the REAL scoring prompt + model, then grade each with deterministic assertions. Stability runs each case K times to see if its pass/fail wanders (the score crossing the assertion boundary). Tests the actual prompt, not a recorded artifact." },
  consolidation: { stability: "consolidation_stability",
    description: "Run golden dimension pairs through the REAL consolidation prompt + model, then grade merge/keep against the label by exact match. Stability runs each pair K times to see if the verdict flips. Tests the actual prompt, not a recorded artifact. Contested pairs are shown but not scored." },
  matching: { stability: "matching_stability",
    description: "Run golden prior/new dimension pairs through the REAL identity-match prompt + model, then grade matches/mismatches against the label by exact match. Stability runs each pair K times to see if the verdict flips. Tests the actual prompt, not a recorded artifact. A wrong match corrupts a carried-forward score, so the constructed mismatch pair guards that direction." },
  decomposition: { stability: "decomposition_stability",
    description: "Run golden discovery-report sets through the REAL decomposition prompt + model; the merge/keep verdict is derived from the settled set (all carvings folded into one axis = merge; kept across ≥2 = keep), graded against the label by exact match. Stability runs each set K times to see if the fold flips. Guards both over-fold (collapsing distinct axes) and under-fold (weighting one concept N times)." },
  screening: { stability: "screening_stability",
    description: "Run golden synthetic applicants through the REAL screening prompt + model, then grade the produced flags per-category: expected flags must fire, over-reach guards must stay absent (flagging a benign thing is the costly error since flags gate eligibility), and a clean applicant must raise none. Stability runs each applicant K times to see if the flag set holds." },
} satisfies Record<PassTab, { stability: EvalRunMode; description: string }>;

function isPassTab(tab: Tab): tab is PassTab {
  return tab in PASS_EVALS;
}

export function AIWorkspaceView(props: {
  family: AIWorkspaceFamily;
  run: CurrentRunResponse | null;
  openingId: number | null;
  // Save outcomes (golden case, judge brief) surface as the app's standard toasts, same as
  // Settings and the Rank flows — not inline text.
  onToast: (message: string) => void;
  onError: (message: string) => void;
}): ReactNode {
  const { fetchEvalCatalog } = useCommitteeApi(evalsApi);

  const { family, onToast, onError } = props;
  const toast = { onToast, onError };
  const [catalog, setCatalog] = useState<EvalDescriptor[] | null>(null);
  const [fixtureEditingEnabled, setFixtureEditingEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    if (family !== "eval") return;
    let active = true;
    fetchEvalCatalog()
      .then((data) => { if (active) { setCatalog(data.evals); setFixtureEditingEnabled(data.fixtureEditingEnabled); } })
      .catch(() => { if (active) setCatalog([]); });
    return () => { active = false; };
  }, [family, fetchEvalCatalog]);

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
  // The per-pass tabs render in pipeline order from the shared source of truth (so they can't
  // drift from the judge's grouping); the two cross-cutting evals follow.
  const evalTabs: { id: Tab; label: string; group: string }[] = [
    ...AI_PASS_PIPELINE_ORDER.map((id) => ({
      id: id as Tab,
      label: id.charAt(0).toUpperCase() + id.slice(1),
      group: "pass",
    })),
    { id: "invariants", label: "Invariants", group: "cross" },
    { id: "judge", label: "Judge", group: "cross" },
  ];
  const tabs = family === "obs" ? obsTabs : evalTabs;

  const [tab, setTab] = useState<Tab | null>(null);
  // Default to the family's first tab; fall back if the current pick isn't in it (e.g. a
  // per-run obs tab after the run cleared).
  const activeTab: Tab = tabs.some((t) => t.id === tab) ? (tab as Tab) : tabs[0].id;

  const passTab = isPassTab(activeTab) ? activeTab : null;
  const passConfig = passTab ? PASS_EVALS[passTab] : null;
  const calls = (k: EvalRunMode) => catalog?.find((e) => e.key === k)?.estimatedCalls ?? 0;

  return (
    <div className="observability-view">
      <div className="observability-header">
        <h3>{family === "obs" ? "Observability" : "Evals"}</h3>
      </div>

      <div className="subtabs" role="tablist" aria-label={`${family === "obs" ? "Observability" : "Evals"} sections`}>
        {tabs.map((t, i) => {
          // A thin divider where the group changes (per-pass → cross-cutting; traces → aggregates).
          const divider = i > 0 && tabs[i - 1].group !== t.group;
          return (
            <span key={t.id} style={{ display: "contents" }}>
              {divider ? <span className="observability-subtab-divider" aria-hidden="true" /> : null}
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === t.id}
                className={`subtab${activeTab === t.id ? " active" : ""}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            </span>
          );
        })}
      </div>

      {family === "eval" && fixtureEditingEnabled === false ? (
        <p className="panel-hint">Edit fixtures locally, then deploy the committed files to use them here.</p>
      ) : null}
      <div className="observability-subtab-body">
        {activeTab === "discovery" && props.run ? (
          // Key by analysisId so an analysis change remounts the panel (its fetch is mount-once).
          <DiscoveryPanel key={props.run.analysisId} run={props.run} openingId={props.openingId!} />
        ) : activeTab === "decompose" ? (
          <DecomposeAuditPanel openingId={props.openingId!} />
        ) : activeTab === "match" ? (
          <MatchAuditPanel openingId={props.openingId!} />
        ) : activeTab === "consolidate" ? (
          <ConsolidateAuditPanel openingId={props.openingId!} />
        ) : activeTab === "metrics" ? (
          <MetricsPanel />
        ) : activeTab === "invariants" ? (
          <InvariantsEval editable={fixtureEditingEnabled === true} />
        ) : passTab && passConfig ? (
          <RunnableEval
            key={passTab}
            {...toast}
            caseEvalKey={passTab}
            editable={fixtureEditingEnabled === true}
            runKeys={[passTab, passConfig.stability]}
            description={passConfig.description}
            modes={[
              { evalKey: passTab, label: `Run ${passTab}`, rowLabel: "Run", calls: calls(passTab) },
              { evalKey: passConfig.stability, label: "Run stability (K=5)", rowLabel: "Run stability", calls: calls(passConfig.stability) },
            ]}
          />
        ) : activeTab === "judge" ? (
          <RunnableEval
            key="judge"
            {...toast}
            caseEvalKey="judge"
            editable={fixtureEditingEnabled === true}
            runKeys={["judge", "stability"]}
            groupBy="pass"
            addable={false}
            header={<JudgeBackgrounds {...toast} editable={fixtureEditingEnabled === true} />}
            description="A blind label audit: for every pass's golden cases, an independent model reproduces that pass's output from the pass's brief + the case input (NOT the human label), then the harness compares to the label. A judge run reports judge-vs-human agreement (κ); a stability run repeats each case K times to see if the judge's verdict flips. Cases are grouped by the pass they exercise."
            modes={
              [
                { evalKey: "judge", label: "Run judge + agreement", rowLabel: "Run judge", calls: calls("judge") },
                { evalKey: "stability", label: "Run stability (K=5)", rowLabel: "Run stability", calls: calls("stability") },
              ]
            }
          />
        ) : (
          <CostPanel />
        )}
      </div>
    </div>
  );
}
