import { type ReactNode, useEffect, useState } from "react";
import { fetchMetrics } from "../api";
import type { MetricsReport, TrendPoint } from "../types";

// M13 Pillar 3: operational trends across runs, an Insights subtab. Reads the same
// RunPassCost rows Cost does, but for *behaviour over time* rather than spend: per-run
// cost, latency, cache-hit rate, failures, and dimension count. Deliberately plain —
// one row per run, newest first, with a tiny inline bar for at-a-glance shape rather
// than a charting dependency (a single-dev MVP doesn't need one). Rank and Screen are
// split because their passes and cadence differ.
const money = (n: number) => `$${n.toFixed(4)}`;
const secs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);
const pct = (r: number | null) => (r === null ? "—" : `${Math.round(r * 100)}%`);
const shortAt = (iso: string) => iso.slice(0, 16).replace("T", " ");

// A minimal inline bar: value relative to the max in its column, so a column reads as a
// crude sparkline down the rows. Purely decorative scale, never a precise axis.
function Bar(props: { value: number; max: number }): ReactNode {
  const width = props.max > 0 ? Math.round((props.value / props.max) * 100) : 0;
  return (
    <span className="metric-bar" aria-hidden="true">
      <span className="metric-bar-fill" style={{ width: `${width}%` }} />
    </span>
  );
}

export function MetricsPanel(): ReactNode {
  const [report, setReport] = useState<MetricsReport | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    fetchMetrics()
      .then((m) => live && (setReport(m), setState("ready")))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  if (state === "loading") return <p className="match-audit-hint">Loading…</p>;
  if (state === "error" || report === null)
    return <p className="match-audit-hint">Couldn’t load operational metrics.</p>;
  if (report.runs.length === 0)
    return <p className="match-audit-hint">No runs recorded yet — run Screen or Rank to see trends.</p>;

  // Newest first for reading; both kinds shown in their own section.
  const rank = report.runs.filter((r) => r.kind === "rank").reverse();
  const screen = report.runs.filter((r) => r.kind === "screen").reverse();

  return (
    <div className="metrics-report">
      <p className="match-audit-hint">
        How each run behaved over time — spend, wall-clock, cache reuse, failures, and (for Rank) the live
        dimension count. Reads the same per-pass ledger as Cost; here it’s trend, not total.
      </p>
      {rank.length > 0 ? <RunTable title="Rank runs" runs={rank} /> : null}
      {screen.length > 0 ? <RunTable title="Screen runs" runs={screen} /> : null}
    </div>
  );
}

function RunTable(props: { title: string; runs: TrendPoint[] }): ReactNode {
  const { runs } = props;
  const maxCost = Math.max(...runs.map((r) => r.costUsd));
  const maxDur = Math.max(...runs.map((r) => r.durationMs));
  // The dims column is always present so the Screen and Rank tables share one layout
  // and line up; Screen rows have no dimension count and show "—".
  return (
    <div className="cost-section">
      <div className="cost-block-head">
        <span className="insights-label">{props.title}</span>
        <span className="cost-block-total">{runs.length} runs</span>
      </div>
      <table className="cost-table metrics-table">
        <thead>
          <tr>
            <th className="cost-col-label">when</th>
            <th className="cost-col-money">cost</th>
            <th className="cost-col-latency">latency</th>
            <th className="cost-col-count">cache hit</th>
            <th className="cost-col-count">failed</th>
            <th className="cost-col-count">dims</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r, i) => (
            <tr key={i}>
              <td className="cost-pass-name">{shortAt(r.at)}</td>
              <td className="cost-num">
                <Bar value={r.costUsd} max={maxCost} />
                {money(r.costUsd)}
              </td>
              <td className="cost-num">
                <Bar value={r.durationMs} max={maxDur} />
                {secs(r.durationMs)}
              </td>
              <td className="cost-num">{pct(r.cacheHitRate)}</td>
              <td className={`cost-num${r.failedCalls > 0 ? " metric-failed" : ""}`}>{r.failedCalls}</td>
              <td className="cost-num">{r.dimensions ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
