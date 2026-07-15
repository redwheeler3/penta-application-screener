import { type ReactNode, useEffect, useState } from "react";
import { fetchCostReport, fetchLastRuns } from "../api";
import type { CostReport, LastRunCost, LastRunsReport } from "../types";

// M13 Pillar 1: AI cost, an Insights subtab. Two sections, same column layout so they
// line up: [ label | tokens (in→out) | uncached | cached | saved by cache | spent ].
// Spent is the rightmost hard number; cache savings sit to its left as the softer
// estimate; tokens sit next to the label as the "why it cost that" breakdown.
//   - Last runs — the most recent Screen, full Rank, and score-current update.
//   - Cumulative spend — cumulative spend + savings, grouped by run.
// Passes that can't cache (pattern discovery, dimension matching) show "—" for the
// cached count and savings, never 0, so structural absence of caching doesn't read as
// "caching failed".
const money = (n: number) => `$${n.toFixed(4)}`;
const savedCell = (n: number, cacheable: boolean) => (!cacheable ? "—" : money(n));
const cachedCell = (n: number, cacheable: boolean) => (!cacheable ? "—" : String(n));
// Compact token count: 1_234 → "1.2k", 26_203 → "26.2k". Output ~5× the input rate on
// Sonnet, so the in→out split is what tells you whether a pass is input- or output-bound.
const tok = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
const tokensCell = (input: number, output: number) =>
  input || output ? `${tok(input)} → ${tok(output)}` : "—";
type InsightRunKind = "screen" | "rank" | "rank_scores";

const RUN_LABELS: Record<InsightRunKind, string> = {
  screen: "Screen",
  rank: "Discover criteria & rank",
  rank_scores: "Score current criteria",
};

const PASS_LABELS: Record<InsightRunKind, Array<{ label: string; cacheable: boolean }>> = {
  screen: [{ label: "Screening", cacheable: true }],
  rank: [
    { label: "Pattern discovery", cacheable: false },
    { label: "Dimension decomposition", cacheable: false },
    { label: "Dimension matching", cacheable: false },
    { label: "Dimension scoring", cacheable: true },
    { label: "Dimension consolidation", cacheable: false },
  ],
  rank_scores: [{ label: "Dimension scoring", cacheable: true }],
};

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

  const runs = [last.screen, last.rank, last.rankScores].filter((r): r is LastRunCost => r !== null);
  const lastSpent = runs.reduce((s, r) => s + r.freshUsd, 0);

  return (
    <div className="cost-report">
      <div className="cost-section">
        <div className="cost-block-head">
          <span className="insights-label">Last runs</span>
          <span className="cost-block-total">{`$${lastSpent.toFixed(2)}`} spent</span>
        </div>
        <p className="match-audit-hint">
          What your most recent Screen, full Rank, and score-current update each spent on Bedrock, and an estimate
          of what caching saved by reusing unchanged results.
        </p>
        {runs.length === 0 ? (
          <p className="match-audit-hint">No runs recorded yet — run Screen or Rank to see per-run cost.</p>
        ) : (
          <table className="cost-table">
            <CostHead />
            {[last.screen, last.rank, last.rankScores].map((run, i) =>
              run === null ? (
                <tbody key={i}>
                  {renderEmptyRun((["screen", "rank", "rank_scores"] as const)[i])}
                </tbody>
              ) : (
                <tbody key={i}>
                  <tr className="cost-group-head">
                    <td>{RUN_LABELS[run.kind as InsightRunKind]}</td>
                    <td className="cost-num" />
                    <td className="cost-num" />
                    <td className="cost-num" />
                    <td className="cost-num">{run.cachedSavedUsd > 0 ? money(run.cachedSavedUsd) : "—"}</td>
                    <td className="cost-num">{money(run.freshUsd)}</td>
                  </tr>
                  {run.passes.map((p) => (
                    <tr key={p.label}>
                      <td className="cost-pass-name">{p.label}</td>
                      <td className="cost-num">{tokensCell(p.inputTokens, p.outputTokens)}</td>
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
          <span className="insights-label">Cumulative spend</span>
          <span className="cost-block-total">{`$${cost.totalCostUsd.toFixed(2)}`} spent</span>
        </div>
        <p className="match-audit-hint">
          What all Screen, full Rank, and score-current update runs have spent on Bedrock, and an estimate of what
          caching saved by reusing unchanged results.
        </p>
        <table className="cost-table">
          <CostHead />
          {cost.groups.map((g) => (
            <tbody key={g.runLabel}>
              <tr className="cost-group-head">
                <td>{g.runLabel}</td>
                <td className="cost-num" />
                <td className="cost-num" />
                <td className="cost-num" />
                <td className="cost-num">{g.subtotalSavedUsd > 0 ? money(g.subtotalSavedUsd) : "—"}</td>
                <td className="cost-num">{money(g.subtotalUsd)}</td>
              </tr>
              {g.passes.map((p) => (
                <tr key={p.passLabel}>
                  <td className="cost-pass-name">{p.passLabel}</td>
                  <td className="cost-num">{tokensCell(p.inputTokens, p.outputTokens)}</td>
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

function renderEmptyRun(kind: InsightRunKind): ReactNode {
  return (
    <>
      <tr className="cost-group-head">
        <td>{RUN_LABELS[kind]}</td>
        <td className="cost-num" />
        <td className="cost-num" />
        <td className="cost-num" />
        <td className="cost-num">—</td>
        <td className="cost-num">{money(0)}</td>
      </tr>
      {PASS_LABELS[kind].map((p) => (
        <tr key={p.label}>
          <td className="cost-pass-name">{p.label}</td>
          <td className="cost-num">—</td>
          <td className="cost-num">0</td>
          <td className="cost-num">{cachedCell(0, p.cacheable)}</td>
          <td className="cost-num">{savedCell(0, p.cacheable)}</td>
          <td className="cost-num">{money(0)}</td>
        </tr>
      ))}
    </>
  );
}

// Shared header so both tables carry identical columns and widths.
function CostHead(): ReactNode {
  return (
    <thead>
      <tr>
        <th className="cost-col-label" />
        <th className="cost-col-tokens">tokens (in→out)</th>
        <th className="cost-col-count">uncached</th>
        <th className="cost-col-count">cached</th>
        <th className="cost-col-money">cache savings</th>
        <th className="cost-col-money">spent</th>
      </tr>
    </thead>
  );
}
