import { type ReactNode, useEffect, useState } from "react";
import { fetchCostReport, fetchLastRuns } from "../api";
import type { CostReport, LastRunCost, LastRunsReport } from "../types";

// M13 Pillar 1: AI cost, an Insights subtab. Two sections, same column layout so they
// line up: [ label | uncached | cached | saved by cache | spent ]. Spent is the
// rightmost hard number; "saved by cache" sits to its left as the softer estimate.
//   - Last runs — the most recent Screen and Rank, fresh spend vs. cache savings.
//   - Total, all time — cumulative spend + savings, grouped by run.
// Passes that can't cache (pattern discovery, dimension matching) show "—" for the
// cached count and savings, never 0, so structural absence of caching doesn't read as
// "caching failed".
const money = (n: number) => `$${n.toFixed(4)}`;
const savedCell = (n: number, cacheable: boolean) => (!cacheable ? "—" : n > 0 ? `~${money(n)}` : money(n));
const cachedCell = (n: number, cacheable: boolean) => (!cacheable ? "—" : String(n));

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

  const runs = [last.screen, last.rank].filter((r): r is LastRunCost => r !== null);
  const lastSpent = runs.reduce((s, r) => s + r.freshUsd, 0);

  return (
    <div className="cost-report">
      <div className="cost-section">
        <div className="cost-block-head">
          <span className="insights-label">Last runs</span>
          <span className="cost-block-total">{`$${lastSpent.toFixed(2)}`} spent</span>
        </div>
        <p className="match-audit-hint">
          What your most recent Screen and Rank each spent on Bedrock, and an estimate of what caching saved by
          reusing unchanged results.
        </p>
        {runs.length === 0 ? (
          <p className="match-audit-hint">No runs recorded yet — run Screen or Rank to see per-run cost.</p>
        ) : (
          <table className="cost-table">
            <CostHead />
            {[last.screen, last.rank].map((run, i) =>
              run === null ? (
                <tbody key={i}>
                  <tr className="cost-group-head">
                    <td>{i === 0 ? "Screen" : "Rank"}</td>
                    <td className="cost-muted" colSpan={4}>
                      not run yet
                    </td>
                  </tr>
                </tbody>
              ) : (
                <tbody key={i}>
                  <tr className="cost-group-head">
                    <td>{run.kind === "screen" ? "Screen" : "Rank"}</td>
                    <td className="cost-num" />
                    <td className="cost-num" />
                    <td className="cost-num">{run.cachedSavedUsd > 0 ? `~${money(run.cachedSavedUsd)}` : "—"}</td>
                    <td className="cost-num">{money(run.freshUsd)}</td>
                  </tr>
                  {run.passes.map((p) => (
                    <tr key={p.label}>
                      <td className="cost-pass-name">{p.label}</td>
                      <td className="cost-num">{p.freshCalls}</td>
                      <td className="cost-num">{cachedCell(p.cachedCount, p.cacheable)}</td>
                      <td className="cost-num">{savedCell(p.cachedSavedUsd, p.cacheable)}</td>
                      <td className="cost-num">{money(p.freshUsd)}</td>
                    </tr>
                  ))}
                </tbody>
              ),
            )}
          </table>
        )}
      </div>

      <div className="cost-section">
        <div className="cost-block-head">
          <span className="insights-label">Total AI spend, all time</span>
          <span className="cost-block-total">{`$${cost.totalCostUsd.toFixed(2)}`} spent</span>
        </div>
        <p className="match-audit-hint">
          Every dollar spent on AI across all runs so far, grouped by the run that triggers each pass. The spending
          cap limits each individual run before it starts; this is the running total across all of them, with no
          ceiling of its own.
        </p>
        <table className="cost-table">
          <CostHead />
          {cost.groups.map((g) => (
            <tbody key={g.runLabel}>
              <tr className="cost-group-head">
                <td>{g.runLabel}</td>
                <td className="cost-num" />
                <td className="cost-num" />
                <td className="cost-num">{g.subtotalSavedUsd > 0 ? `~${money(g.subtotalSavedUsd)}` : "—"}</td>
                <td className="cost-num">{money(g.subtotalUsd)}</td>
              </tr>
              {g.passes.map((p) => (
                <tr key={p.passLabel}>
                  <td className="cost-pass-name">{p.passLabel}</td>
                  <td className="cost-num">{p.calls}</td>
                  <td className="cost-num">{cachedCell(p.cachedCount, p.cacheable)}</td>
                  <td className="cost-num">{savedCell(p.cachedSavedUsd, p.cacheable)}</td>
                  <td className="cost-num">{money(p.costUsd)}</td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  );
}

// Shared header so both tables carry identical columns and widths.
function CostHead(): ReactNode {
  return (
    <thead>
      <tr>
        <th className="cost-col-label" />
        <th className="cost-col-count">uncached</th>
        <th className="cost-col-count">cached</th>
        <th className="cost-col-money">saved by cache</th>
        <th className="cost-col-money">spent</th>
      </tr>
    </thead>
  );
}
