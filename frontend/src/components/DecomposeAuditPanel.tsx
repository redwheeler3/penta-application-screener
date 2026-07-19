import { type ReactNode, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchDecomposeAudit } from "../api";
import type { DecomposeAuditResponse } from "../types";

// Fan-Out Redesign observability: how the K parallel discovery reports were settled
// into one non-overlapping dimension set for the current run. K fresh-context
// discoveries carve the pool at different, overlapping granularities; decomposition
// distils them into the finest set of axes that each differentiate AND don't overlap —
// collapsing re-carvings of one concept, keeping genuinely distinct axes apart.
//
// This surfaces the settle-down (how many input axes → how many settled), which settled
// axes are MERGES (more than one source), the model's per-axis reasoning, and the D9
// trail: any committee-requested axis folded into another is shown explicitly, so a
// fold is visible, never a silent disappearance.
//
// Self-fetches on mount. A null audit (a run from before the fan-out redesign) shows an
// explicit empty state, not a broken panel.
export function DecomposeAuditPanel(): ReactNode {
  const [audit, setAudit] = useState<DecomposeAuditResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    fetchDecomposeAudit()
      .then((a) => live && (setAudit(a), setState("ready")))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  if (state === "loading") return <p className="match-audit-hint">Loading…</p>;
  if (state === "error") return <p className="match-audit-hint">Couldn’t load the decomposition audit.</p>;
  if (audit === null) {
    return (
      <p className="match-audit-hint">
        No decomposition audit for this run — it predates the fan-out redesign (a single
        discovery run, not K parallel reports settled into one set). Re-rank to populate it.
      </p>
    );
  }
  return <DecomposeAuditBody audit={audit} />;
}

function DecomposeAuditBody(props: { audit: DecomposeAuditResponse }): ReactNode {
  const { audit } = props;
  // Map each settled axis's key → the request it folded in (for the D9 badge).
  const foldedInto = new Map(audit.foldedRequests.map((f) => [f.intoKey, f.requestKey]));

  // Kept-as-is axes (one source) first, merges after — the merges are the interesting,
  // heavier rows, so grouping them below keeps the plain carry-throughs from being
  // visually interrupted. Within each group, committee-requested axes lead so the
  // committee can find its own asks first. Stable sort preserves the model's order
  // within each (group, origin) bucket.
  const settled = [...audit.settled].sort(
    (a, b) =>
      Number(a.sourceKeys.length > 1) - Number(b.sourceKeys.length > 1) ||
      Number(!!b.fromCommitteeRequest) - Number(!!a.fromCommitteeRequest),
  );

  return (
    <div className="match-audit">
      <p className="match-audit-hint">
        {audit.inputReportCount} parallel discovery reports ({audit.inputDimensionCount} axes in
        total) were settled into {audit.settledCount} non-overlapping dimensions. A “merge” folds
        several re-carvings of one concept into a single axis.
      </p>

      <dl className="match-audit-stats">
        <div>
          <dt>Reports</dt>
          <dd>{audit.inputReportCount}</dd>
        </div>
        <div>
          <dt>Input axes</dt>
          <dd>{audit.inputDimensionCount}</dd>
        </div>
        <div>
          <dt>Settled</dt>
          <dd>{audit.settledCount}</dd>
        </div>
        <div>
          <dt>Merges</dt>
          <dd>{audit.mergeCount}</dd>
        </div>
      </dl>

      {audit.foldedRequests.length > 0 ? (
        <p className="match-audit-hint decompose-folded-note">
          <strong>Committee requests folded into another axis:</strong>{" "}
          {audit.foldedRequests.map((f) => `${f.requestKey} → ${f.intoKey}`).join(", ")}. These
          were not dropped — they are captured inside the settled axis shown below.
        </p>
      ) : null}

      <table className="match-audit-table">
        <thead>
          {/* Unified inputs → keeper layout: the source axes (candidates) on the left flow
              into the settled dimension (keeper) on the right, mirroring Matching and
              Consolidation. */}
          <tr>
            <th>Source axes</th>
            <th aria-label="settles into" />
            <th>Settled dimension</th>
            {/* Whether this axis folded several re-carvings together (merged) or is one
                source carried through (distinct) — the decomposition analogue of the
                Consolidation tab's Verdict column. */}
            <th>Verdict</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {settled.map((d) => {
            const isMerge = d.sourceKeys.length > 1;
            const folded = foldedInto.get(d.key);
            return (
              <tr key={d.key}>
                <td>
                  {d.sourceKeys.map((k) => {
                    // Which discoverer(s) coined this source key — "R0, R3" — so the
                    // committee can see independent re-discovery vs. a single origin.
                    const reports = d.sourceReportMap[k] ?? [];
                    // The source's own name (name + key, like Matching); absent when the
                    // fan-out wasn't captured, so we fall back to just the key below.
                    const sourceName = d.sourceNames[k];
                    return (
                      <div key={k} className="decompose-source">
                        {sourceName ? sourceName : null}
                        <span className="match-audit-key">
                          {k}
                          {reports.length > 0 ? (
                            <span className="decompose-source-reports">
                              {" "}
                              ({reports.map((i) => `R${i}`).join(", ")})
                            </span>
                          ) : null}
                        </span>
                      </div>
                    );
                  })}
                </td>
                <td className="match-audit-arrow" aria-hidden="true">→</td>
                <td>
                  {/* Name + key (mirroring the Matching tab), then the request / folded-in
                      attribute tags (each spaced off the name with .decompose-tag). The
                      merged/distinct verdict lives in its own column. */}
                  {d.name}
                  {d.fromCommitteeRequest ? (
                    <span className="decompose-tag decompose-requested-tag" title="This dimension was requested by the committee">
                      <span className="decompose-requested-glyph" aria-hidden="true">★</span>
                      Committee
                    </span>
                  ) : null}
                  {folded ? (
                    <span className="decompose-tag match-audit-key-unnamed" title="A committee request folded in here">
                      folded in: {folded}
                    </span>
                  ) : null}
                  <span className="match-audit-key">{d.key}</span>
                </td>
                <td>
                  {isMerge ? (
                    <span className="match-audit-new">merged</span>
                  ) : (
                    // One source, nothing to fold — a distinct axis. "distinct" mirrors the
                    // Consolidation tab's language for its non-merged rows.
                    <span className="match-audit-key-unnamed">distinct</span>
                  )}
                </td>
                <td>{d.decision}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {audit.narrative ? (
        <div className="insights-narrative">
          <span className="insights-label">Decomposition reasoning</span>
          <div className="ai-narrative">
            <ReactMarkdown>{audit.narrative}</ReactMarkdown>
          </div>
        </div>
      ) : null}
    </div>
  );
}
