import { type ReactNode, useState } from "react";
import { harvestEvalCases } from "../../api";

// "Harvest from current run" — the fidelity-preserving path for turning the current Rank's
// scoring/screening output into candidate judge cases (opaque-indexed, synthetic-pool
// gated server-side). Proposes UNLABELLED candidates; clicking one opens it in the case
// editor to set `expected` + `label_rationale` before saving. Capture never labels — the
// human does, in the editor. Candidates already in the judge set are dropped server-side.
//
// Collapsed by default (it's an occasional action). On expand it fetches both families and
// shows a flat, grouped review list. Guard failures (no current run; non-synthetic pool)
// surface as a plain message — harvesting a real pool's evidence quotes is refused.
export function HarvestPanel(props: {
  onEditCandidate: (candidate: Record<string, unknown>) => void;
}): ReactNode {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<{ family: string; cases: Record<string, unknown>[] } | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setCandidates(null);
    // Fetch both families; a family with nothing to harvest just contributes an empty list.
    const families = ["scoring", "screening"] as const;
    const all: Record<string, unknown>[] = [];
    for (const family of families) {
      const resp = await harvestEvalCases(family);
      if (!resp.ok) {
        const problem = await resp.json().catch(() => null);
        setError(problem?.detail ?? `Harvest failed (${resp.status})`);
        setLoading(false);
        return;
      }
      const body = await resp.json();
      all.push(...body.candidates);
    }
    setCandidates({ family: "all", cases: all });
    setLoading(false);
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && candidates === null) void load();
  }

  return (
    <div className="eval-harvest">
      <button type="button" className="eval-harvest-toggle" onClick={toggle}>
        {open ? "▾" : "▸"} Harvest cases from current run
      </button>
      {open ? (
        <div className="eval-harvest-body">
          <p className="eval-hint">
            Proposes candidate judge cases from the current Rank’s scoring and screening
            output — the fidelity-preserving way to turn real model output into eval cases
            (only allowed on a synthetic pool). Pick a candidate to label its verdict and save.
          </p>
          {loading ? <p className="eval-hint">Harvesting…</p> : null}
          {error ? <p className="eval-error">{error}</p> : null}
          {candidates && !loading ? (
            candidates.cases.length === 0 ? (
              <p className="eval-hint">No new candidates — every scoring/screening result is already a case.</p>
            ) : (
              <ul className="eval-harvest-list">
                {candidates.cases.map((c) => (
                  <li key={String(c.key)}>
                    <button type="button" className="eval-harvest-item" onClick={() => props.onEditCandidate(c)}>
                      <span className="eval-harvest-pass">{String(c.pass ?? "")}</span>
                      <span className="eval-harvest-title">{String(c.title ?? c.key)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
