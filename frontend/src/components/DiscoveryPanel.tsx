import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { CurrentRunResponse } from "../types";

// The discovery half of the run-level axis (M13): the model's reasoning behind the
// dimensions it found this run. Deliberately ONLY the reasoning — observability must
// not duplicate product content. The dimensions (name, definition, why-it-differentiates)
// and the pool summary both live on the Ranking tab, so the reasoning narrative is the
// only discovery artifact with no other home.
export function DiscoveryPanel(props: { run: CurrentRunResponse }): ReactNode {
  const { run } = props;
  if (!run.discoveryNarrative) {
    return <p className="match-audit-hint">No discovery reasoning recorded for this run.</p>;
  }
  return (
    <div className="discovery-audit">
      <div className="insights-narrative">
        <span className="insights-label">Model reasoning</span>
        <div className="ai-narrative">
          <ReactMarkdown>{run.discoveryNarrative}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
