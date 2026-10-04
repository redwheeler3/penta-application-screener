import type { ReactNode } from "react";
import { money } from "../../format";
import type { RankEstimateResponse, ScoreCurrentEstimateResponse } from "../../types";

/** Ranking cost confirmation and action priority; run state stays in useAiRuns. */
export function RankingRunConfirmation(props: {
  estimate: RankEstimateResponse;
  scoreCurrentEstimate: ScoreCurrentEstimateResponse | null;
  hasCurrentCriteria: boolean;
  pendingProposals: string[];
  running: boolean;
  onRun: (mode: "discover" | "score-current") => void;
  onCancel: () => void;
}): ReactNode {
  const { estimate, scoreCurrentEstimate, hasCurrentCriteria, pendingProposals, running, onRun, onCancel } = props;
  const hasMissingScores = (scoreCurrentEstimate?.toAnalyze ?? 0) > 0;
  const hasCachedRefresh = (scoreCurrentEstimate?.cachedToRefresh ?? 0) > 0;
  const hasScoreUpdates = hasMissingScores || hasCachedRefresh;
  const hasPendingProposals = pendingProposals.length > 0;
  const preferScoring = hasScoreUpdates && !hasPendingProposals;

  return (
    <div className="run-confirm">
      <div className="run-confirm-body">
        <strong>{confirmationTitle(pendingProposals.length, scoreCurrentEstimate)}</strong>
        {hasPendingProposals ? (
          <p>
            You proposed{" "}
            {pendingProposals.map((text, i) => (
              <span key={text}>
                {i > 0 ? ", " : ""}
                <strong>{text}</strong>
              </span>
            ))}
            . A proposal stays inactive until a discovery run grounds it in the pool — run{" "}
            <strong>Discover new criteria</strong> below to fold it in.
          </p>
        ) : null}
        {scoreCurrentEstimate && hasScoreUpdates ? (
          <>
            <p>
              <strong>{hasMissingScores ? "Score missing applicants" : "Reuse cached scores"}</strong> against the current {scoreCurrentEstimate.dimensions} criteria.
              The criteria and your tier layout stay unchanged. Estimated cost{" "}
              <strong>~{money(scoreCurrentEstimate.estimatedUsd)}</strong> (cap ${scoreCurrentEstimate.capUsd.toFixed(2)}).
            </p>
            {hasCachedRefresh && !hasMissingScores ? (
              <p>
                Restore scores for {scoreCurrentEstimate.cachedToRefresh} applicant{scoreCurrentEstimate.cachedToRefresh === 1 ? "" : "s"}{" "}
                using the saved results for the selected AI settings. No AI calls are needed.
              </p>
            ) : null}
            {!scoreCurrentEstimate.withinCap ? (
              <p className="run-confirm-warn">
                Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
              </p>
            ) : null}
          </>
        ) : null}
        {scoreCurrentEstimate?.toAnalyze === 0 && !hasCachedRefresh ? (
          <p>All {scoreCurrentEstimate.cached} eligible applicants are already scored against these criteria.</p>
        ) : null}
        <div>
          <p>
            {hasScoreUpdates ? "Or, " : ""}<strong>Discover new criteria</strong> that distinguish this pool and score all{" "}
            {estimate.eligible} eligible applicant{estimate.eligible === 1 ? "" : "s"} against them.
            Estimated cost <strong>~{money(estimate.estimatedUsd)}</strong> (cap $
            {estimate.capUsd.toFixed(2)}).
          </p>
          {hasCurrentCriteria ? (
            <p>
              Criteria you've tiered are kept and re-scored; only ignored criteria may be
              dropped or re-carved.
            </p>
          ) : null}
          {!estimate.withinCap ? (
            <p className="run-confirm-warn">
              Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
            </p>
          ) : null}
        </div>
      </div>
      <div className="run-confirm-actions">
        {/* A pending proposal makes Discover the primary action — it's the only run
            that grounds the proposed axis — so score-missing is demoted even when
            scores are short. */}
        {scoreCurrentEstimate && hasScoreUpdates ? (
          <button
            className={preferScoring ? "primary-button" : "secondary-button"}
            type="button"
            onClick={() => onRun("score-current")}
            disabled={running || !scoreCurrentEstimate.withinCap}
          >
            {running ? "Running…" : hasMissingScores ? "Score missing applicants" : "Reuse cached scores"}
          </button>
        ) : null}
        <button
          className={preferScoring ? "secondary-button" : "primary-button"}
          type="button"
          onClick={() => onRun("discover")}
          disabled={running || !estimate.withinCap}
        >
          {running ? "Running…" : hasCurrentCriteria ? "Discover new criteria" : "Confirm & run"}
        </button>
        <button className="secondary-button" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function confirmationTitle(proposalCount: number, scoreEstimate: ScoreCurrentEstimateResponse | null): string {
  if (proposalCount === 1) return "Apply your proposed criterion?";
  if (proposalCount > 1) return "Apply your proposed criteria?";
  if (scoreEstimate?.toAnalyze === 0 && scoreEstimate.cachedToRefresh > 0) return "Reuse saved scores?";
  if (scoreEstimate?.toAnalyze === 0) return "Ranking is up to date.";
  if (scoreEstimate) return "Update the ranking?";
  return "Rank the candidates?";
}
