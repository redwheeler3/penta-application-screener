import { AlertTriangle, Check, ChevronLeft, ChevronRight, ListOrdered, RefreshCw, Sparkles } from "lucide-react";
import { type ReactNode } from "react";
import { qfPercent } from "../format";
import type {
  Coverage,
  DashboardCounts,
  QualityFlagEstimate,
  RankEstimate,
  RankProgress,
  WorkflowState,
} from "../types";

// One numbered step in the ordered workflow strip: the step button plus a chevron
// to the next step (omitted on the last). Line 1 is the title; line 2 is the live
// "processed/total" while running, else the step's coverage "cached/inScope". When
// results are stale (cached < inScope) the step is NOT done — the badge turns amber
// so "it ran once" can't masquerade as "it's current" after a re-sync.
function WorkflowStep(props: {
  n: number;
  title: string;
  icon: ReactNode;
  done: boolean;
  busy: boolean;
  // The line-1 verb while running; line 2's count comes from `progress`.
  busyLabel: string;
  disabled: boolean;
  onClick: () => void;
  last?: boolean;
  coverage?: { cached: number; inScope: number };
  progress?: { processed: number; total: number } | null;
  // A single value for line 2 when there's no coverage fraction (e.g. sync's row
  // count) — shown as one number, not "n/n".
  caption?: string;
  // Explicit "out of date" signal for steps not captured by score coverage (Rank:
  // the pool can change while every candidate keeps a cached score). Drives the
  // stale badge instead of the coverage comparison.
  outOfDate?: boolean;
  // Tooltip shown when stale, overriding the default coverage-based one.
  staleTitle?: string;
  // Tooltip explaining why the step is disabled. Stale takes precedence if both apply.
  disabledTitle?: string;
}): ReactNode {
  const { n, title, icon, done, busy, busyLabel, disabled, onClick, last, coverage, progress, caption, outOfDate, staleTitle, disabledTitle } = props;
  // Stale only applies once done — from the explicit out-of-date signal when given
  // (Rank), else coverage falling short of the current scope.
  const stale =
    done &&
    (outOfDate !== undefined
      ? outOfDate
      : coverage !== undefined && coverage.cached < coverage.inScope);
  const showDone = done && !stale;
  // Line 2 priority: live progress, then settled coverage, then a standalone caption.
  const fraction = busy
    ? progress
      ? `${progress.processed}/${progress.total}`
      : null
    : coverage
      ? `${coverage.cached}/${coverage.inScope}`
      : caption ?? null;
  return (
    <li className="workflow-step">
      <button
        type="button"
        className={
          `workflow-step-button${showDone ? " is-done" : ""}` +
          `${busy ? " is-busy" : ""}${stale ? " is-stale" : ""}`
        }
        onClick={onClick}
        disabled={disabled}
        title={
          stale
            ? staleTitle ?? `${coverage!.cached}/${coverage!.inScope} current — re-run to cover everyone`
            : disabled
              ? disabledTitle
              : undefined
        }
      >
        <span className="workflow-step-badge">
          {stale ? <AlertTriangle size={13} /> : showDone ? <Check size={14} /> : n}
        </span>
        {icon}
        <span className="workflow-step-text">
          {busy ? busyLabel : title}
          {fraction ? <span className="workflow-step-fraction">{fraction}</span> : null}
        </span>
      </button>
      {!last ? <ChevronRight className="workflow-step-arrow" size={18} /> : null}
    </li>
  );
}

