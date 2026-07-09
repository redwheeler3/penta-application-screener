import { type ReactNode, useEffect, useState } from "react";
import { fetchReconcileAudit } from "../api";
import type { ReconcileAuditResponse } from "../types";

// M13 per-run AI legibility: the reconcile pass's audit for the current run. Reconcile
// takes the dropped prior dimensions (the ones the match pass did NOT carry forward)
// and asks, against the live pool, "does this pool still vary on it?" — reviving only
// those it does. This surfaces the full ballot (a verdict + reasoning per dropped
// dimension) and the recovery rate — the signal that answers "is reconcile
// over-reviving?" (RQ8) without a SQLite spelunk. "No" is the expected answer for
// most, so a HIGH recovery rate is the smell, mirroring the match pass's over-match rate.
//
// Self-fetches on mount. An absent audit (first run, nothing dropped, or a run from
// before capture) shows an explicit empty state — "nothing to reconcile" is
// information, not a broken panel.
export function ReconcileAuditPanel(): ReactNode {
  const [audit, setAudit] = useState<ReconcileAuditResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    fetchReconcileAudit()
      .then((a) => live && (setAudit(a), setState("ready")))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  if (state === "loading") return <p className="match-audit-hint">Loading…</p>;
  if (state === "error") return <p className="match-audit-hint">Couldn’t load the reconcile audit.</p>;
  if (audit === null) {
    return (
      <p className="match-audit-hint">
        No reconcile audit for this run — nothing was dropped to reconcile (a first run, or every prior dimension
        carried forward), or it predates audit capture. Re-rank to populate it.
      </p>
    );
  }
  return <ReconcileAuditBody audit={audit} />;
}

function ReconcileAuditBody(props: { audit: ReconcileAuditResponse }): ReactNode {
  const { audit } = props;
  const rate = audit.recoveryRate;
  // A high recovery rate is the over-recovery smell (reconcile reviving too readily),
  // flagged visually. Reuses the match-audit rate bands (blue→amber→red), but the
  // healthy direction is inverted: here LOW is good ("no" is expected for most).
  const rateClass =
    rate === null ? "" : rate >= 0.6 ? " match-audit-rate-high" : rate >= 0.3 ? " match-audit-rate-mid" : "";

  return (
    <div className="match-audit">
      <p className="match-audit-hint">
        Dropped dimensions (not carried forward by the match pass) are re-checked against the live pool; only those
        the pool still varies on are revived. “No” is expected for most, so a persistently high recovery rate can
        mean reconcile is over-reviving.
      </p>

      <dl className="match-audit-stats">
        <div>
          <dt>Offered</dt>
          <dd>{audit.offeredCount}</dd>
        </div>
        <div>
          <dt>Revived</dt>
          <dd>{audit.recoveredCount}</dd>
        </div>
        <div>
          <dt>Recovery rate</dt>
          <dd className={`match-audit-rate${rateClass}`}>
            {rate === null ? "—" : `${Math.round(rate * 100)}%`}
          </dd>
        </div>
      </dl>

      <table className="match-audit-table">
        <thead>
          <tr>
            <th>Dropped dimension</th>
            <th>Verdict</th>
            <th>Reasoning</th>
          </tr>
        </thead>
        <tbody>
          {audit.verdicts.map((v) => (
            <tr key={v.oldKey}>
              <td>
                <span className="match-audit-key">{v.oldKey}</span>
              </td>
              <td>
                {v.revive ? (
                  <span className="match-audit-new">revived</span>
                ) : (
                  <span className="match-audit-key-unnamed">declined</span>
                )}
              </td>
              <td>{v.reasoning}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
