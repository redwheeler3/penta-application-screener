import { type ReactNode, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchMatchAudit } from "../api";
import type { MatchAuditResponse } from "../types";

// M13 per-run AI legibility: the carry-forward audit for the current run. Surfaces
// what discovery ACTUALLY emitted (pre key-adoption), how the match pass mapped each
// new dimension onto a prior one, and the derived carry-forward rate — the signal
// that answers "is the match pass over-matching?" without a SQLite spelunk.
//
// Lazily fetches its own data on mount: this is a collapsible debug surface off the
// ranked view's critical path, so it stays out of the parent's (already large) state
// and only the members who open it pay for the round-trip.
export function MatchAuditPanel(props: { defaultOpen?: boolean }): ReactNode {
  const [audit, setAudit] = useState<MatchAuditResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    fetchMatchAudit()
      .then((a) => live && (setAudit(a), setState("ready")))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  // No audit is the common, correct case (first run, or a run from before capture) —
  // render nothing rather than an empty panel that reads as broken.
  if (state === "error" || (state === "ready" && audit === null)) return null;

  return (
    <details className="raw-row-section no-print" open={props.defaultOpen}>
      <summary>AI carry-forward audit (match pass)</summary>
      {state === "loading" || audit === null ? (
        <p className="match-audit-hint">Loading…</p>
      ) : (
        <MatchAuditBody audit={audit} />
      )}
    </details>
  );
}

function MatchAuditBody(props: { audit: MatchAuditResponse }): ReactNode {
  const { audit } = props;
  const firstRun = audit.priorDimensionCount === 0;
  const rate = audit.carryForwardRate;
  // A high rate is the over-matching smell; flag it visually so the number isn't just
  // decoration. The band mirrors the SPEC's "persistently near-100%" concern.
  const rateClass =
    rate === null ? "" : rate >= 0.9 ? " match-audit-rate-high" : rate >= 0.6 ? " match-audit-rate-mid" : "";

  return (
    <div className="match-audit">
      <p className="match-audit-hint">
        What pattern discovery emitted this run, and how many dimensions the match pass carried forward from the
        prior run (reusing their tier placement and cached scores). A persistently high carry-forward rate can mean
        the match pass is over-matching.
      </p>

      <dl className="match-audit-stats">
        <div>
          <dt>Discovered</dt>
          <dd>{audit.discoveredCount}</dd>
        </div>
        <div>
          <dt>Carried forward</dt>
          <dd>{audit.matchedCount}</dd>
        </div>
        <div>
          <dt>New</dt>
          <dd>{audit.newCount}</dd>
        </div>
        <div>
          <dt>Carry-forward rate</dt>
          <dd className={`match-audit-rate${rateClass}`}>
            {firstRun || rate === null ? "—" : `${Math.round(rate * 100)}%`}
          </dd>
        </div>
      </dl>
      {firstRun ? (
        <p className="match-audit-hint">First run — no prior dimensions to match against, so carry-forward is N/A.</p>
      ) : null}

      <table className="match-audit-table">
        <thead>
          <tr>
            <th>Discovered dimension</th>
            <th>Carried forward from</th>
          </tr>
        </thead>
        <tbody>
          {audit.rawDiscoveryDimensions.map((d) => {
            const matchedTo = audit.newToOld[d.key];
            return (
              <tr key={d.key}>
                <td>
                  {d.name}
                  {d.fromCommitteeRequest ? <span className="match-audit-tag">requested</span> : null}
                  <span className="match-audit-key">{d.key}</span>
                </td>
                <td>
                  {matchedTo ? (
                    <>
                      {matchedTo.name ?? <span className="match-audit-key-unnamed">(prior dimension)</span>}
                      <span className="match-audit-key">{matchedTo.key}</span>
                    </>
                  ) : (
                    <span className="match-audit-new">new</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {audit.matchNarrative ? (
        <div className="match-audit-narrative">
          <span className="match-audit-narrative-label">Match reasoning</span>
          {/* Reuse the .ai-narrative markdown box (same as the screening narrative)
              so the match reasoning renders as markdown, not raw text. */}
          <div className="ai-narrative">
            <ReactMarkdown>{audit.matchNarrative}</ReactMarkdown>
          </div>
        </div>
      ) : null}
    </div>
  );
}
