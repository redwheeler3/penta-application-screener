import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { fetchFanOutAudit } from "../api";
import { useFetchOnce } from "../hooks/useFetchOnce";
import type { CurrentRunResponse } from "../types";

// The discovery half of the run-level axis (M13 + Fan-Out Redesign): what the K
// parallel discoverers each found and why. Each pass is one fresh-context discovery;
// their cross-call variation is the diversity the decomposition step later settles, so
// seeing all K side by side (not just the one that streamed live) is what makes the
// fan-out — and the merges it feeds — legible.
//
// One collapsible per discoverer: its dimensions (the comparison signal — who found
// what) plus its reasoning. Self-fetches the fan-out audit (mount-once via useFetchOnce;
// the caller keys this by runId so a run change remounts and re-fetches). Falls back to the
// single run-level narrative for runs that predate the fan-out (no per-pass audit).
export function DiscoveryPanel(props: { run: CurrentRunResponse }): ReactNode {
  const { data: audit, state } = useFetchOnce(fetchFanOutAudit);

  if (state === "loading") return <p className="panel-hint">Loading…</p>;
  if (state === "error") return <p className="panel-hint">Couldn’t load discovery.</p>;

  // Legacy runs (pre fan-out) have no per-pass audit — fall back to the single narrative.
  if (audit === null || audit.passes.length === 0) {
    if (!props.run.discoveryNarrative) {
      return <p className="panel-hint">No discovery reasoning recorded for this run.</p>;
    }
    return (
      <div className="discovery-audit">
        <div className="insights-narrative">
          <span className="insights-label">Model reasoning</span>
          <div className="ai-narrative">
            <ReactMarkdown>{props.run.discoveryNarrative}</ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="discovery-audit">
      <p className="panel-hint">
        {audit.k} parallel discovery passes ran on this pool; their differing takes are
        settled into one set by decomposition (see the Decomposition tab). Each found the
        axes below independently — the overlaps and the gaps are the fan-out at work.
      </p>
      {audit.passes.map((pass, i) => (
        <details key={i} className="discovery-pass">
          <summary className="discovery-pass-summary">
            Discoverer {i + 1}
            <span className="discovery-pass-count">{pass.dimensions.length} dimensions</span>
          </summary>
          <div className="discovery-pass-body">
            <ul className="discovery-pass-dims">
              {pass.dimensions.map((d) => (
                <li key={d.key}>
                  <span className="discovery-pass-dim-name">{d.name}</span>
                  <span className="discovery-pass-dim-def">{d.definition}</span>
                </li>
              ))}
            </ul>
            {pass.narrative ? (
              <div className="insights-narrative">
                <span className="insights-label">Reasoning</span>
                <div className="ai-narrative">
                  <ReactMarkdown>{pass.narrative}</ReactMarkdown>
                </div>
              </div>
            ) : (
              <p className="panel-hint discovery-pass-no-reasoning">
                Reasoning wasn’t recorded for this run — re-rank to capture it.
              </p>
            )}
          </div>
        </details>
      ))}
    </div>
  );
}
