import { useCommitteeApi } from "../../api/identity";
import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import * as rankingApi from "../../api/ranking";
import { AnalysisTraceResource } from "./AnalysisTraceResource";
import type { AnalysisTraceScope, FanOutAuditResponse } from "../../types";

// Show each independent discovery pass and its reasoning. When per-pass data is absent,
// fall back to the run-level narrative.
export function DiscoveryPanel(props: { scope: AnalysisTraceScope }): ReactNode {
  const { fetchFanOutAudit } = useCommitteeApi(rankingApi);

  return <AnalysisTraceResource scope={props.scope}
    fetcher={() => fetchFanOutAudit(props.scope.openingId, props.scope.analysisId)}>
    {(audit) => <DiscoveryBody audit={audit} />}
  </AnalysisTraceResource>;
}

function DiscoveryBody({ audit }: { audit: FanOutAuditResponse | null }): ReactNode {
  if (audit === null || audit.passes.length === 0) {
    if (!audit?.narrative) {
      return <p className="panel-hint">No discovery reasoning recorded for this run.</p>;
    }
    return (
      <div className="discovery-audit">
        <div className="observability-narrative">
          <span className="observability-label">Model reasoning</span>
          <div className="ai-narrative">
            <ReactMarkdown>{audit?.narrative}</ReactMarkdown>
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
              <div className="observability-narrative">
                <span className="observability-label">Reasoning</span>
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
