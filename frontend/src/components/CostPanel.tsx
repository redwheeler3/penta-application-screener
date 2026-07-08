import { type ReactNode, useEffect, useState } from "react";
import { fetchCostReport } from "../api";
import type { CostReport } from "../types";

// M13 Pillar 1: cumulative AI spend across all runs, an Insights subtab. Self-fetches.
// Only a cumulative figure is shown — cost rows are a reuse cache with no run-id stamp,
// so per-run cost can't be reconstructed without over-counting.
export function CostPanel(): ReactNode {
  const [report, setReport] = useState<CostReport | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    fetchCostReport()
      .then((r) => live && (setReport(r), setState("ready")))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  if (state === "loading") return <p className="match-audit-hint">Loading…</p>;
  if (state === "error" || report === null) return <p className="match-audit-hint">Couldn’t load AI cost.</p>;

  const { cumulative } = report;
  return (
    <div className="cost-report">
      <div className="cost-block">
        <div className="cost-block-head">
          <span className="insights-label">Total AI spend, all time</span>
          <span className="cost-block-total">${cumulative.totalCostUsd.toFixed(2)}</span>
        </div>
        <p className="match-audit-hint">
          Every dollar spent on AI across all runs so far. The spending cap limits each individual run (Screen or
          Rank) before it starts; this is the running total across all of them, with no ceiling of its own.
        </p>
        <table className="cost-table">
          <tbody>
            {cumulative.passes.map((p) => (
              <tr key={p.passLabel}>
                <td>{p.passLabel}</td>
                <td className="cost-num">{p.calls > 0 ? `${p.calls} call${p.calls === 1 ? "" : "s"}` : "—"}</td>
                <td className="cost-num">${p.costUsd.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
