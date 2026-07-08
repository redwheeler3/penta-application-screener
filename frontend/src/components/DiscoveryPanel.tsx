import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { CurrentRunResponse } from "../types";

// The discovery half of the run-level axis (M13): what pattern discovery emitted for
// this run — the pool summary, the full set of differentiating dimensions (each with
// its definition and why-it-differentiates rationale), and the model's reasoning. The
// ranked view shows the dimensions as tap-to-read chips (a control); here they're a
// readable trace so an operator can inspect what the model found in the pool this run.
//
// Reads the current run (already loaded by the app, no extra fetch). The keys shown are
// post-match — a matched dimension carries its prior key — which is intentional: this
// panel answers "what does the model consider this run?", and the carry-forward panel
// answers "what changed from last run?".
export function DiscoveryPanel(props: { run: CurrentRunResponse }): ReactNode {
  const { run } = props;
  const newKeys = new Set(run.newDimensionKeys);
  return (
    <div className="discovery-audit">
      {run.summary ? (
        <div className="discovery-summary">
          <span className="insights-label">Pool summary</span>
          <p>{run.summary}</p>
        </div>
      ) : null}

      <ol className="discovery-dimensions">
        {run.dimensions.map((d) => (
          <li key={d.key} className="discovery-dimension">
            <div className="discovery-dimension-head">
              <span className="discovery-dimension-name">{d.name}</span>
              {newKeys.has(d.key) ? <span className="match-audit-new">new</span> : null}
              <span className="match-audit-key">{d.key}</span>
            </div>
            <p className="discovery-dimension-def">{d.definition}</p>
            {d.whyItDifferentiates ? (
              <p className="discovery-dimension-why">
                <span className="discovery-why-label">Why it differentiates:</span> {d.whyItDifferentiates}
              </p>
            ) : null}
          </li>
        ))}
      </ol>

      {/* Model reasoning, rendered inline (matching the carry-forward panel's
          treatment) so "reasoning" behaves the same in both sections. */}
      {run.discoveryNarrative ? (
        <div className="insights-narrative">
          <span className="insights-label">Model reasoning</span>
          <div className="ai-narrative">
            <ReactMarkdown>{run.discoveryNarrative}</ReactMarkdown>
          </div>
        </div>
      ) : null}
    </div>
  );
}
