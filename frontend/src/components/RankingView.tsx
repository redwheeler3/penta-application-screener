import { Printer } from "lucide-react";
import { type ReactNode } from "react";
import { bandClass, scoreBand } from "../format";
import type { RankingState, ScreeningRunState, Tier } from "../types";
import { TierList, TierSummaryForPrint } from "./TierList";

// The current run's discovered criteria — the axes scoring rates each candidate
// on. Shown above the list and the shortlist, not when a candidate is open.
export function CriteriaPanel(props: { screeningRun: ScreeningRunState; tiers: Tier[] | null }): ReactNode {
  // Order criteria most→least important by tier position (Ignore last; discovery
  // order within a tier), falling back to discovery order.
  const rankOf = new Map<string, number>();
  (props.tiers ?? []).forEach((tier, tierIdx) => {
    tier.dimension_keys.forEach((key) => rankOf.set(key, tierIdx));
  });
  const orderedDimensions = [...props.screeningRun.dimensions].sort(
    (a, b) =>
      (rankOf.get(a.key) ?? Number.MAX_SAFE_INTEGER) - (rankOf.get(b.key) ?? Number.MAX_SAFE_INTEGER),
  );
  return (
    <details className="dimensions-panel">
      <summary>Screening criteria ({props.screeningRun.dimensions.length})</summary>
      <p className="dimensions-summary">{props.screeningRun.summary}</p>
      <ul className="dimensions-list">
        {orderedDimensions.map((dim) => (
          <li key={dim.key} className="dimension-item">
            <div className="dimension-head">
              <span className="dimension-name">{dim.name}</span>
            </div>
            <p className="dimension-def">{dim.definition}</p>
            <p className="dimension-why">{dim.why_it_differentiates}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}

// The ranked shortlist: a decision surface, not a browse table. The order IS the
// product — read top-down. The band label and rationale lead; numbers are detail.
export function RankingView(props: {
  ranking: RankingState;
  screeningRun: ScreeningRunState | null;
  tiers: Tier[] | null;
  onSaveTiers: (next: Tier[]) => void;
  onAcknowledgeNew: (keys: string[]) => void;
  onSelectApplication: (id: number) => void;
}): ReactNode {
  const { ranking, screeningRun, tiers } = props;
  const labelFor = (key: string) => screeningRun?.dimensions.find((d) => d.key === key)?.name ?? key;

  return (
    <div className="ranking-view">
      <div className="ranking-header">
        <div>
          <h3>Candidate ranking</h3>
          <p className="ranking-subhead">
            {ranking.scoredCount} candidate{ranking.scoredCount === 1 ? "" : "s"} scored, ranked by overall fit. Drag
            criteria into importance tiers below to re-rank.
          </p>
        </div>
        <button type="button" className="secondary-button no-print" onClick={() => window.print()}>
          <Printer size={16} />
          Print
        </button>
      </div>

      {/* Tier-list: drag criteria into importance tiers; the ranking re-sorts on
          each edit (deterministic, no model call). */}
      {tiers && screeningRun ? (
        <>
          <TierList
            tiers={tiers}
            labelFor={labelFor}
            // Read from ranking (refreshed on every save) so badges clear
            // immediately when a dimension is placed or acknowledged.
            newKeys={new Set(ranking.newDimensionKeys)}
            onAcknowledge={props.onAcknowledgeNew}
            onChange={props.onSaveTiers}
          />
          <TierSummaryForPrint tiers={tiers} labelFor={labelFor} />
        </>
      ) : null}

      {ranking.candidates.length === 0 ? (
        <div className="empty-state">
          <p>No scored candidates to rank yet. Run scoring first.</p>
        </div>
      ) : (
        <ol className="ranking-list">
          {ranking.candidates.map((candidate) => {
            // Lead with what most moved this candidate's rank — by |impact|, not raw
            // weight×score — so a heavy strike surfaces as readily as a strength.
            // The score band's colour says which is which.
            const topContributions = [...candidate.contributions]
              .filter((c) => c.weight > 0)
              .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))
              .slice(0, 3);
            return (
              <li key={candidate.application_id}>
                <div className="ranking-row" onClick={() => props.onSelectApplication(candidate.application_id)}>
                  <span className="ranking-rank">#{candidate.rank}</span>
                  <div className="ranking-main">
                    <div className="ranking-name-row">
                      <span className="ranking-name">{candidate.name || "Unnamed applicant"}</span>
                      <span className={`fit-band band-${bandClass(candidate.band)}`}>{candidate.band}</span>
                    </div>
                    <div className="ranking-contributions">
                      {topContributions.map((c) => {
                        const sb = scoreBand(c.score);
                        return (
                          <p key={c.dimension_key} className="ranking-contribution">
                            <span className={`ranking-contribution-label ${sb.cls}`}>
                              {c.name} ({sb.label}){c.rationale ? ":" : ""}
                            </span>
                            {c.rationale ? ` ${c.rationale}` : null}
                          </p>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