// The ordered screening workflow band: three single-verb steps (Import, Screen,
// Rank), the View-ranking entry point, and the confirm + progress cards for the
// two AI runs. Rank is one button that runs the whole essays → criteria → scores
// chain under one combined cost estimate. Later steps stay hard-gated until the
// previous has run; "done" flags come from the backend, so gating survives reload.
export function WorkflowBar(props: {
  workflow: WorkflowState;
  coverage: Coverage;
  dashboardCounts: DashboardCounts;
  hasGoogleSheetLink: boolean;
  isSyncing: boolean;
  importConfirm: boolean;
  onRequestImport: () => void;
  onConfirmImport: () => void;
  onCancelImport: () => void;
  qfRunning: boolean;
  qfEstimate: QualityFlagEstimate | null;
  qfProgress: { processed: number; total: number } | null;
  onRequestQualityFlags: () => void;
  onRunQualityFlags: () => void;
  onCancelQualityFlags: () => void;
  rankRunning: boolean;
  rankEstimate: RankEstimate | null;
  rankProgress: RankProgress | null;
  // Committee discovery seeds the next Rank will offer the AI, for the card note.
  favouritedCount: number;
  proposedCount: number;
  onRequestRank: () => void;
  onRunRank: () => void;
  onCancelRank: () => void;
  showRanking: boolean;
  selectedAppOpen: boolean;
  onOpenRanking: () => void;
  onHideRanking: () => void;
}): ReactNode {
  const {
    workflow,
    coverage,
    dashboardCounts,
    qfEstimate,
    qfProgress,
    rankEstimate,
    rankProgress,
  } = props;

  return (
    <>
      <div className="workflow-bar">
        <ol className="workflow-steps">
          <WorkflowStep
            n={1}
            title="Import"
            icon={<RefreshCw size={16} />}
            done={workflow.synced}
            busy={props.isSyncing}
            busyLabel="Importing"
            // Step 1 is always available once a sheet is configured. The caption
            // persists the imported row count (not a fraction).
            disabled={props.isSyncing || props.importConfirm || !props.hasGoogleSheetLink}
            disabledTitle="Add a Google Sheet link in settings to import."
            // Amber when import-relevant settings changed since the last sync: a
            // re-import would reclassify eligibility.
            outOfDate={workflow.synced && !workflow.importCurrent}
            staleTitle="Settings changed since the last import — re-import to apply them."
            onClick={props.onRequestImport}
            caption={
              workflow.synced && dashboardCounts.submitted > 0 ? `${dashboardCounts.submitted} rows` : undefined
            }
          />
          <WorkflowStep
            n={2}
            title="Screen"
            icon={<Sparkles size={16} />}
            done={workflow.qualityChecksRun}
            busy={props.qfRunning}
            busyLabel="Screening"
            // Needs a sync, eligible apps, and no estimate prompt open.
            disabled={
              !workflow.synced || props.qfRunning || qfEstimate !== null || dashboardCounts.status.eligible === 0
            }
            disabledTitle={
              !workflow.synced
                ? "Import applications first."
                : dashboardCounts.status.eligible === 0
                  ? "No eligible applicants to screen."
                  : undefined
            }
            onClick={props.onRequestQualityFlags}
            coverage={coverage.qualityChecksRun}
            progress={qfProgress}
          />
          <WorkflowStep
            n={3}
            title="Rank"
            icon={<Sparkles size={16} />}
            // Done only once the final pass (scoring) has full coverage, which
            // coverage tracks so a re-sync correctly shows it stale.
            done={workflow.candidatesScored}
            busy={props.rankRunning}
            busyLabel="Ranking"
            // Needs screening run, eligible apps, and no open estimate.
            disabled={
              !workflow.qualityChecksRun ||
              props.rankRunning ||
              rankEstimate !== null ||
              dashboardCounts.status.eligible === 0
            }
            disabledTitle={
              !workflow.qualityChecksRun
                ? "Run Screen first."
                : dashboardCounts.status.eligible === 0
                  ? "No eligible applicants to rank."
                  : undefined
            }
            onClick={props.onRequestRank}
            coverage={coverage.candidatesScored}
            // Rank's currency is the pool fingerprint, not score coverage: a pool
            // change makes ranking out of date even with full coverage.
            outOfDate={workflow.candidatesScored && !workflow.rankingCurrent}
            staleTitle="The applicant pool changed since the last ranking — re-rank to refresh it."
            progress={rankProgress}
            last
          />
        </ol>

        {/* Ranked shortlist entry point, beside the steps once Rank has run.
            Not a gated AI step — viewing the ranking is math, no model. */}
        {workflow.candidatesScored && !props.selectedAppOpen ? (
          props.showRanking ? (
            <button type="button" className="secondary-button workflow-shortlist-button" onClick={props.onHideRanking}>
              <ChevronLeft size={16} />
              <span>Back to applications</span>
            </button>
          ) : (
            <button type="button" className="primary-button workflow-shortlist-button" onClick={props.onOpenRanking}>
              <ListOrdered size={16} />
              <span>View ranking</span>
            </button>
          )
        ) : null}
      </div>

      {props.importConfirm ? (
        <div className="qf-confirm">
          <div className="qf-confirm-body">
            <strong>Import applications?</strong>
            {workflow.synced ? (
              <p>
                Re-import from the Google Sheet. New and changed applications are reclassified against the current
                settings; existing decisions are preserved.
              </p>
            ) : (
              <p>Pull the applications from the configured Google Sheet and screen them against the current settings.</p>
            )}
          </div>
          <div className="qf-confirm-actions">
            <button className="primary-button" type="button" onClick={props.onConfirmImport} disabled={props.isSyncing}>
              {props.isSyncing ? "Importing" : "Confirm & import"}
            </button>
            <button className="secondary-button" type="button" onClick={props.onCancelImport}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {qfEstimate ? (
        <div className="qf-confirm">
          <div className="qf-confirm-body">
            <strong>Run AI quality checks?</strong>
            {qfEstimate.to_analyze === 0 ? (
              <p>
                Screening is already up to date — all {qfEstimate.cached} eligible applicant
                {qfEstimate.cached === 1 ? " has" : "s have"} been checked. Sync new or changed applications to screen
                again.
              </p>
            ) : (
              <p>
                Analyze {qfEstimate.to_analyze} eligible applicant{qfEstimate.to_analyze === 1 ? "" : "s"}
                {qfEstimate.cached > 0 ? ` (${qfEstimate.cached} already cached)` : ""}. Estimated cost{" "}
                <strong>${qfEstimate.estimated_usd.toFixed(4)}</strong> (cap ${qfEstimate.cap_usd.toFixed(2)}).
              </p>
            )}
            {qfEstimate.to_analyze > 0 && !qfEstimate.within_cap ? (
              <p className="qf-confirm-warn">
                Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
              </p>
            ) : null}
          </div>
          <div className="qf-confirm-actions">
            {/* No run button when there's nothing to do — informational, Close only. */}
            {qfEstimate.to_analyze > 0 ? (
              <button
                className="primary-button"
                type="button"
                onClick={props.onRunQualityFlags}
                disabled={props.qfRunning || !qfEstimate.within_cap}
              >
                {props.qfRunning ? "Running" : "Confirm & run"}
              </button>
            ) : null}
            <button className="secondary-button" type="button" onClick={props.onCancelQualityFlags}>
              {qfEstimate.to_analyze === 0 ? "Close" : "Cancel"}
            </button>
          </div>
        </div>
      ) : null}
      {props.qfRunning ? (
        <div className="qf-progress">
          <div className="qf-progress-label">
            {qfProgress
              ? `Analyzing applications… ${qfProgress.processed}/${qfProgress.total} ` +
                `(${Math.round(qfPercent(qfProgress))}%)`
              : "Starting analysis…"}
          </div>
          {/* Indeterminate bar until the first progress event, so the indicator
              appears instantly on confirm. */}
          <div className="qf-progress-track">
            {qfProgress ? (
              <div className="qf-progress-fill" style={{ width: `${qfPercent(qfProgress)}%` }} />
            ) : (
              <div className="qf-progress-fill qf-progress-fill-indeterminate" />
            )}
          </div>
        </div>
      ) : null}

      {rankEstimate ? (
        <div className="qf-confirm">
          <div className="qf-confirm-body">
            <strong>Rank the candidates?</strong>
            {rankEstimate.ranking_current ? (
              // Nothing changed in the pool, but re-ranking is still allowed: the
              // categorization is non-deterministic, so a re-run gives a fresh set
              // of criteria for the committee to weigh.
              <p>
                Ranking is already up to date. You can re-run for a fresh take on the criteria (finding them is
                non-deterministic). Estimated cost <strong>~${rankEstimate.estimated_usd.toFixed(4)}</strong> (cap $
                {rankEstimate.cap_usd.toFixed(2)}).
              </p>
            ) : (
              <p>
                This summarizes essays, finds the criteria that distinguish this pool, and scores all{" "}
                {rankEstimate.eligible} eligible applicant{rankEstimate.eligible === 1 ? "" : "s"} against them.
                Estimated cost <strong>~${rankEstimate.estimated_usd.toFixed(4)}</strong> (cap $
                {rankEstimate.cap_usd.toFixed(2)}).
              </p>
            )}
            <ul className="qf-confirm-breakdown">
              <li>
                Summarize essays ~${rankEstimate.breakdown.essays_usd.toFixed(4)}
                {rankEstimate.essays_cached > 0 ? ` (${rankEstimate.essays_cached} cached)` : ""}
              </li>
              <li>Find distinguishing criteria ~${rankEstimate.breakdown.criteria_usd.toFixed(4)}</li>
              {rankEstimate.breakdown.match_usd > 0 ? (
                <li>Match criteria to the prior run ~${rankEstimate.breakdown.match_usd.toFixed(4)}</li>
              ) : null}
              <li>Score against criteria ~${rankEstimate.breakdown.scoring_usd.toFixed(4)}</li>
            </ul>
            {props.favouritedCount + props.proposedCount > 0 ? (
              <p className="qf-confirm-note">
                Offering the AI {props.favouritedCount + props.proposedCount} suggested{" "}
                {props.favouritedCount + props.proposedCount === 1 ? "axis" : "axes"} ({props.favouritedCount} favourited,{" "}
                {props.proposedCount} proposed) — it may refine, split, or skip them.
              </p>
            ) : null}
            {!rankEstimate.within_cap ? (
              <p className="qf-confirm-warn">
                Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
              </p>
            ) : null}
          </div>
          <div className="qf-confirm-actions">
            <button
              className="primary-button"
              type="button"
              onClick={props.onRunRank}
              disabled={props.rankRunning || !rankEstimate.within_cap}
            >
              {props.rankRunning ? "Running" : "Confirm & run"}
            </button>
            <button className="secondary-button" type="button" onClick={props.onCancelRank}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      {props.rankRunning ? (
        <div className="qf-progress">
          <div className="qf-progress-label">
            {rankProgress
              ? rankProgress.phase === "criteria"
                ? "Finding criteria across the pool…"
                : `${rankProgress.phase === "essays" ? "Summarizing essays" : "Scoring candidates"}… ` +
                  `${rankProgress.processed}/${rankProgress.total}` +
                  (rankProgress.total ? ` (${Math.round(qfPercent(rankProgress))}%)` : "")
              : "Starting…"}
          </div>
          <div className="qf-progress-track">
            {/* Criteria is a single call with no fraction, so it shows the
                indeterminate bar; the per-candidate phases show real width. */}
            {rankProgress && rankProgress.phase !== "criteria" && rankProgress.total ? (
              <div className="qf-progress-fill" style={{ width: `${qfPercent(rankProgress)}%` }} />
            ) : (
              <div className="qf-progress-fill qf-progress-fill-indeterminate" />
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
