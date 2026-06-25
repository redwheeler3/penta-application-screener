import { AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clipboard, GripVertical, ListOrdered, LogIn, LogOut, Plus, Printer, RefreshCw, Settings, Sparkles, X } from "lucide-react";
import { type ReactNode, type SyntheticEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  KeyboardSensor,
  closestCorners,
  useSensor,
  useSensors,
  useDroppable,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  horizontalListSortingStrategy,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { HouseIcon } from "./HouseIcon";

type CurrentUser = {
  id: number;
  email: string;
  displayName: string;
  avatarUrl: string | null;
  role: "admin" | "member";
};

// Mirrors backend AISettings. The UI only edits spending_cap_usd; the rest are
// round-tripped so a save never resets them.
type AISettings = {
  region: string;
  first_pass_model: string;
  synthesis_model: string;
  spending_cap_usd: number;
  max_workers: number;
};

type AppSettings = {
  google_sheet_id: string;
  income_min: number;
  income_max: number;
  min_adult_age: number;
  max_child_age: number;
  min_children: number;
  max_children: number;
  max_dogs: number;
  max_cats: number;
  allow_other_pets: boolean;
  disabled_rules: string[];
  ai: AISettings;
};

type SettingsResponse = {
  settings: AppSettings;
  google_sheet_url: string;
  google_sheet_title: string | null;
};

type AppStatus = "eligible" | "ineligible";
type StatusSource = "untouched" | "rules" | "ai" | "human";

// Counts keyed by the real columns; named views are composed client-side.
type DashboardCounts = {
  submitted: number;
  status: Record<AppStatus, number>;
  source: Record<StatusSource, number>;
};

// Which screening steps have run (persisted), so workflow gating survives a reload.
type WorkflowState = {
  synced: boolean;
  // Whether the latest import used the settings as they are now. False flags the
  // Import step amber: a re-import would reclassify eligibility.
  importCurrent: boolean;
  qualityChecksRun: boolean;
  essaysAnalyzed: boolean;
  patternsDiscovered: boolean;
  candidatesScored: boolean;
  // Same truth the Rank no-op gate uses; the "needs re-run" badge reads this (not
  // score coverage), so a pool change still flags re-rank with full coverage.
  rankingCurrent: boolean;
};

// Per-AI-step coverage of the current scope. cached < inScope means results went
// stale, so the UI warns instead of a misleading done-check. Keys are absent for
// steps not yet computable (e.g. scoring before patterns exist).
type Coverage = Partial<
  Record<"qualityChecksRun" | "essaysAnalyzed" | "candidatesScored", { cached: number; inScope: number }>
>;

// Faceted counts: each facet reflects the other group's active filter, so the two
// filter groups stay consistent.
type AppFacets = {
  status: Record<AppStatus, number>;
  source: Record<StatusSource, number>;
};

type ApplicationSummary = {
  id: number;
  primaryEmail: string;
  applicantName: string | null;
  coApplicantName: string | null;
  status: AppStatus;
  statusSource: StatusSource;
  // True when machine findings changed since a human last reviewed.
  stale: boolean;
  hardFilterReasons: Array<{ code: string; message: string; details: Record<string, unknown> }>;
  childCount: number | null;
  householdIncome: number | null;
  // null = AI quality-flag pass not run; int = flag count (0 = ran clean).
  flagCount: number | null;
  // Distinct flag categories from the latest pass (null if not run).
  flagCategories: string[] | null;
  createdAt: string | null;
};

type Essay = {
  label: string;
  question: string;
  answer: string;
};

type QualityFlag = {
  category: string;
  severity: "info" | "notable";
  summary: string;
  evidence: string;
};

// Neutral factual extraction across the four essays. Mirrors backend
// EssayAnalysisReport. Informational only — never affects status.
type EssayAnalysis = {
  summary: string;
  household_context: string | null;
  employment_background: string | null;
  interests: string[];
  values: string[];
  skills_offered: string[];
  prior_co_op_experience: string | null;
  stated_motivations: string[];
  stated_contributions: string[];
  evidence: string[];
};

type ApplicationDetail = ApplicationSummary & {
  // What the machine would decide from the current findings — i.e. the result of
  // clearing a human override. Lets the status control show the automatic verdict.
  autoStatus: AppStatus;
  autoStatusSource: StatusSource;
  normalized: Record<string, unknown>;
  essays: Essay[];
  // null = quality-flag pass not yet run for this application; [] = ran, clean.
  qualityFlags: QualityFlag[] | null;
  rawRow?: Record<string, unknown>;
  // The model's free-text reasoning from the latest quality-flag pass.
  aiNarrative?: string | null;
  // null = essay-analysis pass not yet run for this application.
  essayAnalysis?: EssayAnalysis | null;
  // This candidate's scores against the current run's dimensions, by |impact|
  // descending — the same ranking contributions the ranked-list row slices. null =
  // no run, or not scored under it.
  dimensionScores?: DimensionContribution[] | null;
};

// The current run's discovered dimensions, from GET /screening/current.
type PoolDimension = {
  key: string;
  name: string;
  definition: string;
  why_it_differentiates: string;
};

// --- Ranking: the deterministic ranked shortlist from GET /screening/ranking,
// pure math over the cached scores. Mirrors the backend ranking dataclasses.

// How one dimension fed a candidate's fit. `impact` = weight × (score − pool mean):
// magnitude ranks "what mattered", sign gives direction.
type DimensionContribution = {
  dimension_key: string;
  name: string;
  score: number;
  weight: number;
  impact: number;
  confidence: "low" | "medium" | "high";
  rationale: string;
  evidence: string;
};

type RankedCandidate = {
  application_id: number;
  name: string | null;
  rank: number; // 1-based position
  fit: number; // 0..1 weighted average — supporting detail, not the headline
  band: string; // relative pool-position label (Strong fit … Limited)
  contributions: DimensionContribution[];
};

type RankingState = {
  runId: number;
  weights: Record<string, number>;
  scoredCount: number;
  candidates: RankedCandidate[];
  // Unacknowledged new dimensions, recomputed on every tier save so badges clear
  // in the same round-trip.
  newDimensionKeys: string[];
};

// One importance tier. Same tier → equal weight; higher tiers weigh more; Ignore
// weighs 0. The backend stores only working tiers and synthesizes the Ignore zone
// for display (the one with `ignore: true`), so the flag is optional here.
type Tier = {
  id: string;
  label: string;
  dimension_keys: string[];
  ignore?: boolean;
};

type ScreeningRunState = {
  runId: number;
  name: string;
  status: string;
  summary: string;
  dimensions: PoolDimension[];
  // New dimensions with no confident match to a prior one — they start in Ignore,
  // badged "new" until the committee triages them. Empty on a first run.
  newDimensionKeys: string[];
};

// A notification toast. Success toasts auto-dismiss; error toasts persist until
// dismissed (and offer a copy button), so a failure can't scroll away unread.
type Toast = { id: number; message: string; variant: "success" | "error" };

type QualityFlagEstimate = {
  total: number;
  to_analyze: number;
  cached: number;
  estimated_usd: number;
  cap_usd: number;
  within_cap: boolean;
};

// Combined cost projection for the Rank chain, from GET /screening/rank/estimate.
// `approximate` is always true: scoring is priced as a whole-pool ceiling.
type RankEstimate = {
  eligible: number;
  breakdown: {
    essays_usd: number;
    criteria_usd: number;
    // The dimension identity-match call; 0 on a first run (pass skipped).
    match_usd: number;
    scoring_usd: number;
  };
  essays_cached: number;
  estimated_usd: number;
  approximate: boolean;
  cap_usd: number;
  within_cap: boolean;
  // True when the pool is unchanged — ranking is already current, so re-running is
  // blocked.
  ranking_current: boolean;
};

type SortKey = "applicant" | "co_applicant" | "children" | "income" | "status";
type SortState = { key: SortKey; direction: "asc" | "desc" } | null;

// Committee-facing labels for the normalized field keys. Keys not listed here
// fall back to a title-cased version of the raw key.
const FIELD_LABELS: Record<string, string> = {
  applicant_name: "Applicant name",
  co_applicant_name: "Co-applicant name",
  applicant_age: "Applicant age",
  co_applicant_age: "Co-applicant age",
  adult_count: "Adults",
  child_count: "Number of children",
  child_details: "Children",
  household_income: "Household income",
  applicant_income: "Applicant income",
  co_applicant_income: "Co-applicant income",
  has_real_estate: "Owns real estate",
  pets_text: "Pets",
  co_applicant_phone: "Co-applicant phone",
  co_applicant_email: "Co-applicant email",
  applicant_email: "Applicant email",
  form_submission_email: "Form submission email",
  applicant_employment_start: "Applicant employment start",
  co_applicant_employment_start: "Co-applicant employment start",
};

// Normalized fields that should render as currency.
const MONEY_FIELDS = new Set(["household_income", "applicant_income", "co_applicant_income"]);

// Human-readable labels for AI quality-flag categories.
const FLAG_CATEGORY_LABELS: Record<string, string> = {
  placeholder_name: "Placeholder name",
  suspicious_name: "Suspicious name",
  minimal_essay: "Minimal essay",
  spam_essay: "Spam essay",
  ai_generated_essay: "AI-generated essay",
  duplicated_answers: "Duplicated answers",
  internal_inconsistency: "Internal inconsistency",
  fake_contact: "Suspicious contact info",
  pet_policy: "Pet policy",
  other: "Other",
};

// Maps a filter reason code to the normalized field(s) that caused it, so the
// detail view can highlight the offending value next to the reason.
const REASON_FIELDS: Record<string, string[]> = {
  income_below_range: ["household_income"],
  income_above_range: ["household_income"],
  income_arithmetic_mismatch: ["household_income", "applicant_income", "co_applicant_income"],
  owns_real_estate: ["has_real_estate"],
  applicant_under_min_age: ["applicant_age"],
  co_applicant_under_min_age: ["co_applicant_age"],
  child_count_mismatch: ["child_count", "child_details"],
  child_age_over_max: ["child_details"],
  too_few_children: ["child_count"],
  too_many_children: ["child_count"],
  child_age_exceeds_parent: ["child_details", "applicant_age", "co_applicant_age"],
  co_applicant_incomplete: ["co_applicant_name", "co_applicant_age", "co_applicant_phone", "co_applicant_email"],
  future_employment_start: ["applicant_employment_start", "co_applicant_employment_start"],
};

function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Status and "who set it" are independent axes, shown as separate columns.
const STATUS_LABELS: Record<AppStatus, string> = {
  eligible: "Eligible",
  ineligible: "Ineligible",
};

// Short label for the "Decided by" column. "untouched" means no actor changed
// the status, so it shows nothing.
const SOURCE_LABELS: Record<StatusSource, string> = {
  untouched: "—",
  rules: "Rules",
  ai: "AI",
  human: "Reviewer",
};

// Longer, non-prescriptive sentence for the candidate detail page.
const SOURCE_DESCRIPTIONS: Record<StatusSource, string> = {
  untouched: "Passed the deterministic rules; the AI pass raised no flags.",
  rules: "Set ineligible by the deterministic screening rules.",
  ai: "Flagged by the AI quality pass.",
  human: "Set by a reviewer.",
};

function flagCategoryLabel(category: string): string {
  return FLAG_CATEGORY_LABELS[category] ?? category;
}

// Map a relative fit band ("Strong fit" … "Limited") to a CSS modifier class.
// Derived from the label so the backend stays the single source of band names.
function bandClass(band: string): string {
  return band.toLowerCase().replace(/[^a-z]+/g, "-");
}

// A dimension SCORE (0..1) as a qualitative band + CSS modifier — the applicant's
// strength on that axis (not the model's confidence). Colour ramp strong→green,
// moderate→blue, weak→amber.
function scoreBand(score: number): { label: string; cls: string } {
  if (score >= 0.66) return { label: "Strong", cls: "score-strong" };
  if (score >= 0.33) return { label: "Moderate", cls: "score-moderate" };
  return { label: "Weak", cls: "score-weak" };
}

// Percent complete (0–100) for a quality-flag run, used for both the label text
// and the progress-bar width so the two never drift apart.
function qfPercent(progress: { processed: number; total: number }): number {
  return (progress.processed / progress.total) * 100;
}

// Render one essay-analysis prose field as a dt/dd row, omitted when the model
// captured nothing for it (null = "applicant did not address this").
function renderEssayText(label: string, value: string | null): ReactNode {
  if (!value) return null;
  return (
    <div className="essay-analysis-field">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

// Render one essay-analysis list field as chips, omitted when empty.
function renderEssayChips(label: string, values: string[]): ReactNode {
  if (!values || values.length === 0) return null;
  return (
    <div className="essay-analysis-field">
      <dt>{label}</dt>
      <dd className="essay-analysis-chips">
        {values.map((value, i) => (
          <span key={i} className="essay-analysis-chip">
            {value}
          </span>
        ))}
      </dd>
    </div>
  );
}

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

// The configured sheet id from a server response: prefer the resolved URL, falling
// back to the bare id. Returns "" when no sheet is configured.
function resolveSheetId(payload: SettingsResponse): string {
  return payload.google_sheet_url || payload.settings.google_sheet_id;
}

// --- Tier-list maker ---------------------------------------------------------
//
// The committee drags dimensions into importance tiers (+ an Ignore zone); higher
// tiers weigh more, Ignore weighs 0. Layout edits are the source of truth — the
// backend derives weights and re-sorts. Drag uses @dnd-kit; final placement is
// computed on drop (no live re-parenting).

// Move a dimension into a target tier, optionally before a specific chip. Returns
// a new tier array; pure so it is easy to reason about and the caller persists it.
function moveDimensionToTier(
  tiers: Tier[],
  dimKey: string,
  targetTierId: string,
  beforeKey: string | null,
): Tier[] {
  return tiers.map((tier) => {
    const without = tier.dimension_keys.filter((k) => k !== dimKey);
    if (tier.id !== targetTierId) {
      return { ...tier, dimension_keys: without };
    }
    if (beforeKey && beforeKey !== dimKey) {
      const at = without.indexOf(beforeKey);
      if (at >= 0) {
        return {
          ...tier,
          dimension_keys: [...without.slice(0, at), dimKey, ...without.slice(at)],
        };
      }
    }
    return { ...tier, dimension_keys: [...without, dimKey] };
  });
}

function tierIndexOfKey(tiers: Tier[], dimKey: string): number {
  return tiers.findIndex((t) => t.dimension_keys.includes(dimKey));
}

// Collision detection: the tier containing the *center of the dragged chip* wins.
// Using the midpoint (not corners) keeps the wide overlay from straying into the
// neighbouring tier. Falls back to `closestCorners` when the center is outside
// every tier (gap between rows, or keyboard dragging with no moving rect).
const tierCollisionDetection: CollisionDetection = (args) => {
  const rect = args.collisionRect;
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const containing = args.droppableContainers.filter((container) => {
    const r = args.droppableRects.get(container.id);
    return r && cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom;
  });
  if (containing.length > 0) {
    return containing.map((container) => ({ id: container.id }));
  }
  return closestCorners(args);
};

// The visual chip (used in place and inside the DragOverlay). `dragging` adds the
// lifted overlay look. `isNew` badges a freshly-discovered dimension awaiting
// triage; the badge clears once it's dragged into a working tier.
function ChipBody(props: {
  label: string;
  dragging?: boolean;
  isNew?: boolean;
  onDismiss?: () => void;
}): ReactNode {
  return (
    <span className={`tier-chip${props.dragging ? " tier-chip-overlay" : ""}${props.isNew ? " tier-chip-new" : ""}`}>
      <GripVertical size={12} className="tier-chip-grip" />
      {props.label}
      {props.isNew ? (
        <span className="tier-chip-new-badge">
          New
          {props.onDismiss ? (
            <button
              type="button"
              className="tier-chip-new-dismiss"
              aria-label="Mark reviewed"
              title="Mark reviewed — keep in Ignore"
              // Stop pointerdown so the dnd-kit drag sensor never starts on the ✕.
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                props.onDismiss!();
              }}
            >
              <X size={10} strokeWidth={3} />
            </button>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}

// A draggable dimension chip. While dragging, the original is hidden (opacity 0)
// and a DragOverlay copy follows the cursor across tiers (see TierList), so the
// drag isn't clipped to its tier's box.
function DimensionChip(props: {
  dimKey: string;
  label: string;
  isNew?: boolean;
  onDismiss?: () => void;
}): ReactNode {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: props.dimKey });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    // Hide the in-place chip entirely while it's the active drag; the overlay
    // copy is what the user sees moving.
    opacity: isDragging ? 0 : 1,
  };
  return (
    <span ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <ChipBody label={props.label} isNew={props.isNew} onDismiss={props.onDismiss} />
    </span>
  );
}

// One tier row: a droppable target (so chips can land on empty space) wrapping a
// sortable context of its chips, plus tier controls.
function TierRow(props: {
  tier: Tier;
  labelFor: (key: string) => string;
  newKeys: Set<string>;
  isOver: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  onRename: (label: string) => void;
  // Acknowledge "new" dimensions in place (badge ✕ / "mark all reviewed").
  onAcknowledge: (keys: string[]) => void;
}): ReactNode {
  const { tier, isOver } = props;
  // The droppable is the WHOLE row, so its rect covers the full tier height (no
  // dead space below the chips). The highlight is driven by the parent's tracked
  // `overTierId` (`isOver`), not this hook's own, which flickers over chips.
  const { setNodeRef } = useDroppable({ id: tier.id });
  return (
    <div
      ref={setNodeRef}
      className={`tier-row ${tier.ignore ? "tier-row-ignore" : ""} ${isOver ? "tier-row-over" : ""}`}
    >
      <div className="tier-row-head">
        {tier.ignore ? (
          <span className="tier-label tier-label-ignore">{tier.label}</span>
        ) : (
          <input
            className="tier-label-input"
            value={tier.label}
            aria-label="Tier name"
            onChange={(e) => props.onRename(e.target.value)}
          />
        )}
        {!tier.ignore ? (
          <div className="tier-controls">
            <button type="button" className="stepper-button" aria-label="Move tier up"
              disabled={!props.canMoveUp} onClick={props.onMoveUp}>
              <ChevronUp size={13} />
            </button>
            <button type="button" className="stepper-button" aria-label="Move tier down"
              disabled={!props.canMoveDown} onClick={props.onMoveDown}>
              <ChevronDown size={13} />
            </button>
            <button type="button" className="stepper-button" aria-label="Remove tier"
              onClick={props.onRemove}>
              <X size={13} />
            </button>
          </div>
        ) : null}
      </div>
      <SortableContext items={tier.dimension_keys} strategy={horizontalListSortingStrategy}>
        <div className="tier-chips">
          {tier.dimension_keys.length === 0 ? (
            <span className="tier-empty">Drag criteria here</span>
          ) : (
            tier.dimension_keys.map((key) => {
              // "New" badge only while the dimension is still parked in Ignore;
              // dragging it into a working tier triages it, so the badge clears.
              const isNew = props.newKeys.has(key) && Boolean(tier.ignore);
              return (
                <DimensionChip
                  key={key}
                  dimKey={key}
                  label={props.labelFor(key)}
                  isNew={isNew}
                  onDismiss={isNew ? () => props.onAcknowledge([key]) : undefined}
                />
              );
            })
          )}
          {/* Bulk-acknowledge the new dimensions in this (Ignore) row — flows after
              the chips it acts on. Only shows when at least one new flag is here. */}
          {(() => {
            const newHere = tier.dimension_keys.filter((k) => props.newKeys.has(k));
            return tier.ignore && newHere.length > 0 ? (
              <div className="tier-mark-reviewed-row">
                <button
                  type="button"
                  className="tier-mark-reviewed"
                  onClick={() => props.onAcknowledge(newHere)}
                >
                  <Check size={13} />
                  Clear all {newHere.length} "NEW" flag{newHere.length === 1 ? "" : "s"}
                </button>
              </div>
            ) : null;
          })()}
        </div>
      </SortableContext>
    </div>
  );
}

// A print-only text rendering of the importance tiers (the drag TierList is hidden
// when printing). Gives the printed ranking the context of which dimensions sit in
// which tier, so a reader sees WHY the order came out as it did.
function TierSummaryForPrint(props: {
  tiers: Tier[];
  labelFor: (key: string) => string;
}): ReactNode {
  // Only filled tiers are worth printing; the Ignore zone is kept so a reader sees
  // what was set aside.
  const filled = props.tiers.filter((t) => t.dimension_keys.length > 0);
  if (filled.length === 0) return null;
  return (
    <div className="tier-summary-print">
      <h4>Importance tiers</h4>
      <dl>
        {filled.map((tier) => (
          <div key={tier.id} className="tier-summary-row">
            <dt>{tier.label}</dt>
            <dd>{tier.dimension_keys.map((k) => props.labelFor(k)).join(", ")}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// The tier-list maker. `tiers` is the layout (ordered, with a final Ignore tier);
// `onChange` persists a new layout.
function TierList(props: {
  tiers: Tier[];
  labelFor: (key: string) => string;
  newKeys: Set<string>;
  onAcknowledge: (keys: string[]) => void;
  onChange: (next: Tier[]) => void;
}): ReactNode {
  const { tiers, onChange } = props;
  // The chip being dragged (for the DragOverlay) and the tier the pointer is over
  // (drives the highlight — tracked here, not via each row's flickering isOver).
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [overTierId, setOverTierId] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // Resolve which tier an `over.id` refers to: it is either a tier id (pointer
  // over empty row space) or a chip's dimension key (resolve to its tier).
  function tierIdForOver(overId: string): string | null {
    if (tiers.some((t) => t.id === overId)) return overId;
    const idx = tierIndexOfKey(tiers, overId);
    return idx >= 0 ? tiers[idx].id : null;
  }

  function handleDragStart(event: DragStartEvent) {
    setActiveKey(String(event.active.id));
  }

  function handleDragOver(event: DragOverEvent) {
    const { over } = event;
    setOverTierId(over ? tierIdForOver(String(over.id)) : null);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    setActiveKey(null);
    setOverTierId(null);
    if (!over) return;
    const dimKey = String(active.id);
    const overId = String(over.id);
    // over.id is a tier id (dropped on empty row space) or a chip's dimension key.
    const targetTier = tiers.find((t) => t.id === overId);
    if (targetTier) {
      onChange(moveDimensionToTier(tiers, dimKey, targetTier.id, null));
      return;
    }
    const destIdx = tierIndexOfKey(tiers, overId);
    if (destIdx < 0) return;
    if (overId === dimKey) return; // dropped on itself, no-op
    onChange(moveDimensionToTier(tiers, dimKey, tiers[destIdx].id, overId));
  }

  // The Ignore tier sorts last; working tiers keep their order.
  const working = tiers.filter((t) => !t.ignore);
  const ignore = tiers.find((t) => t.ignore);
  const activeLabel = activeKey ? props.labelFor(activeKey) : null;

  function renameTier(id: string, label: string) {
    onChange(tiers.map((t) => (t.id === id ? { ...t, label } : t)));
  }
  function moveTier(idx: number, delta: number) {
    const next = [...working];
    const [moved] = next.splice(idx, 1);
    next.splice(idx + delta, 0, moved);
    onChange(ignore ? [...next, ignore] : next);
  }
  function removeTier(id: string) {
    // Removing a tier drops its chips into the first working tier (never lost).
    const target = working.find((t) => t.id !== id);
    const removed = tiers.find((t) => t.id === id);
    if (!target || !removed) return;
    const next = tiers
      .filter((t) => t.id !== id)
      .map((t) =>
        t.id === target.id
          ? { ...t, dimension_keys: [...t.dimension_keys, ...removed.dimension_keys] }
          : t,
      );
    onChange(next);
  }
  function addTier() {
    // Insert a new empty tier just above the Ignore zone.
    const id = `tier-${tiers.length}-${working.length}`;
    const newTier: Tier = { id, label: `Tier ${working.length + 1}`, dimension_keys: [], ignore: false };
    onChange(ignore ? [...working, newTier, ignore] : [...working, newTier]);
  }

  return (
    <div className="tier-list">
      <div className="tier-list-head">
        <span className="tier-list-title">Importance tiers</span>
        <button type="button" className="secondary-button tier-add" onClick={addTier}>
          <Plus size={14} /> Add tier
        </button>
      </div>
      <DndContext
        sensors={sensors}
        collisionDetection={tierCollisionDetection}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
      >
        {working.map((tier, idx) => (
          <TierRow
            key={tier.id}
            tier={tier}
            labelFor={props.labelFor}
            newKeys={props.newKeys}
            isOver={overTierId === tier.id}
            canMoveUp={idx > 0}
            canMoveDown={idx < working.length - 1}
            onMoveUp={() => moveTier(idx, -1)}
            onMoveDown={() => moveTier(idx, 1)}
            onRemove={() => removeTier(tier.id)}
            onRename={(label) => renameTier(tier.id, label)}
            onAcknowledge={props.onAcknowledge}
          />
        ))}
        {ignore ? (
          <TierRow
            tier={ignore}
            labelFor={props.labelFor}
            newKeys={props.newKeys}
            isOver={overTierId === ignore.id}
            canMoveUp={false}
            canMoveDown={false}
            onMoveUp={() => {}}
            onMoveDown={() => {}}
            onRemove={() => {}}
            onRename={() => {}}
            onAcknowledge={props.onAcknowledge}
          />
        ) : null}
        {/* The floating copy that follows the cursor freely across tiers — this
            is what makes cross-tier drag smooth instead of clipped to a row. */}
        <DragOverlay>
          {activeLabel ? <ChipBody label={activeLabel} dragging /> : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// Placeholder for the initial render only — the GET /settings fetch on mount
// overwrites draft and saved with the server's values (the backend's AppSettings
// schema is the source of truth for every default). Not canonical.
const defaultSettings: AppSettings = {
  google_sheet_id: "",
  income_min: 70000,
  income_max: 150000,
  min_adult_age: 18,
  max_child_age: 17,
  min_children: 1,
  max_children: 4,
  max_dogs: 1,
  max_cats: 1,
  allow_other_pets: false,
  disabled_rules: [],
  ai: {
    region: "us-west-2",
    first_pass_model: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    synthesis_model: "us.anthropic.claude-sonnet-4-6",
    spending_cap_usd: 1.0,
    max_workers: 50,
  },
};

// Kept in alphabetical order by label so the toggle grid reads predictably; the
// render sorts defensively too, so a new rule added out of order still slots in.
const ALL_RULES = [
  { id: "applicant_under_min_age", label: "Applicant under minimum age" },
  { id: "child_age_exceeds_parent", label: "Child age exceeds parent" },
  { id: "child_age_over_max", label: "Child over max age" },
  { id: "child_count_mismatch", label: "Child count mismatch" },
  { id: "co_applicant_incomplete", label: "Co-applicant incomplete" },
  { id: "co_applicant_under_min_age", label: "Co-applicant under minimum age" },
  { id: "future_employment_start", label: "Future employment start" },
  { id: "income_above_range", label: "Income above range" },
  { id: "income_arithmetic_mismatch", label: "Income arithmetic mismatch" },
  { id: "income_below_range", label: "Income below range" },
  { id: "negative_number", label: "Negative number" },
  { id: "owns_real_estate", label: "Real estate ownership" },
  { id: "too_few_children", label: "Too few children" },
  { id: "too_many_children", label: "Too many children" },
] as const;

export function App() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoadingUser, setIsLoadingUser] = useState(true);
  // The form draft the user edits. Separate from `saved` so typing never affects
  // affordances that gate on persisted state until the change is saved.
  const [draft, setDraft] = useState<AppSettings>(defaultSettings);
  // The last settings persisted on the server. `draft` resets to this on load/save.
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [isSettingsExpanded, setIsSettingsExpanded] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [dashboardCounts, setDashboardCounts] = useState<DashboardCounts>({
    submitted: 0,
    status: { eligible: 0, ineligible: 0 },
    source: { untouched: 0, rules: 0, ai: 0, human: 0 },
  });
  const [workflow, setWorkflow] = useState<WorkflowState>({
    synced: false,
    importCurrent: true,
    qualityChecksRun: false,
    essaysAnalyzed: false,
    patternsDiscovered: false,
    candidatesScored: false,
    rankingCurrent: false,
  });
  const [coverage, setCoverage] = useState<Coverage>({});
  const [isSyncing, setIsSyncing] = useState(false);

  // Workflow notifications surface as bottom-right toasts. Success toasts
  // auto-dismiss; error toasts persist until dismissed. Unique ids let them stack.
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastSeq = useRef(0);

  const TOAST_DURATION_MS = 7000;

  function showToast(message: string) {
    const id = (toastSeq.current += 1);
    setToasts((current) => [...current, { id, message, variant: "success" }]);
    setTimeout(() => {
      setToasts((current) => current.filter((t) => t.id !== id));
    }, TOAST_DURATION_MS);
  }

  function showError(message: string) {
    const id = (toastSeq.current += 1);
    setToasts((current) => [...current, { id, message, variant: "error" }]);
    // No auto-dismiss: errors stay until the user reads and dismisses them.
  }

  function dismissToast(id: number) {
    setToasts((current) => current.filter((t) => t.id !== id));
  }
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [appTotal, setAppTotal] = useState(0);
  const [appPage, setAppPage] = useState(1);
  const [appPageSize, setAppPageSize] = useState(25);
  // Filter mirrors the real columns. A tab sets one of these (or neither for All).
  const [appFilter, setAppFilter] = useState<{ status?: AppStatus; status_source?: StatusSource }>({});
  // Faceted option counts from the latest list response (reflect the cross-group filter).
  const [appFacets, setAppFacets] = useState<AppFacets | null>(null);
  const [appSearch, setAppSearch] = useState("");
  const [appSort, setAppSort] = useState<SortState>(null);
  const [selectedApp, setSelectedApp] = useState<ApplicationDetail | null>(null);

  // AI run flows share a shape: estimate (confirmation) -> running -> result.
  // Outcomes surface as toasts, so no per-step message state is kept here.
  const [qfEstimate, setQfEstimate] = useState<QualityFlagEstimate | null>(null);
  const [qfRunning, setQfRunning] = useState(false);
  // Live progress while the run streams: processed/total applications.
  const [qfProgress, setQfProgress] = useState<{ processed: number; total: number } | null>(null);

  // The current run's discovered dimensions, shown above the list once Rank has run.
  const [screeningRun, setScreeningRun] = useState<ScreeningRunState | null>(null);

  // Rank (the combined essays → criteria → scores chain): one estimate-confirm-stream
  // flow over all three passes, gated once on the combined cost.
  const [rankEstimate, setRankEstimate] = useState<RankEstimate | null>(null);
  const [rankRunning, setRankRunning] = useState(false);
  // Live progress while the chain streams. `phase` is the running pass;
  // processed/total drive the bar (criteria is a single call, so it has no fraction).
  const [rankProgress, setRankProgress] = useState<
    { phase: "essays" | "criteria" | "scores"; processed: number; total: number } | null
  >(null);

  // The deterministic ranked shortlist. `showRanking` toggles the ranked view over
  // the list; null ranking means not yet fetched.
  const [ranking, setRanking] = useState<RankingState | null>(null);
  const [showRanking, setShowRanking] = useState(false);

  // The committee's importance tiers for the current run. Each edit persists (PUT
  // /tiers) and returns the re-sorted ranking, so tiers and order stay in lockstep.
  const [tiers, setTiers] = useState<Tier[] | null>(null);


  useEffect(() => {
    fetch(`${apiBaseUrl}/auth/me`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { user: CurrentUser | null }) => setUser(payload.user))
      .finally(() => setIsLoadingUser(false));
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }

    fetch(`${apiBaseUrl}/settings`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: SettingsResponse) => applySettingsResponse(payload));
    refreshDashboard();
    refreshScreeningRun();
    fetchApplications({}, 1, "");
  }, [user]);

  // The current run's dimensions, if discovery has run. Returns the promise so
  // callers can await it before rendering anything that resolves dimension keys to
  // names (the tier list's labelFor reads screeningRun.dimensions).
  function refreshScreeningRun() {
    return fetch(`${apiBaseUrl}/screening/current`, { credentials: "include" })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: ScreeningRunState | null) => setScreeningRun(payload))
      .catch(() => setScreeningRun(null));
  }

  function applySettingsResponse(payload: SettingsResponse) {
    const sheetId = resolveSheetId(payload);
    setSaved(payload);
    setDraft({
      ...payload.settings,
      google_sheet_id: sheetId,
    });
    // First-run setup: open the form when there's no sheet configured yet.
    if (!sheetId) {
      setIsSettingsExpanded(true);
    }
  }

  function refreshDashboard() {
    fetch(`${apiBaseUrl}/dashboard`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { counts: DashboardCounts; workflow: WorkflowState; coverage: Coverage }) => {
        setDashboardCounts(payload.counts);
        setWorkflow(payload.workflow);
        setCoverage(payload.coverage ?? {});
      });
  }

  function fetchApplications(
    filter: { status?: AppStatus; status_source?: StatusSource } = appFilter,
    page: number = 1,
    search: string = appSearch,
    pageSize: number = appPageSize,
    sort: SortState = appSort,
  ) {
    const params = new URLSearchParams();
    if (filter.status) params.set("status", filter.status);
    if (filter.status_source) params.set("status_source", filter.status_source);
    if (search) params.set("search", search);
    if (sort) {
      params.set("sort", sort.key);
      params.set("direction", sort.direction);
    }
    params.set("page", String(page));
    params.set("page_size", String(pageSize));

    fetch(`${apiBaseUrl}/applications?${params}`, { credentials: "include" })
      .then((response) => response.json())
      .then(
        (payload: {
          applications: ApplicationSummary[];
          total: number;
          page: number;
          pageSize: number;
          facets: AppFacets;
        }) => {
          setApplications(payload.applications);
          setAppTotal(payload.total);
          setAppPage(payload.page);
          setAppPageSize(payload.pageSize);
          setAppFacets(payload.facets);
        },
      );
  }

  function viewApplication(id: number) {
    fetch(`${apiBaseUrl}/applications/${id}`, { credentials: "include" })
      .then((response) => response.json())
      .then((payload: { application: ApplicationDetail }) => setSelectedApp(payload.application));
  }

  function toggleSort(key: SortKey) {
    // First click sorts ascending; clicking the active column flips direction.
    const next: SortState =
      appSort?.key === key
        ? { key, direction: appSort.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" };
    setAppSort(next);
    fetchApplications(appFilter, 1, appSearch, appPageSize, next);
  }

  function formatFieldValue(value: unknown, key?: string): React.ReactNode {
    if (value == null || value === "") return "—";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (key && MONEY_FIELDS.has(key) && typeof value === "number") {
      return `$${value.toLocaleString()}`;
    }
    if (Array.isArray(value)) {
      if (value.length === 0) return "—";
      return (
        <ul className="field-list">
          {value.map((item, i) => (
            <li key={i}>{formatArrayItem(item)}</li>
          ))}
        </ul>
      );
    }
    if (typeof value === "object") {
      return Object.entries(value as Record<string, unknown>)
        .filter(([, v]) => v != null && v !== "")
        .map(([, v]) => String(v))
        .join(", ");
    }
    return String(value);
  }

  function formatArrayItem(item: unknown): string {
    if (typeof item !== "object" || item === null) return String(item);
    const obj = item as Record<string, unknown>;
    if ("first_name" in obj || "last_name" in obj) {
      const name = [obj.first_name, obj.last_name].filter(Boolean).join(" ");
      return obj.age != null ? `${name} (${obj.age})` : name || "—";
    }
    return Object.values(obj).filter((v) => v != null && v !== "").join(", ");
  }

  function formatErrorDetail(detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (detail == null) return "";
    return JSON.stringify(detail, null, 2);
  }

  function login() {
    window.location.href = `${apiBaseUrl}/auth/google/login`;
  }

  async function logout() {
    await fetch(`${apiBaseUrl}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    setUser(null);
  }

  async function saveSettings(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSavingSettings(true);
    setSettingsMessage("");

    const response = await fetch(`${apiBaseUrl}/settings`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });

    if (response.ok) {
      const payload: SettingsResponse = await response.json();
      applySettingsResponse(payload);
      // Collapse the form after a successful save (applySettingsResponse keeps it
      // open only when no sheet is configured yet).
      if (resolveSheetId(payload)) {
        setIsSettingsExpanded(false);
      }
      setSettingsMessage("Settings saved.");
      refreshDashboard();
    } else {
      setSettingsMessage("Settings could not be saved.");
    }

    setIsSavingSettings(false);
  }

  async function syncApplications() {
    setIsSyncing(true);

    try {
      const response = await fetch(`${apiBaseUrl}/sync/applications`, {
        method: "POST",
        credentials: "include",
      });

      if (response.ok) {
        const payload: {
          syncRun: {
            rowCount: number;
            importedCount: number;
            updatedCount: number;
            unchangedCount: number;
          };
        } = await response.json();
        const { rowCount, importedCount, updatedCount, unchangedCount } = payload.syncRun;
        showToast(
          `Synced ${rowCount} rows: ${importedCount} imported, ${updatedCount} updated, ` +
            `${unchangedCount} unchanged.`,
        );
        refreshDashboard();
        fetchApplications(appFilter, 1, appSearch);
      } else {
        let detail = `Sync failed (HTTP ${response.status}).`;
        try {
          const payload = await response.json();
          if (payload.detail) detail = `Sync failed: ${formatErrorDetail(payload.detail)}`;
        } catch {
          // response body wasn't JSON
        }
        showError(detail);
      }
    } catch (error) {
      showError(
        `Sync error: ${
          error instanceof Error ? error.message : "Network request failed. Check that the backend is running."
        }`,
      );
    }

    setIsSyncing(false);
  }

  // Fetch the cost estimate and show the confirmation prompt. AI never runs
  // without the user first seeing the estimate and confirming (SPEC cost control).
  async function requestQualityFlagsEstimate() {
    // Close the Rank confirmation if open, so only one card shows at a time.
    setRankEstimate(null);
    const response = await fetch(`${apiBaseUrl}/quality-flags/estimate`, { credentials: "include" });
    if (response.ok) {
      const estimate: QualityFlagEstimate = await response.json();
      // Always open the confirmation card — even a $0 no-op (nothing uncached to
      // analyze). The card states there's nothing to do and disables Confirm,
      // rather than firing a transient toast the user might miss.
      setQfEstimate(estimate);
    } else {
      showError("Could not load the AI cost estimate for flagging submissions.");
    }
  }

  async function runQualityFlags() {
    setQfRunning(true);
    setQfEstimate(null);
    setQfProgress(null);
    try {
      const response = await fetch(`${apiBaseUrl}/quality-flags/run`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => null);
        showError(payload?.detail ? `Flagging failed: ${formatErrorDetail(payload.detail)}` : "Flagging failed.");
      } else {
        // Read the NDJSON stream: a progress line per application, then a summary.
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? ""; // keep any partial line for the next chunk
          for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.type === "progress") {
              setQfProgress({ processed: event.processed, total: event.total });
            } else if (event.type === "summary") {
              const failedNote = event.failed
                ? ` ${event.failed} failed and were skipped.`
                : "";
              showToast(
                `Flagging complete: ${event.flagged} flagged of ` +
                  `${event.analyzed + event.cached} analyzed ($${event.totalCostUsd.toFixed(4)}).` +
                  failedNote,
              );
            }
          }
        }
        // Refresh dashboard counts, the application list + facet counts, and the
        // open candidate so new flags/status show immediately after the run.
        refreshDashboard();
        fetchApplications(appFilter, appPage, appSearch);
        if (selectedApp) viewApplication(selectedApp.id);
      }
    } catch (error) {
      showError(error instanceof Error ? `Flagging error: ${error.message}` : "Flagging error.");
    }
    setQfProgress(null);
    setQfRunning(false);
  }

  // Rank: the combined essays → criteria → scores chain. One estimate-confirm-stream
  // flow, cap-checked as a single combined number server-side.
  async function requestRankEstimate() {
    // Close the flagging confirmation so only one card shows at a time.
    setQfEstimate(null);
    const response = await fetch(`${apiBaseUrl}/screening/rank/estimate`, { credentials: "include" });
    if (response.ok) {
      const estimate: RankEstimate = await response.json();
      // Always open the card, even when unchanged: it explains there's nothing to
      // re-rank and disables Confirm, instead of a transient toast.
      setRankEstimate(estimate);
    } else {
      showError("Could not load the AI cost estimate for ranking.");
    }
  }

  async function runRank() {
    setRankRunning(true);
    setRankEstimate(null);
    setRankProgress(null);
    try {
      const response = await fetch(`${apiBaseUrl}/screening/rank/run`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => null);
        showError(payload?.detail ? `Ranking failed: ${formatErrorDetail(payload.detail)}` : "Ranking failed.");
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.type === "phase") {
              // New pass: reset the bar to its total (criteria is one call → no total).
              setRankProgress({ phase: event.phase, processed: 0, total: event.total ?? 0 });
            } else if (event.type === "progress") {
              setRankProgress({ phase: event.phase, processed: event.processed, total: event.total });
            } else if (event.type === "error") {
              showError(event.message || "Ranking failed.");
            } else if (event.type === "summary") {
              const failedNote = event.failed ? ` ${event.failed} failed and were skipped.` : "";
              showToast(
                `Ranking complete: ${event.dimensions} criteria, ${event.scored} candidates scored ` +
                  `($${event.totalCostUsd.toFixed(4)}).` +
                  failedNote,
              );
            }
          }
        }
        // The chain replaced the dimensions and scores. Await the run refresh before
        // reopening the ranking, so the tier list's labelFor has the new run's names
        // before its chips render (else they briefly show raw keys).
        await refreshScreeningRun();
        refreshDashboard();
        if (selectedApp) viewApplication(selectedApp.id);
        if (showRanking) openRanking();
      }
    } catch (error) {
      showError(error instanceof Error ? `Ranking error: ${error.message}` : "Ranking error.");
    }
    setRankProgress(null);
    setRankRunning(false);
  }

  // Fetch the ranked shortlist and tier layout, and open the ranked view. No cost —
  // pure math over the cached scores.
  async function openRanking() {
    setSelectedApp(null);
    const [rankRes, tiersRes] = await Promise.all([
      fetch(`${apiBaseUrl}/screening/ranking`, { credentials: "include" }),
      fetch(`${apiBaseUrl}/screening/tiers`, { credentials: "include" }),
    ]);
    if (rankRes.ok) {
      setRanking(await rankRes.json());
      if (tiersRes.ok) setTiers((await tiersRes.json()).tiers);
      setShowRanking(true);
    } else {
      const payload = await rankRes.json().catch(() => null);
      showError(
        payload?.detail
          ? `Could not load the ranking: ${formatErrorDetail(payload.detail)}`
          : "Could not load the ranking.",
      );
    }
  }

  // Persist a new tier layout. The PUT returns the re-sorted ranking. Optimistically
  // set the tiers so the drag feels instant; reconcile from the response.
  async function saveTiers(next: Tier[], acknowledgedKeys: string[] = []) {
    setTiers(next);
    const response = await fetch(`${apiBaseUrl}/screening/tiers`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tiers: next, acknowledged_keys: acknowledgedKeys }),
    });
    if (response.ok) {
      setRanking(await response.json());
    } else {
      showError("Could not update the tiers.");
      openRanking(); // reconcile back to the server's truth on failure
    }
  }

  // Acknowledge "new" dimensions in place (badge ✕ / "mark all reviewed") — drop
  // them from new_dimension_keys without moving, via the same tiers PUT.
  async function acknowledgeNewDimensions(keys: string[]) {
    if (!tiers || keys.length === 0) return;
    await saveTiers(tiers, keys);
  }

  // Human override of an application's status. The backend marks it human-owned and
  // sticky against future machine runs.
  async function overrideStatus(id: number, status: AppStatus) {
    const response = await fetch(`${apiBaseUrl}/applications/${id}/status`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (response.ok) {
      const payload: { application: ApplicationDetail } = await response.json();
      setSelectedApp(payload.application);
      // Refresh dashboard + list/facet counts so the change shows on "Back to list".
      refreshDashboard();
      fetchApplications(appFilter, appPage, appSearch);
    }
  }

  // Remove a human override, handing the decision back to the machine. The
  // backend recomputes status from the current findings (see DELETE handler).
  async function clearStatusOverride(id: number) {
    const response = await fetch(`${apiBaseUrl}/applications/${id}/status`, {
      method: "DELETE",
      credentials: "include",
    });
    if (response.ok) {
      const payload: { application: ApplicationDetail } = await response.json();
      setSelectedApp(payload.application);
      refreshDashboard();
      fetchApplications(appFilter, appPage, appSearch);
    }
  }

  const hasGoogleSheetLink = Boolean(saved && resolveSheetId(saved));
  // Explicit open/closed state, not derived from the field value — else typing a
  // link would collapse the form before saving.
  const showSettingsForm = isSettingsExpanded;

  return (
    <main className="app-shell">
      <header className="topnav">
        <div className="topnav-inner">
          {user ? (
            <button
              className="brand-lockup brand-button"
              type="button"
              onClick={() => setSelectedApp(null)}
              title="Back to applications"
            >
              <span className="brand-mark" aria-hidden="true">
                <HouseIcon size={30} />
              </span>
              <span className="brand-name">Penta Housing Co-Op</span>
            </button>
          ) : (
            <div className="brand-lockup">
              <span className="brand-mark" aria-hidden="true">
                <HouseIcon size={30} />
              </span>
              <span className="brand-name">Penta Housing Co-Op</span>
            </div>
          )}
          {user ? (
            <div className="toolbar">
              <div className="user-chip">
                <span>{user.displayName}</span>
                <strong>{user.role}</strong>
              </div>
              <button className="icon-button" aria-label="Log out" title="Log out" onClick={logout}>
                <LogOut size={18} />
              </button>
            </div>
          ) : null}
        </div>
      </header>

      <div className="page-heading">
        <h1>Application Screener</h1>
      </div>

      {!user ? (
        <section className="login-panel">
          <span className="panel-kicker">Member access</span>
          <h2>{isLoadingUser ? "Checking session" : "Sign in to continue"}</h2>
          <p>Use your approved Google account.</p>
          <button className="primary-button" onClick={login} disabled={isLoadingUser}>
            <LogIn size={18} />
            <span>Sign in with Google</span>
          </button>
        </section>
      ) : (
        <>
          <section className="settings-panel no-print" aria-label="Admin settings">
            <div className="settings-panel-header">
              <div>
                <h2>Settings</h2>
              </div>
              {hasGoogleSheetLink ? (
                <button
                  className="secondary-button secondary-button-accent"
                  type="button"
                  onClick={() => setIsSettingsExpanded((isExpanded) => !isExpanded)}
                >
                  <Settings size={16} />
                  <span>{isSettingsExpanded ? "Hide settings" : "Edit settings"}</span>
                </button>
              ) : null}
            </div>

            <div className="settings-panel-body">
            {/* Render nothing until the GET /settings fetch resolves. Before it
                does, `saved` is null and the summary condition below is false, so
                the panel would briefly fall through to the full form — a flash of
                the expanded form on every load. Gating on `saved` avoids it; the
                first-run case (no sheet) still opens the form, since `saved` is
                set then, just with an empty sheet id. */}
            {!saved ? null : hasGoogleSheetLink && !showSettingsForm ? (
              <div className="settings-summary">
                <div>
                  <span>Google Sheet</span>
                  {saved.google_sheet_title && saved.google_sheet_url ? (
                    <a className="sheet-reference" href={saved.google_sheet_url} target="_blank" rel="noreferrer">
                      {saved.google_sheet_title}
                    </a>
                  ) : (
                    <strong>{saved.settings.google_sheet_id}</strong>
                  )}
                </div>
                <div>
                  <span>Income range</span>
                  <strong>
                    {`$${saved.settings.income_min.toLocaleString()} – $${saved.settings.income_max.toLocaleString()}`}
                  </strong>
                </div>
              </div>
            ) : (
              <form className="settings-form" onSubmit={saveSettings}>
                <label>
                  <span>Google Sheet link</span>
                  <input
                    value={draft.google_sheet_id}
                    onChange={(event) => setDraft({ ...draft, google_sheet_id: event.target.value })}
                    placeholder="Paste the response spreadsheet link"
                  />
                  {saved?.google_sheet_title && saved.google_sheet_url ? (
                    <a className="sheet-reference" href={saved.google_sheet_url} target="_blank" rel="noreferrer">
                      {saved.google_sheet_title}
                    </a>
                  ) : null}
                </label>
                <label>
                  <span>Income minimum</span>
                  <input
                    type="number"
                    min="0"
                    value={draft.income_min}
                    onChange={(event) => setDraft({ ...draft, income_min: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Income maximum</span>
                  <input
                    type="number"
                    min="0"
                    value={draft.income_max}
                    onChange={(event) => setDraft({ ...draft, income_max: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Min adult age</span>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={draft.min_adult_age}
                    onChange={(event) => setDraft({ ...draft, min_adult_age: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Max child age</span>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={draft.max_child_age}
                    onChange={(event) => setDraft({ ...draft, max_child_age: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Min children per unit</span>
                  <input
                    type="number"
                    min="0"
                    max="20"
                    value={draft.min_children}
                    onChange={(event) => setDraft({ ...draft, min_children: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Max children per unit</span>
                  <input
                    type="number"
                    min="0"
                    max="20"
                    value={draft.max_children}
                    onChange={(event) => setDraft({ ...draft, max_children: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Max dogs</span>
                  <input
                    type="number"
                    min="0"
                    max="10"
                    value={draft.max_dogs}
                    onChange={(event) => setDraft({ ...draft, max_dogs: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Max cats</span>
                  <input
                    type="number"
                    min="0"
                    max="10"
                    value={draft.max_cats}
                    onChange={(event) => setDraft({ ...draft, max_cats: Number(event.target.value) })}
                  />
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={draft.allow_other_pets}
                    onChange={(event) => setDraft({ ...draft, allow_other_pets: event.target.checked })}
                  />
                  <span>Allow other pets</span>
                </label>
                <div className="rules-section">
                  <h3>Screening Rules</h3>
                  <p className="rules-hint">Uncheck a rule to disable it. Disabled rules will not run during screening.</p>
                  <div className="rules-grid">
                    {[...ALL_RULES].sort((a, b) => a.label.localeCompare(b.label)).map((rule) => (
                      <label key={rule.id} className="checkbox-label rule-toggle">
                        <input
                          type="checkbox"
                          checked={!draft.disabled_rules.includes(rule.id)}
                          onChange={(event) => {
                            const disabled = event.target.checked
                              ? draft.disabled_rules.filter((r) => r !== rule.id)
                              : [...draft.disabled_rules, rule.id];
                            setDraft({ ...draft, disabled_rules: disabled });
                          }}
                        />
                        <span>{rule.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="rules-section">
                  <h3>AI Screening</h3>
                  <p className="rules-hint">
                    The quality-flag run is blocked before it starts if its estimated cost
                    exceeds this cap.
                  </p>
                  <label>
                    <span>Spending cap (USD per run)</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={draft.ai.spending_cap_usd}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          ai: { ...draft.ai, spending_cap_usd: Number(event.target.value) },
                        })
                      }
                    />
                  </label>
                </div>
                <div className="settings-actions">
                  <button className="primary-button" type="submit" disabled={isSavingSettings}>
                    {isSavingSettings ? "Saving" : "Save settings"}
                  </button>
                  {settingsMessage ? <span>{settingsMessage}</span> : null}
                </div>
              </form>
            )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header no-print">
              <div>
                <h2>Applications</h2>
              </div>
            </div>
            {/* The ordered screening workflow gets its own full-width band below
                the title: three single-verb steps — Import, Screen, Rank. Rank is
                one button that runs the whole essays → criteria → scores chain
                (the user never runs those sub-passes individually), under one
                combined cost estimate. Each step's input depends on the previous,
                so later steps stay hard-gated until the previous has run; the
                "done" flags come from the backend, so gating survives reload. */}
            <div className="workflow-bar">
              <ol className="workflow-steps">
                <WorkflowStep
                  n={1}
                  title="Import"
                  icon={<RefreshCw size={16} />}
                  done={workflow.synced}
                  busy={isSyncing}
                  busyLabel="Importing"
                  // Step 1 is always available once a sheet is configured. The
                  // caption persists the imported row count (not a fraction).
                  disabled={isSyncing || !hasGoogleSheetLink}
                  disabledTitle="Add a Google Sheet link in settings to import."
                  // Amber when import-relevant settings changed since the last sync:
                  // a re-import would reclassify eligibility.
                  outOfDate={workflow.synced && !workflow.importCurrent}
                  staleTitle="Settings changed since the last import — re-import to apply them."
                  onClick={syncApplications}
                  caption={
                    workflow.synced && dashboardCounts.submitted > 0
                      ? `${dashboardCounts.submitted} rows`
                      : undefined
                  }
                />
                <WorkflowStep
                  n={2}
                  title="Screen"
                  icon={<Sparkles size={16} />}
                  done={workflow.qualityChecksRun}
                  busy={qfRunning}
                  busyLabel="Screening"
                  // Needs a sync, eligible apps, and no estimate prompt open.
                  disabled={
                    !workflow.synced ||
                    qfRunning ||
                    qfEstimate !== null ||
                    dashboardCounts.status.eligible === 0
                  }
                  disabledTitle={
                    !workflow.synced
                      ? "Import applications first."
                      : dashboardCounts.status.eligible === 0
                        ? "No eligible applicants to screen."
                        : undefined
                  }
                  onClick={requestQualityFlagsEstimate}
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
                  busy={rankRunning}
                  busyLabel="Ranking"
                  // Needs screening run, eligible apps, and no open estimate.
                  disabled={
                    !workflow.qualityChecksRun ||
                    rankRunning ||
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
                  onClick={requestRankEstimate}
                  coverage={coverage.candidatesScored}
                  // Rank's currency is the pool fingerprint, not score coverage: a
                  // pool change makes ranking out of date even with full coverage.
                  outOfDate={workflow.candidatesScored && !workflow.rankingCurrent}
                  staleTitle="The applicant pool changed since the last ranking — re-rank to refresh it."
                  progress={rankProgress}
                  last
                />
              </ol>

              {/* Ranked shortlist entry point, beside the steps once Rank has run.
                  Not a gated AI step — viewing the ranking is math, no model. */}
              {workflow.candidatesScored && !selectedApp ? (
                showRanking ? (
                  <button type="button" className="secondary-button workflow-shortlist-button" onClick={() => setShowRanking(false)}>
                    <ChevronLeft size={16} />
                    <span>Back to applications</span>
                  </button>
                ) : (
                  <button type="button" className="primary-button workflow-shortlist-button" onClick={openRanking}>
                    <ListOrdered size={16} />
                    <span>View ranking</span>
                  </button>
                )
              ) : null}
            </div>

            {qfEstimate ? (
              <div className="qf-confirm">
                <div className="qf-confirm-body">
                  <strong>Run AI quality checks?</strong>
                  {qfEstimate.to_analyze === 0 ? (
                    <p>
                      Screening is already up to date — all {qfEstimate.cached} eligible
                      applicant{qfEstimate.cached === 1 ? " has" : "s have"} been checked.
                      Sync new or changed applications to screen again.
                    </p>
                  ) : (
                    <p>
                      Analyze {qfEstimate.to_analyze} eligible applicant
                      {qfEstimate.to_analyze === 1 ? "" : "s"}
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
                      onClick={runQualityFlags}
                      disabled={qfRunning || !qfEstimate.within_cap}
                    >
                      {qfRunning ? "Running" : "Confirm & run"}
                    </button>
                  ) : null}
                  <button className="secondary-button" type="button" onClick={() => setQfEstimate(null)}>
                    {qfEstimate.to_analyze === 0 ? "Close" : "Cancel"}
                  </button>
                </div>
              </div>
            ) : null}
            {qfRunning ? (
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
                    <div
                      className="qf-progress-fill"
                      style={{ width: `${qfPercent(qfProgress)}%` }}
                    />
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
                    <p>
                      Ranking is already up to date for this applicant pool. Sync new
                      or changed applications, or move someone in or out of the
                      eligible pool, to re-rank.
                    </p>
                  ) : (
                    <>
                      <p>
                        This summarizes essays, finds the criteria that distinguish this
                        pool, and scores all {rankEstimate.eligible} eligible applicant
                        {rankEstimate.eligible === 1 ? "" : "s"} against them. Estimated
                        cost <strong>~${rankEstimate.estimated_usd.toFixed(4)}</strong> (cap $
                        {rankEstimate.cap_usd.toFixed(2)}).
                      </p>
                      <ul className="qf-confirm-breakdown">
                        <li>
                          Summarize essays ~${rankEstimate.breakdown.essays_usd.toFixed(4)}
                          {rankEstimate.essays_cached > 0 ? ` (${rankEstimate.essays_cached} cached)` : ""}
                        </li>
                        <li>Find distinguishing criteria ~${rankEstimate.breakdown.criteria_usd.toFixed(4)}</li>
                        {rankEstimate.breakdown.match_usd > 0 ? (
                          <li>Match criteria to the prior run ~${rankEstimate.breakdown.match_usd.toFixed(4)}</li>
                        ) : null}
                        <li>Score against criteria ~${rankEstimate.breakdown.scoring_usd.toFixed(4)} (max)</li>
                      </ul>
                      {rankEstimate.breakdown.match_usd > 0 ? (
                        <p className="qf-confirm-note">
                          Scoring is an upper bound — criteria carried over from the prior run
                          reuse their scores, so the actual cost is usually lower.
                        </p>
                      ) : null}
                    </>
                  )}
                  {!rankEstimate.ranking_current && !rankEstimate.within_cap ? (
                    <p className="qf-confirm-warn">
                      Estimated cost exceeds the spending cap. Raise the cap in settings to proceed.
                    </p>
                  ) : null}
                </div>
                <div className="qf-confirm-actions">
                  {/* No run button when ranking is already current — nothing to
                      confirm, so the card is informational and only offers Close. */}
                  {!rankEstimate.ranking_current ? (
                    <button
                      className="primary-button"
                      type="button"
                      onClick={runRank}
                      disabled={rankRunning || !rankEstimate.within_cap}
                    >
                      {rankRunning ? "Running" : "Confirm & run"}
                    </button>
                  ) : null}
                  <button className="secondary-button" type="button" onClick={() => setRankEstimate(null)}>
                    {rankEstimate.ranking_current ? "Close" : "Cancel"}
                  </button>
                </div>
              </div>
            ) : null}
            {rankRunning ? (
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

            {/* The current run's discovered criteria — the axes scoring rates each
                candidate on. Shown above the list and the shortlist, not when a
                candidate is open. Collapsed by default. */}
            {screeningRun && !selectedApp ? (() => {
              // Order criteria most→least important by tier position (Ignore last;
              // discovery order within a tier), falling back to discovery order.
              const rankOf = new Map<string, number>();
              (tiers ?? []).forEach((tier, tierIdx) => {
                tier.dimension_keys.forEach((key) => rankOf.set(key, tierIdx));
              });
              const orderedDimensions = [...screeningRun.dimensions].sort(
                (a, b) =>
                  (rankOf.get(a.key) ?? Number.MAX_SAFE_INTEGER) -
                  (rankOf.get(b.key) ?? Number.MAX_SAFE_INTEGER),
              );
              return (
              <details className="dimensions-panel">
                <summary>
                  Screening criteria ({screeningRun.dimensions.length})
                </summary>
                <p className="dimensions-summary">{screeningRun.summary}</p>
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
            })() : null}

            {/* The ranked shortlist: a decision surface, not a browse table. The
                order IS the product — read top-down. The band label and rationale
                lead; numbers are supporting detail. */}
            {showRanking && !selectedApp && ranking ? (
              <div className="ranking-view">
                <div className="ranking-header">
                  <div>
                    <h3>Candidate ranking</h3>
                    <p className="ranking-subhead">
                      {ranking.scoredCount} candidate{ranking.scoredCount === 1 ? "" : "s"} scored,
                      ranked by overall fit. Drag criteria into importance tiers below to re-rank.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="secondary-button no-print"
                    onClick={() => window.print()}
                  >
                    <Printer size={16} />
                    Print
                  </button>
                </div>

                {/* Tier-list: drag criteria into importance tiers; the ranking
                    re-sorts on each edit (deterministic, no model call). */}
                {tiers && screeningRun ? (
                  <>
                    <TierList
                      tiers={tiers}
                      labelFor={(key) =>
                        screeningRun.dimensions.find((d) => d.key === key)?.name ?? key
                      }
                      // Read from ranking (refreshed on every save) so badges clear
                      // immediately when a dimension is placed or acknowledged.
                      newKeys={new Set(ranking.newDimensionKeys)}
                      onAcknowledge={acknowledgeNewDimensions}
                      onChange={saveTiers}
                    />
                    <TierSummaryForPrint
                      tiers={tiers}
                      labelFor={(key) =>
                        screeningRun.dimensions.find((d) => d.key === key)?.name ?? key
                      }
                    />
                  </>
                ) : null}

                {ranking.candidates.length === 0 ? (
                  <div className="empty-state">
                    <p>No scored candidates to rank yet. Run scoring first.</p>
                  </div>
                ) : (
                  <ol className="ranking-list">
                    {ranking.candidates.map((candidate) => {
                      // Lead with what most moved this candidate's rank — by |impact|,
                      // not raw weight×score — so a heavy strike surfaces as readily
                      // as a strength. The score band's colour says which is which.
                      const topContributions = [...candidate.contributions]
                        .filter((c) => c.weight > 0)
                        .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))
                        .slice(0, 3);
                      return (
                        <li key={candidate.application_id}>
                          <div
                            className="ranking-row"
                            onClick={() => viewApplication(candidate.application_id)}
                          >
                            <span className="ranking-rank">#{candidate.rank}</span>
                            <div className="ranking-main">
                              <div className="ranking-name-row">
                                <span className="ranking-name">{candidate.name || "Unnamed applicant"}</span>
                                <span className={`fit-band band-${bandClass(candidate.band)}`}>
                                  {candidate.band}
                                </span>
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
            ) : selectedApp ? (() => {
              const flaggedFields = new Set(
                selectedApp.hardFilterReasons.flatMap((reason) => REASON_FIELDS[reason.code] ?? []),
              );
              return (
              <div className="app-detail">
                <div className="app-detail-actions no-print">
                  <button className="back-button" onClick={() => setSelectedApp(null)}>
                    <ChevronLeft size={16} />
                    <span>Back to list</span>
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => window.print()}
                  >
                    <Printer size={16} />
                    Print
                  </button>
                </div>
                <div className="app-detail-header">
                  <h3>{selectedApp.applicantName || selectedApp.primaryEmail}</h3>
                  <span className={`status-badge status-${selectedApp.status}`}>
                    {STATUS_LABELS[selectedApp.status]}
                  </span>
                  {selectedApp.statusSource !== "untouched" ? (
                    <span className={`source-badge source-${selectedApp.statusSource}`}>
                      {SOURCE_LABELS[selectedApp.statusSource]}
                    </span>
                  ) : null}
                </div>
                {selectedApp.coApplicantName ? (
                  <p className="co-applicant-line">Co-applicant: {selectedApp.coApplicantName}</p>
                ) : null}

                <div className="status-panel">
                  <p className="status-source-line">{SOURCE_DESCRIPTIONS[selectedApp.statusSource]}</p>
                  {selectedApp.stale ? (
                    <p className="stale-note">
                      New AI findings since this was last reviewed — you may want to look again.
                    </p>
                  ) : null}
                  {(() => {
                    // The toggle is source ownership: "Automatic" (machine-decided)
                    // vs. a human-pinned status. Automatic clears the override; the
                    // helper line shows the current automatic verdict.
                    const isHuman = selectedApp.statusSource === "human";
                    const autoLabel = STATUS_LABELS[selectedApp.autoStatus];
                    return (
                      <div className="status-decider">
                        <span className="status-decider-label">Decided by:</span>
                        <div className="segmented" role="group" aria-label="Status decided by">
                          <button
                            type="button"
                            className="segment"
                            aria-pressed={!isHuman}
                            disabled={!isHuman}
                            onClick={() => clearStatusOverride(selectedApp.id)}
                          >
                            Automatic
                          </button>
                          <button
                            type="button"
                            className="segment"
                            aria-pressed={isHuman && selectedApp.status === "eligible"}
                            disabled={isHuman && selectedApp.status === "eligible"}
                            onClick={() => overrideStatus(selectedApp.id, "eligible")}
                          >
                            Eligible
                          </button>
                          <button
                            type="button"
                            className="segment"
                            aria-pressed={isHuman && selectedApp.status === "ineligible"}
                            disabled={isHuman && selectedApp.status === "ineligible"}
                            onClick={() => overrideStatus(selectedApp.id, "ineligible")}
                          >
                            Ineligible
                          </button>
                        </div>
                        {isHuman ? (
                          <p className="status-decider-hint">
                            Reviewer override. Automatic would mark this {autoLabel.toLowerCase()}.
                          </p>
                        ) : null}
                      </div>
                    );
                  })()}
                </div>
                {selectedApp.hardFilterReasons.length > 0 ? (
                  <div className="filter-reasons">
                    <strong>Filter reasons:</strong>
                    <ul>
                      {selectedApp.hardFilterReasons.map((reason, i) => (
                        <li key={i}>{reason.message}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {selectedApp.qualityFlags && selectedApp.qualityFlags.length > 0 ? (
                  <div className="quality-flags">
                    <strong>AI quality flags</strong>
                    <p className="quality-flags-hint">
                      The AI raised these. Decide for yourself which matter — set the status above.
                    </p>
                    <ul>
                      {selectedApp.qualityFlags.map((flag, i) => (
                        <li key={i} className={`quality-flag quality-flag-${flag.severity}`}>
                          <span className="quality-flag-category">
                            {FLAG_CATEGORY_LABELS[flag.category] ?? flag.category}
                          </span>
                          <span className="quality-flag-summary">{flag.summary}</span>
                          {flag.evidence ? (
                            <span className="quality-flag-evidence">{flag.evidence}</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {selectedApp.dimensionScores && selectedApp.dimensionScores.length > 0 ? (
                  <div className="dimension-scores">
                    <h4>Fit dimensions</h4>
                    <p className="dimension-scores-hint">
                      Ordered by how much each dimension moved this candidate's ranking —
                      strengths and weaknesses together, most decisive first. Colour shows the
                      score: green strong, blue moderate, amber weak.
                    </p>
                    <ul>
                      {selectedApp.dimensionScores.map((s) => {
                        const sb = scoreBand(s.score);
                        return (
                          <li key={s.dimension_key} className="dimension-score">
                            <div className="dimension-score-head">
                              <span className="dimension-score-name">{s.name}</span>
                              <span className="dimension-score-bar" aria-hidden="true">
                                <span
                                  className={`dimension-score-fill ${sb.cls}`}
                                  style={{ width: `${Math.round(s.score * 100)}%` }}
                                />
                              </span>
                              <span className={`dimension-score-band ${sb.cls}`}>{sb.label}</span>
                              <span className="dimension-score-confidence">
                                {s.confidence} confidence
                              </span>
                            </div>
                            <p className="dimension-score-rationale">{s.rationale}</p>
                            {s.evidence ? (
                              <p className="dimension-score-evidence">{s.evidence}</p>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ) : null}
                {selectedApp.essays?.some((essay) => essay.answer) ? (
                  <div className="app-detail-essays">
                    <h4>Essay responses</h4>
                    {selectedApp.essays.map((essay) => (
                      <div key={essay.question} className="essay-block">
                        <h5>{essay.label}</h5>
                        {essay.answer ? (
                          <p>{essay.answer}</p>
                        ) : (
                          <p className="essay-empty">No response provided.</p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="app-detail-fields">
                  <h4>Applicant data</h4>
                  <dl>
                    {Object.entries(selectedApp.normalized).map(([key, value]) => {
                      const flagged = flaggedFields.has(key);
                      return (
                        <div key={key} className={flagged ? "field-flagged" : undefined}>
                          <dt>{fieldLabel(key)}</dt>
                          <dd>{formatFieldValue(value, key)}</dd>
                        </div>
                      );
                    })}
                  </dl>
                </div>
                {selectedApp.rawRow ? (
                  <details className="raw-row-section">
                    <summary>Raw source row</summary>
                    <pre>{JSON.stringify(selectedApp.rawRow, null, 2)}</pre>
                  </details>
                ) : null}
                {selectedApp.aiNarrative ? (
                  <details className="raw-row-section">
                    <summary>Raw AI narrative (quality flags)</summary>
                    <div className="ai-narrative">
                      <ReactMarkdown>{selectedApp.aiNarrative}</ReactMarkdown>
                    </div>
                  </details>
                ) : null}
                {selectedApp.essayAnalysis ? (
                  <details className="raw-row-section">
                    <summary>AI essay summary</summary>
                    <div className="essay-analysis">
                      <p className="essay-analysis-hint">
                        A neutral digest of what the applicant wrote. It describes what they said, not how good it is.
                      </p>
                      <p className="essay-analysis-summary">{selectedApp.essayAnalysis.summary}</p>
                      <dl className="essay-analysis-fields">
                        {renderEssayText("Household", selectedApp.essayAnalysis.household_context)}
                        {renderEssayText("Employment", selectedApp.essayAnalysis.employment_background)}
                        {renderEssayText("Prior co-op experience", selectedApp.essayAnalysis.prior_co_op_experience)}
                        {renderEssayChips("Skills offered", selectedApp.essayAnalysis.skills_offered)}
                        {renderEssayChips("Stated contributions", selectedApp.essayAnalysis.stated_contributions)}
                        {renderEssayChips("Motivations", selectedApp.essayAnalysis.stated_motivations)}
                        {renderEssayChips("Interests", selectedApp.essayAnalysis.interests)}
                        {renderEssayChips("Values", selectedApp.essayAnalysis.values)}
                      </dl>
                    </div>
                  </details>
                ) : null}
              </div>
              );
            })() : (
              <>
                <div className="app-controls">
                  {(() => {
                    // Each group toggles one axis of the filter, preserving the
                    // other, so Status and "Decided by" combine (AND).
                    const applyFilter = (next: typeof appFilter) => {
                      setAppFilter(next);
                      fetchApplications(next, 1, appSearch);
                    };
                    // Counts are faceted: each group reflects the OTHER group's
                    // active filter (plus search). "All"/"Any" sums the facet.
                    const statusFacet = appFacets?.status ?? dashboardCounts.status;
                    const sourceFacet = appFacets?.source ?? dashboardCounts.source;
                    const sum = (counts: Record<string, number>) =>
                      Object.values(counts).reduce((a, b) => a + b, 0);
                    const statusOptions = [
                      { label: "All", value: undefined, count: sum(statusFacet) },
                      { label: "Eligible", value: "eligible" as const, count: statusFacet.eligible },
                      { label: "Ineligible", value: "ineligible" as const, count: statusFacet.ineligible },
                    ];
                    const sourceOptions = [
                      { label: "Any", value: undefined, count: sum(sourceFacet) },
                      { label: "Rules", value: "rules" as const, count: sourceFacet.rules },
                      { label: "AI", value: "ai" as const, count: sourceFacet.ai },
                      { label: "Reviewer", value: "human" as const, count: sourceFacet.human },
                    ];
                    return (
                      <>
                        <div className="filter-group">
                          <span className="filter-group-label">Status</span>
                          <div className="app-tabs">
                            {statusOptions.map((opt) => (
                              <button
                                key={opt.label}
                                className={`tab-button ${appFilter.status === opt.value ? "active" : ""}`}
                                onClick={() => applyFilter({ ...appFilter, status: opt.value })}
                              >
                                {opt.label} ({opt.count})
                              </button>
                            ))}
                          </div>
                        </div>
                        <div className="filter-group">
                          <span className="filter-group-label">Decided by</span>
                          <div className="app-tabs">
                            {sourceOptions.map((opt) => (
                              <button
                                key={opt.label}
                                className={`tab-button ${
                                  appFilter.status_source === opt.value ? "active" : ""
                                }`}
                                onClick={() => applyFilter({ ...appFilter, status_source: opt.value })}
                              >
                                {opt.label} ({opt.count})
                              </button>
                            ))}
                          </div>
                        </div>
                      </>
                    );
                  })()}
                  <input
                    className="app-search"
                    type="search"
                    placeholder="Search by name or email"
                    value={appSearch}
                    onChange={(event) => {
                      setAppSearch(event.target.value);
                      fetchApplications(appFilter, 1, event.target.value);
                    }}
                  />
                </div>

                {applications.length === 0 ? (
                  <div className="empty-state">
                    <p>
                      {appFilter.status || appFilter.status_source
                        ? "No applications match this filter."
                        : "No applications imported yet."}
                    </p>
                  </div>
                ) : (
                  <>
                    <table className="app-table">
                      <thead>
                        <tr>
                          {(
                            [
                              { label: "Applicant", key: "applicant" },
                              { label: "Co-applicant", key: "co_applicant" },
                              { label: "Children", key: "children" },
                              { label: "Income", key: "income" },
                              { label: "Status", key: "status" },
                            ] as Array<{ label: string; key: SortKey }>
                          ).map((col) => (
                            <th key={col.key}>
                              <button
                                type="button"
                                className={`sort-header ${appSort?.key === col.key ? "active" : ""}`}
                                onClick={() => toggleSort(col.key)}
                              >
                                <span>{col.label}</span>
                                {appSort?.key === col.key ? (
                                  appSort.direction === "asc" ? (
                                    <ChevronUp size={14} />
                                  ) : (
                                    <ChevronDown size={14} />
                                  )
                                ) : null}
                              </button>
                            </th>
                          ))}
                          <th>Decided by</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {applications.map((app) => {
                          // Reason cell shows the machine's "why" for an exclusion: rules
                          // reasons, or AI flag categories. Human overrides show neither.
                          const reason =
                            app.statusSource === "rules"
                              ? app.hardFilterReasons.map((r) => r.message).join("; ")
                              : app.statusSource === "ai"
                                ? (app.flagCategories ?? []).map(flagCategoryLabel).join("; ")
                                : "—";
                          return (
                            <tr key={app.id} onClick={() => viewApplication(app.id)} className="clickable-row">
                              <td>{app.applicantName || app.primaryEmail}</td>
                              <td>{app.coApplicantName || "—"}</td>
                              <td>{app.childCount ?? "?"}</td>
                              <td>
                                {app.householdIncome != null ? `$${app.householdIncome.toLocaleString()}` : "?"}
                              </td>
                              <td>
                                <span className={`status-badge status-${app.status}`}>
                                  {STATUS_LABELS[app.status]}
                                </span>
                              </td>
                              <td>
                                {app.statusSource === "untouched" ? (
                                  "—"
                                ) : (
                                  <span className={`source-badge source-${app.statusSource}`}>
                                    {SOURCE_LABELS[app.statusSource]}
                                  </span>
                                )}
                                {app.stale ? (
                                  <span className="stale-badge" title="New AI findings since last review">
                                    stale
                                  </span>
                                ) : null}
                              </td>
                              <td className="reason-cell">{reason}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    <div className="pagination">
                      <div className="pagination-size">
                        <span>Rows:</span>
                        <select
                          value={appPageSize}
                          onChange={(event) => {
                            const newSize = Number(event.target.value);
                            fetchApplications(appFilter, 1, appSearch, newSize);
                          }}
                        >
                          <option value="10">10</option>
                          <option value="25">25</option>
                          <option value="50">50</option>
                          <option value="100">100</option>
                        </select>
                      </div>
                      <div className="pagination-pages">
                        <button disabled={appPage <= 1} onClick={() => fetchApplications(appFilter, 1, appSearch)}>
                          «
                        </button>
                        <button disabled={appPage <= 1} onClick={() => fetchApplications(appFilter, appPage - 1, appSearch)}>
                          ‹
                        </button>
                        <span>
                          Page {appPage} of {Math.ceil(appTotal / appPageSize) || 1}
                        </span>
                        <button
                          disabled={appPage >= Math.ceil(appTotal / appPageSize)}
                          onClick={() => fetchApplications(appFilter, appPage + 1, appSearch)}
                        >
                          ›
                        </button>
                        <button
                          disabled={appPage >= Math.ceil(appTotal / appPageSize)}
                          onClick={() => fetchApplications(appFilter, Math.ceil(appTotal / appPageSize), appSearch)}
                        >
                          »
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </>
            )}
          </section>
        </>
      )}
      {/* Bottom-right toast stack. Success toasts auto-dismiss; error toasts
          persist (with a copy button) until the user dismisses them. One
          mechanism for every workflow step. */}
      {toasts.length > 0 ? (
        <div className="toast-stack">
          {toasts.map((toast) => {
            const isError = toast.variant === "error";
            return (
              <div
                key={toast.id}
                className={`toast ${isError ? "toast-error" : "toast-success"}`}
                aria-live={isError ? "assertive" : "polite"}
                role={isError ? "alert" : "status"}
              >
                <div className="toast-message">{toast.message}</div>
                <div className="toast-actions">
                  {isError ? (
                    <button
                      className="toast-button"
                      aria-label="Copy error"
                      title="Copy error"
                      onClick={() => navigator.clipboard.writeText(toast.message)}
                    >
                      <Clipboard size={16} />
                    </button>
                  ) : null}
                  <button
                    className="toast-button"
                    aria-label="Dismiss notification"
                    title="Dismiss notification"
                    onClick={() => dismissToast(toast.id)}
                  >
                    <X size={16} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </main>
  );
}
