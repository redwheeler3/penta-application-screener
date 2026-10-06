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
  const hasPendingProposals = pendingProposals.length > 0;
  const preferScoring = hasMissingScores && !hasPendingProposals;

  return (
    <div className="run-confirm">
      <div className="run-confirm-body">
        <strong>Run ranking?</strong>
        {hasPendingProposals ? (
          <p>
            Discovery considers:{" "}
            {pendingProposals.map((text, i) => (
              <span key={text}>
                {i > 0 ? ", " : ""}
                <strong>{text}</strong>
              </span>
            ))}
            .
          </p>
        ) : null}
        {scoreCurrentEstimate && hasMissingScores ? (
          <>
            <p>
              Score {scoreCurrentEstimate.toAnalyze} applicant{scoreCurrentEstimate.toAnalyze === 1 ? "" : "s"} with {scoreCurrentEstimate.dimensions} existing criteria.{" "}
              <strong>~{money(scoreCurrentEstimate.estimatedUsd)}</strong> (cap ${scoreCurrentEstimate.capUsd.toFixed(2)}).
            </p>
            {!scoreCurrentEstimate.withinCap ? (
              <p className="run-confirm-warn">
                Estimate exceeds the cap. Increase it in settings to run.
              </p>
            ) : null}
          </>
        ) : null}
        <div>
          <p>
            Discover criteria and score {estimate.eligible} applicant{estimate.eligible === 1 ? "" : "s"}.{" "}
            <strong>~{money(estimate.estimatedUsd)}</strong> (cap ${estimate.capUsd.toFixed(2)}).
            {hasCurrentCriteria ? " Tiered criteria stay; ignored criteria may change." : ""}
          </p>
          {!estimate.withinCap ? (
            <p className="run-confirm-warn">
              Estimate exceeds the cap. Increase it in settings to run.
            </p>
          ) : null}
        </div>
      </div>
      <div className="run-confirm-actions">
        {/* A pending proposal makes Discover the primary action — it's the only run
            that grounds the proposed axis — so score-missing is demoted even when
            scores are short. */}
        {scoreCurrentEstimate && hasMissingScores ? (
          <button
            className={preferScoring ? "primary-button" : "secondary-button"}
            type="button"
            onClick={() => onRun("score-current")}
            disabled={running || !scoreCurrentEstimate.withinCap}
          >
            {running ? "Running…" : "Score missing applicants"}
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
