import { Plus, Printer, Star, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { bandClass, scoreBand } from "../format";
import type { RankingState, ScreeningRunState, Tier } from "../types";
import { TierList, TierSummaryForPrint } from "./TierList";

// The current run's discovered criteria — the axes scoring rates each candidate on
// — plus a composer for steering the NEXT run's discovery: star a dimension to keep
// it across re-runs (favourite), or describe an axis to propose. Both feed the next
// Rank's discovery as "strongly consider"; the AI may refine, split, or skip them.
// Shown above the list and the shortlist, not when a candidate is open.
export function CriteriaPanel(props: {
  screeningRun: ScreeningRunState;
  tiers: Tier[] | null;
  favouritedKeys: string[];
  proposedDimensions: string[];
  onToggleFavourite: (key: string, favourited: boolean) => void;
  onAddProposal: (text: string) => void;
  onRemoveProposal: (text: string) => void;
}): ReactNode {
  const { screeningRun } = props;
  // Default to [] so a run persisted before this feature (no seed fields) can't crash.
  const favouritedKeys = props.favouritedKeys ?? [];
  const proposedDimensions = props.proposedDimensions ?? [];
  const favourited = new Set(favouritedKeys);
  const [draft, setDraft] = useState("");

  // Order criteria most→least important by tier position (Ignore last), then
  // alphabetically by name within a tier — matching the tier list's chip order.
  const rankOf = new Map<string, number>();
  (props.tiers ?? []).forEach((tier, tierIdx) => {
    tier.dimension_keys.forEach((key) => rankOf.set(key, tierIdx));
  });
  const orderedDimensions = [...screeningRun.dimensions].sort((a, b) => {
    const tierDelta =
      (rankOf.get(a.key) ?? Number.MAX_SAFE_INTEGER) - (rankOf.get(b.key) ?? Number.MAX_SAFE_INTEGER);
    return tierDelta !== 0 ? tierDelta : a.name.localeCompare(b.name);
  });

  function submitDraft() {
    const text = draft.trim();
    if (!text) return;
    props.onAddProposal(text);
    setDraft("");
  }

  const seedCount = favourited.size + proposedDimensions.length;

  return (
    <details className="dimensions-panel">
      <summary>Screening criteria ({screeningRun.dimensions.length})</summary>
      <p className="dimensions-summary">{screeningRun.summary}</p>
      <ul className="dimensions-list">
        {orderedDimensions.map((dim) => {
          const isFav = favourited.has(dim.key);
          return (
            <li key={dim.key} className="dimension-item">
              <div className="dimension-head">
                <button
                  type="button"
                  className={`dimension-fav${isFav ? " is-fav" : ""}`}
                  aria-pressed={isFav}
                  title={isFav ? "Favourited — kept on re-run" : "Favourite — keep this axis on re-run"}
                  onClick={() => props.onToggleFavourite(dim.key, !isFav)}
                >
                  <Star size={14} fill={isFav ? "currentColor" : "none"} />
                </button>
                <span className="dimension-name">{dim.name}</span>
              </div>
              <p className="dimension-def">{dim.definition}</p>
              <p className="dimension-why">{dim.why_it_differentiates}</p>
            </li>
          );
        })}
      </ul>

      <div className="criteria-composer no-print">
        <h4>Suggest an axis to look for</h4>
        <p className="criteria-composer-hint">
          Describe a dimension you want considered. The next Rank offers it to the AI, which may refine, split, or skip
          it to fit the pool. Star a discovered criterion above to keep it across re-runs.
        </p>
        <div className="criteria-composer-row">
          <input
            type="text"
            value={draft}
            placeholder="e.g. school-age kids who'd use the playground"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submitDraft();
              }
            }}
          />
          <button type="button" className="secondary-button" onClick={submitDraft} disabled={!draft.trim()}>
            <Plus size={14} /> Add
          </button>
        </div>
        {proposedDimensions.length > 0 ? (
          <ul className="criteria-proposals">
            {proposedDimensions.map((text) => (
              <li key={text}>
                <span>{text}</span>
                <button
                  type="button"
                  className="criteria-proposal-remove"
                  aria-label="Remove proposal"
                  title="Remove"
                  onClick={() => props.onRemoveProposal(text)}
                >
                  <X size={12} strokeWidth={3} />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {seedCount > 0 ? (
          <p className="criteria-seed-note">
            Next Rank will offer the AI {seedCount} suggested {seedCount === 1 ? "axis" : "axes"} ({favourited.size}{" "}
            favourited, {proposedDimensions.length} proposed) — it may refine, split, or skip them.
          </p>
        ) : null}
      </div>
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
