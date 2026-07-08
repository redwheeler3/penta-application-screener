import { type ReactNode, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchMatchAudit } from "../api";
import type { MatchAuditResponse } from "../types";

// M13 per-run AI legibility: the carry-forward audit for the current run. Surfaces
// what discovery ACTUALLY emitted (pre key-adoption), how the match pass mapped each
// new dimension onto a prior one, and the derived carry-forward rate — the signal
// that answers "is the match pass over-matching?" without a SQLite spelunk.
//
// Self-fetches on mount. Rendered as the active Insights subtab, so an absent audit
// (a first run, or a run from before capture) shows an explicit empty state rather
// than vanishing — "nothing carried forward" is information, not a broken panel.
export function MatchAuditPanel(): ReactNode {
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

  if (state === "loading") return <p className="match-audit-hint">Loading…</p>;
  if (state === "error") return <p className="match-audit-hint">Couldn’t load the carry-forward audit.</p>;
  if (audit === null) {
    return (
      <p className="match-audit-hint">
        No carry-forward audit for this run — it’s the first run (nothing to match against) or predates audit
        capture. Re-rank to populate it.
      </p>
    );
  }
  return <MatchAuditBody audit={audit} />;
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
        Dimensions carried forward reuse their tier placement and cached scores. A persistently high carry-forward
        rate can mean the match pass is over-matching.
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
        <div className="insights-narrative">
          <span className="insights-label">Match reasoning</span>
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
