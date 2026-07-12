import { AlertTriangle, Check, ChevronRight, RefreshCw, Sparkles } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import { screeningPercent } from "../format";
import type {
  Coverage,
  CriteriaStage,
  DashboardCounts,
  ScreeningEstimateResponse,
  RankEstimateResponse,
  RankProgress,
  WorkflowState,
} from "../types";

// Labels for the criteria phase's sub-stages (the sequential model calls under its
// one banner), keyed by the backend's stage names. Fan-out width isn't known here, so
// "discoveries" stays plural-generic rather than naming K.
const CRITERIA_STAGE_LABELS: Record<CriteriaStage, string> = {
  discovering: "Running parallel discovery passes…",
  settling: "Settling into one set of criteria…",
  matching: "Matching criteria to the prior run…",
};

// The descriptive caption under the progress bar, per stage — it explains what the
// current step is doing (and why the wait), so the static line tracks the green label
// instead of describing only discovery. Keyed by criteria sub-stage plus "scoring"
// (the per-candidate phase, which has no criteria sub-stage). Every stage the rank
// stream can report has an entry.
const STAGE_CAPTIONS: Record<CriteriaStage | "scoring" | "consolidate", string> = {
  discovering: "Reading the whole pool and reasoning about what distinguishes it — this can take up to 5 minutes.",
  settling: "Distilling the parallel discoveries into one non-overlapping set of criteria.",
  matching: "Carrying tier placements and cached scores forward by matching to the prior run.",
  scoring: "Scoring each candidate against every criterion — the longest phase on a fresh run.",
  consolidate: "Checking the scored criteria for duplicates and merging any that measure the same thing.",
};

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
    ? progress && progress.total > 0
      ? `${progress.processed}/${progress.total}`
      : null
    : coverage && (coverage.cached > 0 || coverage.inScope > 0)
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
// two AI runs. Rank is one button that runs the whole criteria → scores
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
  screeningRunning: boolean;
  screeningEstimate: ScreeningEstimateResponse | null;
  screeningProgress: { processed: number; total: number } | null;
  onRequestScreening: () => void;
  onRunScreening: () => void;
  onCancelScreening: () => void;
  rankRunning: boolean;
  rankEstimate: RankEstimateResponse | null;
  rankProgress: RankProgress | null;
  // The model's live reasoning during the criteria phase (discovery + match),
  // streamed; shown as "thinking" since that call has no per-item progress.
  criteriaThinking: string;
  // Committee discovery seeds the next Rank will offer the AI, for the card note.
  favouritedCount: number;
  proposedCount: number;
  onRequestRank: () => void;
  onRunRank: () => void;
  onCancelRank: () => void;
}): ReactNode {
  const {
    workflow,
    coverage,
    dashboardCounts,
    screeningEstimate,
    screeningProgress,
    rankEstimate,
    rankProgress,
  } = props;

  return (
    <>
      <div className="workflow-bar">
        <ol className="workflow-steps">
          <WorkflowStep
            n={1}
            title="Sync"
            icon={<RefreshCw size={16} />}
            done={workflow.synced}
            busy={props.isSyncing}
            busyLabel="Syncing"
            // Step 1 is always available once a sheet is configured. The caption
            // persists the synced row count (not a fraction).
            disabled={props.isSyncing || props.importConfirm || !props.hasGoogleSheetLink}
            disabledTitle="Add a Google Sheet link in settings to sync."
            // Amber when sync-relevant settings changed since the last sync: a
            // re-sync would reclassify eligibility.
            outOfDate={workflow.synced && !workflow.importCurrent}
            staleTitle="Settings changed since the last sync — re-sync to apply them."
            onClick={props.onRequestImport}
            caption={
              workflow.synced && dashboardCounts.submitted > 0 ? `${dashboardCounts.submitted} rows` : undefined
            }
          />
          <WorkflowStep
            n={2}
            title="Screen"
            icon={<Sparkles size={16} />}
            done={workflow.screened}
            busy={props.screeningRunning}
            busyLabel="Screening"
            // Needs a sync, eligible apps, and no estimate prompt open.
            disabled={
              !workflow.synced || props.screeningRunning || screeningEstimate !== null || dashboardCounts.status.eligible === 0
            }
            disabledTitle={
              !workflow.synced
                ? "Import applications first."
                : dashboardCounts.status.eligible === 0
                  ? "No eligible applicants to screen."
                  : undefined
            }
            onClick={props.onRequestScreening}
            coverage={workflow.screened ? coverage.screened : undefined}
            progress={screeningProgress}
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
              !workflow.screened ||
              props.rankRunning ||
              rankEstimate !== null ||
              dashboardCounts.status.eligible === 0
            }
            disabledTitle={
              !workflow.screened
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
        {/* The ranked shortlist now has its own "Ranking" tab in the panel header,
            so there's no entry-point button here. */}
      </div>

      {props.importConfirm ? (
        <div className="run-confirm">
          <div className="run-confirm-body">
            <strong>Sync applications?</strong>
            {workflow.synced ? (
              <p>
                Re-sync from the Google Sheet. New and changed applications are reclassified against the current
                settings; existing decisions are preserved.
              </p>
            ) : (
              <p>Pull the applications from the configured Google Sheet and screen them against the current settings.</p>
            )}
          </div>
          <div className="run-confirm-actions">
            <button className="primary-button" type="button" onClick={props.onConfirmImport} disabled={props.isSyncing}>
              {props.isSyncing ? "Syncing" : "Confirm & sync"}
            </button>
            <button className="secondary-button" type="button" onClick={props.onCancelImport}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {screeningEstimate ? (
        <div className="run-confirm">
          <div className="run-confirm-body">
            <strong>Run AI screening?</strong>
            {screeningEstimate.toAnalyze === 0 ? (
              <p>
                Screening is already up to date — all {screeningEstimate.cached} eligible applicant
                {screeningEstimate.cached === 1 ? " has" : "s have"} been checked. Sync new or changed applications to screen
                again.
              </p>
            ) : (
              <p>
                Analyze {screeningEstimate.toAnalyze} eligible applicant{screeningEstimate.toAnalyze === 1 ? "" : "s"}
                {screeningEstimate.cached > 0 ? ` (${screeningEstimate.cached} already cached)` : ""}. Estimated cost{" "}
                <strong>${screeningEstimate.estimatedUsd.toFixed(4)}</strong> (cap ${screeningEstimate.capUsd.toFixed(2)}).
              </p>
            )}
            {screeningEstimate.toAnalyze > 0 && !screeningEstimate.withinCap ? (
              <p className="run-confirm-warn">
                Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
              </p>
            ) : null}
          </div>
          <div className="run-confirm-actions">
            {/* No run button when there's nothing to do — informational, Close only. */}
            {screeningEstimate.toAnalyze > 0 ? (
              <button
                className="primary-button"
                type="button"
                onClick={props.onRunScreening}
                disabled={props.screeningRunning || !screeningEstimate.withinCap}
              >
                {props.screeningRunning ? "Running" : "Confirm & run"}
              </button>
            ) : null}
            <button className="secondary-button" type="button" onClick={props.onCancelScreening}>
              {screeningEstimate.toAnalyze === 0 ? "Close" : "Cancel"}
            </button>
          </div>
        </div>
      ) : null}
      {props.screeningRunning ? (
        <div className="run-progress">
          <div className="run-progress-label">
            {screeningProgress
              ? `Analyzing applications… ${screeningProgress.processed}/${screeningProgress.total} ` +
                `(${Math.round(screeningPercent(screeningProgress))}%)`
              : "Starting analysis…"}
          </div>
          {/* Indeterminate bar until the first progress event, so the indicator
              appears instantly on confirm. */}
          <div className="run-progress-track">
            {screeningProgress ? (
              <div className="run-progress-fill" style={{ width: `${screeningPercent(screeningProgress)}%` }} />
            ) : (
              <div className="run-progress-fill run-progress-fill-indeterminate" />
            )}
          </div>
        </div>
      ) : null}

      {rankEstimate ? (
        <div className="run-confirm">
          <div className="run-confirm-body">
            <strong>Rank the candidates?</strong>
            {rankEstimate.rankingCurrent ? (
              // Nothing changed in the pool, but re-ranking is still allowed: the
              // categorization is non-deterministic, so a re-run gives a fresh set
              // of criteria for the committee to weigh.
              <p>
                Ranking is already up to date. You can re-run for a fresh take on the criteria (finding them is
                non-deterministic). Estimated cost <strong>~${rankEstimate.estimatedUsd.toFixed(4)}</strong> (cap $
                {rankEstimate.capUsd.toFixed(2)}).
              </p>
            ) : (
              <p>
                This finds the criteria that distinguish this pool and scores all{" "}
                {rankEstimate.eligible} eligible applicant{rankEstimate.eligible === 1 ? "" : "s"} against them.
                Estimated cost <strong>~${rankEstimate.estimatedUsd.toFixed(4)}</strong> (cap $
                {rankEstimate.capUsd.toFixed(2)}).
              </p>
            )}
            <ul className="run-confirm-breakdown">
              <li>
                Find distinguishing criteria — {rankEstimate.fanOut} parallel discoveries, then
                settle them into one set ~${rankEstimate.breakdown.criteriaUsd.toFixed(4)}
              </li>
              {rankEstimate.breakdown.matchUsd > 0 ? (
                <li>Match criteria to the prior run ~${rankEstimate.breakdown.matchUsd.toFixed(4)}</li>
              ) : null}
              <li>Score against criteria ~${rankEstimate.breakdown.scoringUsd.toFixed(4)}</li>
            </ul>
            {props.favouritedCount + props.proposedCount > 0 ? (
              <p className="run-confirm-note">
                Offering the AI {props.favouritedCount + props.proposedCount} suggested{" "}
                {props.favouritedCount + props.proposedCount === 1 ? "axis" : "axes"} ({props.favouritedCount} favourited,{" "}
                {props.proposedCount} proposed) — it may refine, split, or skip them.
              </p>
            ) : null}
            {!rankEstimate.withinCap ? (
              <p className="run-confirm-warn">
                Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
              </p>
            ) : null}
          </div>
          <div className="run-confirm-actions">
            <button
              className="primary-button"
              type="button"
              onClick={props.onRunRank}
              disabled={props.rankRunning || !rankEstimate.withinCap}
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
        <div className="run-progress">
          <div className="run-progress-label">
            {rankProgress
              ? rankProgress.phase === "criteria"
                ? CRITERIA_STAGE_LABELS[rankProgress.stage ?? "discovering"]
                : rankProgress.phase === "consolidate"
                  ? "Consolidating duplicate criteria…"
                  : `Scoring candidates… ${rankProgress.processed}/${rankProgress.total}` +
                    (rankProgress.total ? ` (${Math.round(screeningPercent(rankProgress))}%)` : "")
              : "Starting…"}
          </div>
          <div className="run-progress-track">
            {/* Only the per-candidate scoring phase has a real fraction; criteria and
                consolidation are single opaque calls → indeterminate bar. */}
            {rankProgress && rankProgress.phase === "scores" && rankProgress.total ? (
              <div className="run-progress-fill" style={{ width: `${screeningPercent(rankProgress)}%` }} />
            ) : (
              <div className="run-progress-fill run-progress-fill-indeterminate" />
            )}
          </div>
          {/* Descriptive caption that tracks the current stage, so the static line under
              the bar matches the green label above through every phase. */}
          {rankProgress ? (
            <div className="run-progress-caption">
              {STAGE_CAPTIONS[
                rankProgress.phase === "criteria"
                  ? (rankProgress.stage ?? "discovering")
                  : rankProgress.phase === "consolidate"
                    ? "consolidate"
                    : "scoring"
              ]}
            </div>
          ) : null}
          {/* During the criteria phase (discovery + match — one long opaque call,
              no per-item progress) show the model's live reasoning so the wait
              reads as active work, not a hang. */}
          {rankProgress?.phase === "criteria" ? (
            <CriteriaThinking text={props.criteriaThinking} />
          ) : null}
        </div>
      ) : null}
    </>
  );
}

// Auto-scrolling panel for the streamed discovery/match reasoning. Before the first
// delta arrives it shows an expectation line, so the wait is framed even if the
// model is briefly silent at the start.
function CriteriaThinking(props: { text: string }): ReactNode {
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Keep the newest text in view as it streams in.
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [props.text]);
  return props.text ? (
    <div className="criteria-thinking">
      <div className="criteria-thinking-stream" ref={boxRef}>
        <ReactMarkdown>{props.text}</ReactMarkdown>
      </div>
    </div>
  ) : null;
}
