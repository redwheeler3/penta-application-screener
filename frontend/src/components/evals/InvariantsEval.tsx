import { type ReactNode, useEffect, useState } from "react";
import { fetchEvalInvariants, rebaselineEval } from "../../api";
import type { InvariantsResult } from "../../types";
import { InlineConfirm } from "./InlineConfirm";

// The free, deterministic invariants over the committed baseline fixture. No run controls
// (they don't spend) — it loads on mount, and re-baselining (which re-records the fixture
// from the CURRENT Rank) updates it. Re-baseline is a deliberate write to a committed file,
// so it's confirmed inline (the styled card, not window.confirm). No "Refresh": the fixture
// only changes on a re-baseline, which already returns the fresh result.
export function InvariantsEval(): ReactNode {
  const [result, setResult] = useState<InvariantsResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [rebasing, setRebasing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchEvalInvariants()
      .then((r) => (r.ok ? r.json() : null))
      .then(setResult);
  }, []);

  async function rebaseline() {
    setConfirming(false);
    setRebasing(true);
    setError(null);
    const resp = await rebaselineEval();
    setRebasing(false);
    if (resp.ok) setResult(await resp.json());
    else {
      const problem = await resp.json().catch(() => null);
      setError(problem?.detail ?? `Re-baseline failed (${resp.status})`);
    }
  }

  return (
    <div className="eval-section">
      <p className="eval-card-desc">
        Deterministic checks over the committed baseline fixture — every dimension has both
        poles, none keys on a protected attribute. Free and instant; a breach is always a bug
        (these gate CI). Re-baseline re-records the fixture from the current Rank.
      </p>

      {confirming ? (
        <InlineConfirm
          title="Re-baseline from the current Rank?"
          body="This overwrites the committed baseline fixture (rank_baseline.json) with the current run's output. Do it only after confirming that output is good — then commit the file to git."
          confirmLabel="Re-baseline"
          onConfirm={rebaseline}
          onCancel={() => setConfirming(false)}
        />
      ) : null}

      <div className="eval-section-actions">
        <button type="button" className="secondary-button" onClick={() => setConfirming(true)} disabled={rebasing}>
          {rebasing ? "Re-baselining…" : "Re-baseline from current Rank"}
        </button>
      </div>

      {error ? <p className="eval-error">{error}</p> : null}
      {result === null ? (
        <p className="eval-hint">Loading…</p>
      ) : result.hasFixture === false ? (
        <p className="eval-hint">No baseline fixture recorded yet — re-baseline from a completed Rank to create one.</p>
      ) : (
        <div className="eval-result">
          <div className="eval-headline">{result.dimensions} dimensions in the baseline</div>
          {result.invariants.map((inv) => (
            <div key={inv.check} className={`eval-invariant ${inv.passed ? "ok" : "fail"}`}>
              <span className="eval-invariant-mark">{inv.passed ? "✓" : "✗"}</span>
              <span className="eval-invariant-name">{inv.check}</span>
              {inv.violations.length ? (
                <div className="eval-invariant-violations">
                  {inv.violations.map((v) => (
                    <div key={v} className="eval-check-detail">
                      {v}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
