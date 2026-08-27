import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { fetchMatchAudit } from "../../api/ranking";
import { useFetchResource } from "../../hooks/useFetchResource";
import type { MatchAuditResponse } from "../../types";
import { RetryLoadError } from "../shared/RetryLoadError";

// Show how settled dimensions map onto prior dimensions. A high reuse rate is expected;
// individual incorrect mappings are the actionable signal.
export function MatchAuditPanel(): ReactNode {
  const { data: audit, state, reload } = useFetchResource(fetchMatchAudit);

  if (state === "loading") return <p className="panel-hint">Loading…</p>;
  if (state === "error") return <RetryLoadError message="Couldn’t load the matching audit." onRetry={() => void reload()} />;
  if (audit === null) {
    return (
      <p className="panel-hint">
        No matching audit for this run — it’s the first run (nothing to match against) or predates audit
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
  // The aggregate rate cannot distinguish stable reuse from an incorrect match, so it
  // deliberately has no alarm colour; inspect individual mappings instead.

  // New dimensions first: the actionable rows (scored from scratch this run) are the
  // few worth reading; reused rows follow. Stable sort preserves discovery order within
  // each group.
  const rows = [...audit.rawDiscoveryDimensions].sort((a, b) => {
    const aNew = audit.newToOld[a.key] === undefined ? 0 : 1;
    const bNew = audit.newToOld[b.key] === undefined ? 0 : 1;
    return aNew - bNew;
  });

  return (
    <div className="match-audit">
      <p className="panel-hint">
        Reused dimensions keep their prior tier placement and cached scores, so a high reuse rate is
        expected once the pool’s dimension set has settled. Watch the individual matches below for a wrong mapping —
        that, not a high rate, is what would corrupt a prior tier or score.
      </p>

      <dl className="match-audit-stats">
        <div>
          {/* Post-decomposition settled set (what the match pass ran on), not raw
              discovery output — under fan-out those differ. */}
          <dt>Settled</dt>
          <dd>{audit.discoveredCount}</dd>
        </div>
        <div>
          <dt>Reused</dt>
          <dd>{audit.matchedCount}</dd>
        </div>
        <div>
          <dt>New</dt>
          <dd>{audit.newCount}</dd>
        </div>
        <div>
          <dt>Reuse rate</dt>
          <dd className="match-audit-rate">
            {firstRun || rate === null ? "—" : `${Math.round(rate * 100)}%`}
          </dd>
        </div>
      </dl>
      {firstRun ? (
        <p className="panel-hint">First run — no prior dimensions to match against, so reuse is N/A.</p>
      ) : null}

      <table className="match-audit-table">
        <thead>
          {/* Unified inputs → keeper layout: this run's settled dimension (candidate) on
              the left flows into the prior dimension it reuses (keeper) on the right —
              mirroring Decomposition and Consolidation. A row with no match is genuinely
              new, so the arrow flows into the "new" marker. */}
          <tr>
            <th>Settled dimension</th>
            <th aria-label="reuses" />
            <th>Reused from</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => {
            const matchedTo = audit.newToOld[d.key];
            return (
              <tr key={d.key}>
                <td>
                  {d.name}
                  {d.fromCommitteeRequest ? <span className="match-audit-tag">requested</span> : null}
                  <span className="match-audit-key">{d.key}</span>
                </td>
                <td className="match-audit-arrow" aria-hidden="true">→</td>
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
        <div className="observability-narrative">
          <span className="observability-label">Match reasoning</span>
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
