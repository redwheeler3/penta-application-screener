import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { fetchMatchAudit } from "../api";
import { useFetchOnce } from "../hooks/useFetchOnce";
import type { MatchAuditResponse } from "../types";

// M13 per-run AI legibility: the reuse audit for the current run. Surfaces the
// settled dimensions (post-decomposition, pre key-adoption), how the match pass mapped
// each onto a prior-run dimension it reuses, and the derived reuse rate. Under the fan-out
// redesign a high rate is EXPECTED (the dimension set has stabilised); the audit's real
// job is letting a human eyeball individual matches for a wrong mapping, without a
// SQLite spelunk.
//
// Self-fetches on mount. Rendered as the active Insights subtab, so an absent audit
// (a first run, or a run from before capture) shows an explicit empty state rather
// than vanishing — "nothing carried forward" is information, not a broken panel.
export function MatchAuditPanel(): ReactNode {
  const { data: audit, state } = useFetchOnce(fetchMatchAudit);

  if (state === "loading") return <p className="match-audit-hint">Loading…</p>;
  if (state === "error") return <p className="match-audit-hint">Couldn’t load the matching audit.</p>;
  if (audit === null) {
    return (
      <p className="match-audit-hint">
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
  // No alarm colouring on the rate: under the fan-out redesign a HIGH reuse rate is
  // expected and good — it means the settled dimension set has stabilised run-to-run
  // (and re-ranks stay cheap, reusing tiers + scores). The thing that would signal
  // over-matching is a WRONG match — visible in the table/narrative below, not in the
  // aggregate rate, which can't tell "correctly stable" from "wrongly matched".

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
      <p className="match-audit-hint">
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
        <p className="match-audit-hint">First run — no prior dimensions to match against, so reuse is N/A.</p>
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
