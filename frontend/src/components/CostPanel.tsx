import { type ReactNode, useEffect, useState } from "react";
import { fetchCostReport, fetchLastRuns } from "../api";
import type { CostReport, LastRunCost, LastRunsReport } from "../types";

// M13 Pillar 1: AI cost, an Insights subtab. Two views:
//  - Last runs — the most recent Screen and Rank, each with fresh spend vs. what
//    caching saved (the marginal cost of iterating).
//  - Total, all time — cumulative spend across all runs, grouped by run.
// Self-fetches both. Per-run figures come from the run-cost ledger (recorded as each
// run completes); cumulative is summed from stored costs.
export function CostPanel(): ReactNode {
  const [cost, setCost] = useState<CostReport | null>(null);
  const [last, setLast] = useState<LastRunsReport | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    Promise.all([fetchCostReport(), fetchLastRuns()])
      .then(([c, l]) => live && (setCost(c), setLast(l), setState("ready")))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  if (state === "loading") return <p className="match-audit-hint">Loading…</p>;
  if (state === "error" || cost === null || last === null)
    return <p className="match-audit-hint">Couldn’t load AI cost.</p>;

  return (
    <div className="cost-report">
      <div className="cost-section">
        <span className="insights-label">Last runs</span>
        <p className="match-audit-hint">
          What your most recent Screen and Rank each spent on Bedrock, and an estimate of what caching saved by
          reusing unchanged results.
        </p>
        {last.screen === null && last.rank === null ? (
          <p className="match-audit-hint">No runs recorded yet — run Screen or Rank to see per-run cost.</p>
        ) : (
          <>
            <LastRun label="Screen" run={last.screen} />
            <LastRun label="Rank" run={last.rank} />
          </>
        )}
      </div>

      <div className="cost-section">
        <div className="cost-block-head">
          <span className="insights-label">Total AI spend, all time</span>
          <span className="cost-block-total">${cost.totalCostUsd.toFixed(2)}</span>
        </div>
        <p className="match-audit-hint">
          Every dollar spent on AI across all runs so far, grouped by the run that triggers each pass. The spending
          cap limits each individual run before it starts; this is the running total across all of them, with no
          ceiling of its own.
        </p>
        {cost.groups.map((g) => (
          <table key={g.runLabel} className="cost-table">
            <thead>
              <tr className="cost-group-head">
                <th>{g.runLabel}</th>
                <th />
                <th className="cost-num">${g.subtotalUsd.toFixed(4)}</th>
              </tr>
            </thead>
            <tbody>
              {g.passes.map((p) => (
                <tr key={p.passLabel}>
                  <td className="cost-pass-name">{p.passLabel}</td>
                  <td className="cost-num">{p.calls > 0 ? `${p.calls} call${p.calls === 1 ? "" : "s"}` : "—"}</td>
                  <td className="cost-num">${p.costUsd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      </div>
    </div>
  );
}

function LastRun(props: { label: string; run: LastRunCost | null }): ReactNode {
  const { label, run } = props;
  if (run === null) {
    return (
      <table className="cost-table">
        <thead>
          <tr className="cost-group-head">
            <th>{label}</th>
            <th />
            <th className="cost-num cost-muted">not run yet</th>
          </tr>
        </thead>
      </table>
    );
  }
  return (
    <table className="cost-table">
      <thead>
        <tr className="cost-group-head">
          <th>{label}</th>
          <th className="cost-num">${run.freshUsd.toFixed(4)} spent</th>
          <th className="cost-num">
            {run.cachedSavedUsd > 0 ? `~$${run.cachedSavedUsd.toFixed(4)} saved by cache` : "no cache reuse"}
          </th>
        </tr>
      </thead>
      <tbody>
        {run.passes.map((p) => (
          <tr key={p.label}>
            <td className="cost-pass-name">{p.label}</td>
            <td className="cost-num">
              {p.freshCalls > 0 ? `${p.freshCalls} fresh` : "—"}
              {p.cachedCount > 0 ? ` / ${p.cachedCount} cached` : ""}
            </td>
            <td className="cost-num">${p.freshUsd.toFixed(4)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
