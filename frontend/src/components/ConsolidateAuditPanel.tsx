import { type ReactNode, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchConsolidateAudit } from "../api";
import type { ConsolidateAuditResponse } from "../types";

// Post-score consolidation observability: how the run healed duplicate dimensions the
// pre-score match pass couldn't catch. After scoring, two dimensions whose per-applicant
// scores move together are NOMINATED as suspected duplicates (Pearson r); a confirm call
// then judges each by its definition and MERGES only genuine duplicates (the older key is
// kept, the newer aliased into it so future runs adopt it too). Distinct axes that merely
// correlate — a confound — are kept apart.
//
// This surfaces every nominated pair, its correlation, the merge/keep verdict + reason,
// and the confirm call's reasoning. A null audit (a run from before the pass) shows an
// explicit empty state; a run where correlation nominated nothing shows the no-op state.
export function ConsolidateAuditPanel(): ReactNode {
  const [audit, setAudit] = useState<ConsolidateAuditResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    fetchConsolidateAudit()
      .then((a) => live && (setAudit(a), setState("ready")))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  if (state === "loading") return <p className="match-audit-hint">Loading…</p>;
  if (state === "error") return <p className="match-audit-hint">Couldn’t load the consolidation audit.</p>;
  if (audit === null) {
    return (
      <p className="match-audit-hint">
        No consolidation audit for this run — it predates the post-score duplicate-merge
        pass. Re-rank to populate it.
      </p>
    );
  }
  if (audit.nominatedCount === 0) {
    return (
      <p className="match-audit-hint">
        No duplicate dimensions to consolidate this run — no pair of dimensions scored
        applicants similarly enough to be flagged. (This is the common, healthy case.)
      </p>
    );
  }
  return <ConsolidateAuditBody audit={audit} />;
}

function ConsolidateAuditBody(props: { audit: ConsolidateAuditResponse }): ReactNode {
  const { audit } = props;
  return (
    <div className="match-audit">
      <p className="match-audit-hint">
        {audit.nominatedCount} dimension pair{audit.nominatedCount === 1 ? "" : "s"} scored
        applicants similarly enough to be flagged as possible duplicates; {audit.mergedCount}{" "}
        {audit.mergedCount === 1 ? "was" : "were"} confirmed the same concept and merged (the
        older key kept, the newer folded into it). The rest are distinct axes that merely
        correlate, kept apart.
      </p>

      <dl className="match-audit-stats">
        <div>
          <dt>Nominated</dt>
          <dd>{audit.nominatedCount}</dd>
        </div>
        <div>
          <dt>Merged</dt>
          <dd>{audit.mergedCount}</dd>
        </div>
      </dl>

      <table className="match-audit-table">
        <thead>
          <tr>
            <th>Pair</th>
            <th>Correlation</th>
            <th>Verdict</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {audit.pairs.map((p) => (
            <tr key={`${p.keep}:${p.drop}`}>
              <td>
                <div className="consolidate-pair">
                  {/* Always the candidate merge direction (newer → older); the Verdict
                      column says whether it actually merged. */}
                  <code className="consolidate-pair-key">{p.drop}</code>
                  <span className="consolidate-pair-sep">→</span>
                  <code className="consolidate-pair-key">{p.keep}</code>
                </div>
              </td>
              <td>r={p.r.toFixed(2)}</td>
              <td>
                {p.merged ? (
                  <span className="match-audit-new">merged</span>
                ) : (
                  <span className="match-audit-key-unnamed">kept apart</span>
                )}
              </td>
              <td>{p.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {audit.narrative ? (
        <div className="insights-narrative">
          <span className="insights-label">Consolidation reasoning</span>
          <div className="ai-narrative">
            <ReactMarkdown>{audit.narrative}</ReactMarkdown>
          </div>
        </div>
      ) : null}
    </div>
  );
}
