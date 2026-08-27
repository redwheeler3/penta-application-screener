import { AlertTriangle, Check, ChevronRight, Sparkles } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import { money, openingLabel, screeningPercent } from "../../format";
import type {
  Coverage,
  CommitteeOpening,
  CriteriaStage,
  ScreeningEstimateResponse,
  RankEstimateResponse,
  ScoreCurrentEstimateResponse,
  RankProgress,
  WorkflowState,
} from "../../types";

// Labels for the criteria phase's sub-stages (the sequential model calls under its
// one banner), keyed by the backend's stage names. Fan-out width isn't known here, so
// "discoveries" stays plural-generic rather than naming K.
const CRITERIA_STAGE_LABELS: Record<CriteriaStage, string> = {
  discovering: "Running parallel discovery passes…",
  settling: "Settling into one set of criteria…",
  matching: "Matching criteria to the prior run…",
};

// The green criteria-stage label. Discovering names its fan-out width K (carried on the
// criteria phase event's `total`) — "Running K parallel discovery passes…" — falling back
// to the count-less phrasing if K wasn't reported.
function criteriaStageLabel(stage: CriteriaStage, k: number): string {
  if (stage === "discovering" && k > 0) return `Running ${k} parallel discovery passes…`;
  return CRITERIA_STAGE_LABELS[stage];
}

// The descriptive caption under the progress bar, per stage — it explains what the
// current step is doing (and why the wait), so the static line tracks the green label
// instead of describing only discovery. Keyed by criteria sub-stage plus "scoring"
// (the per-candidate phase, which has no criteria sub-stage). Every stage the rank
// stream can report has an entry.
const STAGE_CAPTIONS: Record<CriteriaStage | "scoring" | "consolidate", string> = {
  discovering: "Reading the whole pool and reasoning about what distinguishes it — this can take up to 5 minutes.",
  settling: "Distilling the parallel discoveries into one non-overlapping set of criteria — this can take up to 5 minutes.",
  matching: "Reusing tier placements and cached scores by matching each criterion to the prior run.",
  scoring: "Scoring applicants against the current criteria.",
  consolidate: "Checking the scored criteria for duplicates and merging any that measure the same thing.",
};

// One numbered step in the ordered workflow strip: the step button plus a chevron
// to the next step (omitted on the last). Line 1 is the title; line 2 is the live
// "processed/total" while running, else the step's coverage "cached/inScope". When
// results are stale (cached < inScope) the step is NOT done — the badge turns amber
// so "it ran once" can't masquerade as "it's current" after an applicant edit.
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
  // A single value for line 2 when there's no coverage fraction.
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

