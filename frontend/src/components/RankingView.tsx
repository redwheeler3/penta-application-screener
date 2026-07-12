import { Plus, Printer, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { bandClass, scoreBand } from "../format";
import type { RankingResponse, CurrentRunResponse, PoolDimension, Tier } from "../types";
import { TierList, TierSummaryForPrint } from "./TierList";

// The always-visible description pane beside the tiers. Shows the tapped criterion's
// name + definition (the bulky text, kept out of the chips themselves); when nothing
// is selected it shows a short prompt so the column never reads as broken/empty.
function CriteriaDetail(props: { dim: PoolDimension | null }): ReactNode {
  if (!props.dim) {
    return (
      <div className="criteria-detail criteria-detail-empty" role="region" aria-label="Criterion description">
        <p className="criteria-detail-placeholder">Tap a criterion to read what it measures.</p>
      </div>
    );
  }
  return (
    <div className="criteria-detail" role="region" aria-label={`${props.dim.name} — what it measures`}>
      <span className="dimension-name">{props.dim.name}</span>
      <p className="dimension-def">{props.dim.definition}</p>
      {props.dim.whyItDifferentiates ? (
        <p className="dimension-why">
          <span className="dimension-why-label">Why it differentiates:</span> {props.dim.whyItDifferentiates}
        </p>
      ) : null}
    </div>
  );
}

// The "add your own" composer + the pending-proposal list.
// Steers the NEXT run's discovery: a proposal (free text) or a ★ favourite both feed
// the next Rank as "strongly consider"; the AI may refine, split, or skip them.
function CriteriaComposer(props: {
  proposedDimensions: string[];
  onAddProposal: (text: string) => void;
  onRemoveProposal: (text: string) => void;
}): ReactNode {
  const [draft, setDraft] = useState("");
  function submitDraft() {
    const text = draft.trim();
    if (!text) return;
    props.onAddProposal(text);
    setDraft("");
  }
  return (
    <div className="criteria-composer no-print">
      <p className="criteria-composer-hint">
        Describe a dimension you want considered. Re-ranking offers it to the AI, which may refine, split, or skip
        it to fit the pool.
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
      {props.proposedDimensions.length > 0 ? (
        <ul className="criteria-proposals">
          {props.proposedDimensions.map((text) => (
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
    </div>
  );
}

// The ranked shortlist: a decision surface, not a browse table. The order IS the
// product — read top-down. The band label and rationale lead; numbers are detail.
export function RankingView(props: {
  ranking: RankingResponse;
  rankingRun: CurrentRunResponse | null;
  tiers: Tier[] | null;
  favouritedKeys: string[];
  proposedDimensions: string[];
  onSaveTiers: (next: Tier[]) => void;
  onAcknowledgeNew: (keys: string[]) => void;
  onToggleFavourite: (key: string, favourited: boolean) => void;
  onAddProposal: (text: string) => void;
  onRemoveProposal: (text: string) => void;
  onSelectApplication: (id: number) => void;
}): ReactNode {
  const { ranking, rankingRun, tiers } = props;
  const labelFor = (key: string) => rankingRun?.dimensions.find((d) => d.key === key)?.name ?? key;
  // Default to [] so a run persisted before the seed feature can't crash.
  const favourited = new Set(props.favouritedKeys ?? []);
  const proposedDimensions = props.proposedDimensions ?? [];
  // Which criterion's description is open (one at a time, shown below the tiers), and
  // whether the "add your own" composer is revealed. The criteria live as the tier
  // chips, which drive this on-demand reading/adding.
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const openDim = openKey ? rankingRun?.dimensions.find((d) => d.key === openKey) ?? null : null;

  return (
    <div className="ranking-view">
      <div className="ranking-header">
        <div>
          <h3>Candidate ranking</h3>
          <p className="ranking-subhead">
            Drag criteria into importance tiers to re-rank; tap a criterion to read what it measures, or star it
            to keep it when you re-rank.
          </p>
        </div>
        <button type="button" className="secondary-button no-print" onClick={() => window.print()}>
          <Printer size={16} />
          Print
        </button>
      </div>

      {/* Tier-list: drag criteria into importance tiers; the ranking re-sorts on each
          edit (deterministic, no model call). The criteria's descriptions, ★ favourite,
          and "add your own" composer are folded in here (no separate criteria panel). */}
      {tiers && rankingRun ? (
        <>
          <p className="criteria-head-title no-print">
            This ranking weighs {rankingRun.dimensions.length} criteria
          </p>
          {/* Tier list + the always-visible description side by side: the description
              sits to the RIGHT of the tiers (not below, where it scrolled out of
              view) so tapping a chip shows its text without leaving the dragger. The
              "Add criterion" composer + "Add tier" both live in the tier-list head. */}
          <div className="criteria-layout">
            <div className="criteria-layout-tiers">
              <TierList
                tiers={tiers}
                labelFor={labelFor}
                // Read from ranking (refreshed on every save) so badges clear
                // immediately when a dimension is placed or acknowledged.
                newKeys={new Set(ranking.newDimensionKeys)}
                revivedKeys={new Set(ranking.revivedDimensionKeys)}
                favourited={favourited}
                openKey={openKey}
                addOpen={addOpen}
                onToggleAdd={() => setAddOpen((v) => !v)}
                composer={
                  <CriteriaComposer
                    proposedDimensions={proposedDimensions}
                    onAddProposal={props.onAddProposal}
                    onRemoveProposal={props.onRemoveProposal}
                  />
                }
                onAcknowledge={props.onAcknowledgeNew}
                onChange={props.onSaveTiers}
                onToggleFav={props.onToggleFavourite}
                // Selecting a criterion just sets it (never toggles back to empty),
                // so a click that also nudges the drag sensor can't end up clearing
                // the panel — and the description stays put when re-tapped.
                onOpen={(key) => setOpenKey(key)}
              />
            </div>
            <CriteriaDetail dim={openDim} />
          </div>
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
              <li key={candidate.applicationId}>
                <div className="ranking-row" onClick={() => props.onSelectApplication(candidate.applicationId)}>
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
                          <p key={c.dimensionKey} className="ranking-contribution">
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