// The ordered screening workflow band: Screen and Rank, the shared opening view scope,
// and the confirm + progress cards for the two AI runs. The opening scope filters the
// application and ranking views; it does
// not narrow the reusable AI analysis pool. Rank is one button that runs the whole criteria → scores
// chain under one combined cost estimate. Later steps stay hard-gated until the
// previous has run; "done" flags come from the backend, so gating survives reload.
export function WorkflowBar(props: {
  workflow: WorkflowState;
  coverage: Coverage;
  loadState: "loading" | "ready" | "error";
  onRetryLoad: () => void;
  screeningRunning: boolean;
  screeningEstimate: ScreeningEstimateResponse | null;
  screeningEstimateLoading: boolean;
  screeningProgress: { processed: number; total: number } | null;
  onRequestScreening: () => void;
  onRunScreening: () => void;
  onCancelScreening: () => void;
  rankRunning: boolean;
  rankEstimate: RankEstimateResponse | null;
  rankEstimateLoading: boolean;
  scoreCurrentEstimate: ScoreCurrentEstimateResponse | null;
  hasCurrentCriteria: boolean;
  rankProgress: RankProgress | null;
  // The model's live reasoning, streamed and shown as "thinking" for the opaque
  // calls that have no per-item progress: the criteria phase (discovery + match)
  // and post-score consolidation. Accumulates across the whole run and persists
  // through scoring once it has any text.
  criteriaThinking: string;
  // Free-text axes this member proposed since the last Rank. A proposal does nothing
  // until a discovery run grounds it in the pool, and nothing else about the workflow
  // changes when one is added — so without this the Rank step looks up to date and the
  // proposal seems to vanish. It drives the amber nudge + the card's Discover-first copy.
  pendingProposals: string[];
  onRequestRank: () => void;
  onRunRank: (mode: "discover" | "score-current") => void;
  onCancelRank: () => void;
  openings: CommitteeOpening[];
  selectedOpeningIds: number[];
  onOpeningScopeChange: (openingIds: number[]) => void;
}): ReactNode {
  const {
    workflow,
    coverage,
    loadState,
    screeningEstimate,
    screeningProgress,
    rankEstimate,
    scoreCurrentEstimate,
    hasCurrentCriteria,
    rankProgress,
    pendingProposals,
  } = props;
  const hasMissingScores = (scoreCurrentEstimate?.toAnalyze ?? 0) > 0;
  const hasPendingProposals = pendingProposals.length > 0;
  const currentOpenings = props.openings.filter((opening) => opening.phase !== "archived");
  // Screen and Rank are shared actions over the union scope, so both gate on the shared
  // pool being empty — not on this member's personal eligible count.
  const noApplicantsInScope = (coverage.screened?.inScope ?? 0) === 0;

  if (loadState !== "ready") {
    return (
      <div className="workflow-bar workflow-bar-load-state" aria-live="polite">
        {loadState === "loading" ? (
          <p>Loading workflow…</p>
        ) : (
          <>
            <p>Couldn't load the workflow.</p>
            <button type="button" className="secondary-button" onClick={props.onRetryLoad}>
              Retry
            </button>
          </>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="workflow-bar">
        <ol className="workflow-steps">
          <WorkflowStep
            n={1}
            title="Screen"
            icon={<Sparkles size={16} />}
            done={workflow.screened}
            busy={props.screeningRunning}
            busyLabel="Screening…"
            // Needs submitted applicants in the shared screening scope and no estimate
            // prompt open. Emptiness is the union scope (coverage.screened.inScope), NOT
            // this member's own eligible count — Screen is a shared action over the union
            // pool, so gating on a member's personal view would disable it (amber but
            // unclickable) whenever their view is emptier than the committee's.
            disabled={
              !workflow.applicationsAvailable ||
              props.screeningRunning ||
              props.screeningEstimateLoading ||
              screeningEstimate !== null ||
              noApplicantsInScope
            }
            disabledTitle={
              !workflow.applicationsAvailable
                ? "No submitted applications yet."
                : noApplicantsInScope
                  ? "No applicants to screen."
                  : undefined
            }
            onClick={props.onRequestScreening}
            coverage={workflow.screened ? coverage.screened : undefined}
            progress={screeningProgress}
          />
          <WorkflowStep
            n={2}
            title="Rank"
            icon={<Sparkles size={16} />}
            // Done only once the final pass (scoring) has full coverage, which
            // coverage tracks so an applicant edit correctly shows it stale.
            done={workflow.candidatesScored}
            busy={props.rankRunning}
            busyLabel="Ranking…"
            // Needs a screening run, applicants in the SHARED pool, and no open estimate.
            // Emptiness is the union scope (coverage.screened.inScope — the shared pool Rank
            // scores over), NOT this member's own eligible count: Rank is a shared action, so
            // a member with an emptier personal view must not see it amber-but-disabled.
            disabled={
              !workflow.screened ||
              props.rankRunning ||
              props.rankEstimateLoading ||
              rankEstimate !== null ||
              noApplicantsInScope
            }
            disabledTitle={
              !workflow.screened
                ? "Run Screen first."
                : noApplicantsInScope
                  ? "No applicants to rank."
                  : undefined
            }
            onClick={props.onRequestRank}
            coverage={coverage.candidatesScored}
            // Rank's currency is the pool fingerprint, not score coverage: a pool
            // change makes ranking out of date even with full coverage. A pending
            // proposal also ambers it — the proposed axis stays inert until a discovery
            // run grounds it, so the step is genuinely out of date until then.
            outOfDate={
              workflow.candidatesScored && (!workflow.rankingCurrent || hasPendingProposals)
            }
            staleTitle={
              hasPendingProposals
                ? "You proposed new criteria — run Rank to discover and apply them."
                : "The applicant pool changed — score missing applicants or discover fresh criteria."
            }
            // Only scoring has a candidate count. Criteria's total is the discovery
            // fan-out width, not "candidates processed", and consolidation is one
            // opaque call, so neither should render a misleading 0/5-style fraction.
            progress={rankProgress?.phase === "scores" ? rankProgress : null}
            last
          />
        </ol>
        {currentOpenings.length ? (
          <div className="workflow-opening-scope">
            <span className="workflow-opening-label">Viewing</span>
            <div className="segmented" role="group" aria-label="Filter applications and ranking by opening">
              <button
                type="button"
                className="segment"
                aria-pressed={props.selectedOpeningIds.length === 0}
                onClick={() => props.onOpeningScopeChange([])}
              >
                All openings
              </button>
              {currentOpenings.map((opening) => {
                const selected = props.selectedOpeningIds.includes(opening.id);
                return (
                  <button
                    key={opening.id}
                    type="button"
                    className="segment"
                    aria-pressed={selected}
                    onClick={() => props.onOpeningScopeChange(
                      selected
                        ? props.selectedOpeningIds.filter((id) => id !== opening.id)
                        : [...props.selectedOpeningIds, opening.id],
                    )}
                  >
                    {openingLabel(opening)}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>

      {props.screeningEstimateLoading ? (
        <div className="run-confirm" aria-live="polite">
          <div className="run-confirm-body">
            <strong>Estimating screening cost…</strong>
          </div>
          <div className="run-confirm-actions">
            <button className="secondary-button" type="button" onClick={props.onCancelScreening}>
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
                {screeningEstimate.cached === 1 ? " has" : "s have"} been checked. New or updated submissions will appear here
                when screening is needed again.
              </p>
            ) : (
              <p>
                Analyze {screeningEstimate.toAnalyze} eligible applicant{screeningEstimate.toAnalyze === 1 ? "" : "s"}
                {screeningEstimate.cached > 0 ? ` (${screeningEstimate.cached} already cached)` : ""}. Estimated cost{" "}
                <strong>{money(screeningEstimate.estimatedUsd)}</strong> (cap ${screeningEstimate.capUsd.toFixed(2)}).
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
                {props.screeningRunning ? "Running…" : "Confirm & run"}
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

      {props.rankEstimateLoading ? (
        <div className="run-confirm" aria-live="polite">
          <div className="run-confirm-body">
            <strong>Estimating ranking cost…</strong>
          </div>
          <div className="run-confirm-actions">
            <button className="secondary-button" type="button" onClick={props.onCancelRank}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {rankEstimate ? (
        <div className="run-confirm">
          <div className="run-confirm-body">
            <strong>
              {hasPendingProposals
                ? pendingProposals.length === 1
                  ? "Apply your proposed criterion?"
                  : "Apply your proposed criteria?"
                : scoreCurrentEstimate?.toAnalyze === 0
                  ? "Ranking is up to date."
                  : scoreCurrentEstimate
                    ? "Update the ranking?"
                    : "Rank the candidates?"}
            </strong>
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
            {scoreCurrentEstimate && hasMissingScores ? (
              <>
                <p>
                  <strong>Score missing applicants</strong> against the current {scoreCurrentEstimate.dimensions} criteria.
                  The criteria and your tier layout stay unchanged. Estimated cost{" "}
                  <strong>~{money(scoreCurrentEstimate.estimatedUsd)}</strong> (cap ${scoreCurrentEstimate.capUsd.toFixed(2)}).
                </p>
                {!scoreCurrentEstimate.withinCap ? (
                  <p className="run-confirm-warn">
                    Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
                  </p>
                ) : null}
              </>
            ) : null}
            {scoreCurrentEstimate?.toAnalyze === 0 ? (
              <p>All {scoreCurrentEstimate.cached} eligible applicants are already scored against these criteria.</p>
            ) : null}
            <div>
              <p>
                {hasMissingScores ? "Or, " : ""}<strong>Discover new criteria</strong> that distinguish this pool and score all{" "}
                {rankEstimate.eligible} eligible applicant{rankEstimate.eligible === 1 ? "" : "s"} against them.
                Estimated cost <strong>~{money(rankEstimate.estimatedUsd)}</strong> (cap $
                {rankEstimate.capUsd.toFixed(2)}).
              </p>
              {hasCurrentCriteria ? (
                <p>
                  Criteria you've tiered are kept and re-scored; only ignored criteria may be
                  dropped or re-carved.
                </p>
              ) : null}
              {!rankEstimate.withinCap ? (
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
            {scoreCurrentEstimate && hasMissingScores ? (
              <button
                className={hasPendingProposals ? "secondary-button" : "primary-button"}
                type="button"
                onClick={() => props.onRunRank("score-current")}
                disabled={props.rankRunning || !scoreCurrentEstimate.withinCap}
              >
                {props.rankRunning ? "Running…" : "Score missing applicants"}
              </button>
            ) : null}
            <button
              className={hasMissingScores && !hasPendingProposals ? "secondary-button" : "primary-button"}
              type="button"
              onClick={() => props.onRunRank("discover")}
              disabled={props.rankRunning || !rankEstimate.withinCap}
            >
              {props.rankRunning ? "Running…" : hasCurrentCriteria ? "Discover new criteria" : "Confirm & run"}
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
                ? criteriaStageLabel(rankProgress.stage ?? "discovering", rankProgress.total)
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
          {/* The model's live reasoning box. It fills during the opaque criteria
              calls (discovery + match) and the consolidation call so those waits
              read as active work, not a hang. Once populated it PERSISTS through
              scoring — scoring adds nothing to it, but vanishing the box mid-run
              looked like the reasoning had been lost. The component self-hides
              until the first delta, so it's absent only before criteria streams. */}
          <CriteriaThinking text={props.criteriaThinking} />
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
