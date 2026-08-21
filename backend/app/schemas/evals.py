"""Wire schemas for the in-UI eval cockpit (the Evals tab).

The eval RUNNERS live in ``app.evals.*`` and return plain dataclasses; these are the thin
camelCase response shapes the frontend reads. Kept separate from the runners so the CLI
path (``./judge.sh`` etc.) stays dependency-free of the API layer.

The catalog is FREE (no model calls) — it lists each eval and how many model calls a run
would cost, so the UI can show a spend-confirm before firing. Each run response carries the
prompt version(s) it exercised, so a result is always attributable to the exact prompt.
"""

from __future__ import annotations

from app.schemas.base import RequestModel, ResponseModel

# --- catalog (free) ---------------------------------------------------------


class EvalDescriptor(ResponseModel):
    """One runnable eval + its cost shape, for the catalog the UI lists."""

    key: str  # "scoring" | "judge" | "stability" | "invariants"
    label: str
    description: str
    spends: bool  # True if a run makes model calls (UI shows a spend-confirm)
    estimated_calls: int  # model calls one run makes (0 for invariants)


class EvalCatalogResponse(ResponseModel):
    evals: list[EvalDescriptor] = []


# --- shared stability shapes ------------------------------------------------


class StabilityRun(ResponseModel):
    """One of the K stability runs: its outcome token plus the model's own reasoning for it,
    so a flip is self-explaining (the whole point of capturing per-run detail — a mismatch's
    'why' otherwise lives nowhere). Shared by every live pass's stability response."""

    outcome: str  # the token this run produced (verdict / flag-set / pass|fail)
    detail: str = ""  # the model's reasoning for this run's outcome


# --- shared categorical shapes ----------------------------------------------
# Consolidation, matching, and decomposition are exact-match categorical passes with an
# identical result shape; screening shares the run/stability *headers* but has its own
# per-case fields. These bases hold the common fields so the four passes can't drift; each
# concrete class below adds only what's specific (its typed `cases`, or nothing).


class _CategoricalCaseOut(ResponseModel):
    """One exact-match categorical case: the model's ``verdict`` vs. the human ``expected``
    label, with ``contested`` (both directions defensible ⇒ passes either way) and any
    deterministic ``failures``. The verdict vocabulary is per-pass (see each subclass)."""

    key: str
    passed: bool
    verdict: str
    expected: str
    contested: bool
    reason: str
    failures: list[str] = []


class _CategoricalResponse(ResponseModel):
    """A categorical live run's header: the prompt identity it exercised plus pass/total
    (a contested case counts as passed by running, not by matching). Subclasses add ``cases``."""

    prompt_version: str
    model: str
    passed: int
    total: int


class _CategoricalStabilityCaseOut(ResponseModel):
    """One case across K stability runs: modal ``majority`` verdict, its ``agreement`` share,
    whether it ``flipped``, the full ``tally``, and per-run outcome+reasoning. ``marker`` is
    "[stable]" | "[UNSTABLE]" | "[contested-split]"."""

    key: str
    marker: str
    majority: str
    expected: str
    contested: bool
    agreement: float
    flipped: bool
    tally: dict[str, int]
    runs: list[StabilityRun] = []


class _CategoricalStabilityResponse(ResponseModel):
    """A categorical stability run's header (prompt identity + K). Subclasses add ``cases``."""

    prompt_version: str
    model: str
    k: int


# --- live scoring -----------------------------------------------------------


class ScoringCaseOut(ResponseModel):
    key: str
    passed: bool
    score: float
    confidence: str
    evidence: str
    failures: list[str] = []  # deterministic band/confidence breaches


class ScoringResponse(ResponseModel):
    scoring_prompt_version: str
    scoring_model: str
    passed: int
    total: int
    cases: list[ScoringCaseOut] = []


class ScoringStabilityCaseOut(ResponseModel):
    key: str
    marker: str  # "[stable]" | "[UNSTABLE]" (scoring cases are never contested)
    agreement: float  # modal pass/fail outcome's share of K
    flipped: bool  # the assertion pass/fail wandered across runs
    tally: dict[str, int]  # "pass"/"fail" -> count
    score_min: float  # score spread across the K runs — informational (model noise)
    score_max: float
    runs: list[StabilityRun] = []  # per-run outcome + the model's reasoning (explains a flip)


class ScoringStabilityResponse(ResponseModel):
    scoring_prompt_version: str
    scoring_model: str
    k: int
    cases: list[ScoringStabilityCaseOut] = []


# --- live consolidation (categorical: exact-match, no judge tier) ------------


class ConsolidationCaseOut(_CategoricalCaseOut):
    """``verdict`` is "merge" | "keep" — what the real confirm prompt produced."""


class ConsolidationResponse(_CategoricalResponse):
    cases: list[ConsolidationCaseOut] = []


class ConsolidationStabilityCaseOut(_CategoricalStabilityCaseOut):
    pass


class ConsolidationStabilityResponse(_CategoricalStabilityResponse):
    cases: list[ConsolidationStabilityCaseOut] = []


# --- live matching (categorical: exact-match, no judge tier) -----------------


class MatchingCaseOut(_CategoricalCaseOut):
    """``verdict`` is "matches" | "mismatches" — what the real match prompt produced;
    ``reason`` narrates the mapping the model returned."""


class MatchingResponse(_CategoricalResponse):
    cases: list[MatchingCaseOut] = []


class MatchingStabilityCaseOut(_CategoricalStabilityCaseOut):
    pass


class MatchingStabilityResponse(_CategoricalStabilityResponse):
    cases: list[MatchingStabilityCaseOut] = []


# --- live decomposition (categorical: exact-match, no judge tier) ------------


class DecompositionCaseOut(_CategoricalCaseOut):
    """``verdict`` is "merge" | "keep" — derived from the settled set; ``reason`` narrates
    how the source keys settled."""


class DecompositionResponse(_CategoricalResponse):
    cases: list[DecompositionCaseOut] = []


class DecompositionStabilityCaseOut(_CategoricalStabilityCaseOut):
    pass


class DecompositionStabilityResponse(_CategoricalStabilityResponse):
    cases: list[DecompositionStabilityCaseOut] = []


# --- live screening (per-category over a produced flag list) -----------------


class ScreeningCaseOut(ResponseModel):
    key: str
    passed: bool
    categories: list[str] = []  # the flag categories the model produced
    fires: list[str] = []  # categories that were expected to fire
    absent: list[str] = []  # categories guarded against (over-reach)
    contested: bool = False  # a miss here is expected/defensible → amber not red
    reason: str = ""  # the model's reasoning + per-flag evidence (explains a fire or a miss)
    failures: list[str] = []


class ScreeningResponse(_CategoricalResponse):
    cases: list[ScreeningCaseOut] = []


class ScreeningStabilityCaseOut(ResponseModel):
    key: str
    marker: str
    majority: str  # the modal flag-set token (e.g. "fake_contact" or "none")
    agreement: float
    flipped: bool
    tally: dict[str, int]  # flag-set token -> count
    runs: list[StabilityRun] = []  # per-run flag-set + the model's reasoning (explains a flip)


class ScreeningStabilityResponse(_CategoricalStabilityResponse):
    cases: list[ScreeningStabilityCaseOut] = []


# --- judge + agreement ------------------------------------------------------


class JudgeCaseOut(ResponseModel):
    key: str
    pass_name: str
    marker: str  # "[ok]" | "[review]" | "[contested]"
    human_label: str  # the human expected label (compact token)
    judge_label: str  # what the blind judge independently produced
    contested: bool
    detail: str  # the judge's reproduced output + reasoning
    label_rationale: str = ""  # why the human chose this label — context for a disagreement


class AgreementOut(ResponseModel):
    n_scored: int
    n_agree: int
    n_contested: int
    agreement: float
    kappa: float | None
    per_category: dict[str, list[int]]  # pass_name -> [agree, scored]
    failure_total: int
    failure_caught: int
    failure_recall: float | None
    failure_precision: float | None


class JudgeRunResponse(ResponseModel):
    judge_prompt_version: str
    judge_model: str
    cases: list[JudgeCaseOut] = []
    agreement: AgreementOut | None = None  # None when fewer than 2 scored cases


# --- stability --------------------------------------------------------------


class StabilityCaseOut(ResponseModel):
    key: str
    pass_name: str
    marker: str  # "[stable]" | "[UNSTABLE]" | "[contested-split]"
    majority: str  # modal judge label over K
    seed: str  # the case's human label/leaning
    agreement: float  # modal label's share of K
    flipped: bool
    tally: dict[str, int]  # judge label -> count
    runs: list[StabilityRun] = []  # per-run label + the judge's reasoning (explains a flip)


class StabilityRunResponse(ResponseModel):
    judge_prompt_version: str
    judge_model: str
    k: int
    cases: list[StabilityCaseOut] = []


# --- invariants (free) ------------------------------------------------------


class InvariantOut(ResponseModel):
    check: str
    description: str = ""  # plain-language "what this check verifies", shown under the heading
    passed: bool
    violations: list[str] = []  # "subject: detail" strings


class InvariantsResponse(ResponseModel):
    has_fixture: bool
    dimensions: int
    invariants: list[InvariantOut] = []


# --- cases (the versioned dataset, read/edited through the UI) --------------


class CasesResponse(ResponseModel):
    """An eval's cases, straight from its committed JSON fixture. Cases are free-form
    per family (a golden case has applicant/dimension/expect; a judge case has
    evidence/expected), so they pass through as raw dicts rather than a fixed model."""

    eval_key: str
    cases: list[dict] = []


class SaveCaseRequest(RequestModel):
    """Upsert one case (by its ``key``) into the eval's fixture. The full case object is
    passed as ``case`` — validated server-side for the family's required fields."""

    case: dict


# --- judge backgrounds (the editable per-pass brief the blind judge is given) ----


class JudgeBackground(ResponseModel):
    """One pass's editable ``judge_background`` — the plain-language brief ("what this pass
    does") the blind judge is shown, plus how many golden cases that pass contributes."""

    pass_name: str
    background: str
    case_count: int


class JudgeBackgroundsResponse(ResponseModel):
    """The per-pass backgrounds the Judge tab lists + edits (one per pass), in pipeline order."""

    backgrounds: list[JudgeBackground] = []


class SaveBackgroundRequest(RequestModel):
    """Write one pass's ``judge_background`` to its golden file."""

    background: str


# --- last run (rehydrate a tab on remount) ----------------------------------


class LastRun(ResponseModel):
    """The most recent persisted run for ONE eval key. Carries the result JSON (as the UI
    reads it) but NOT the ``thinking`` narration — the tab shows the outcome + per-case dots,
    not the replayed reasoning. Prompt and model drift are reported separately so a
    rehydrated result is never mistaken for one produced by the current configuration."""

    eval_key: str
    ran_at: str  # ISO-8601 timestamp of the run
    prompt_version: str = ""  # the prompt the run exercised
    current_prompt_version: str = ""  # the prompt in effect NOW
    model_id: str = ""  # the model the run exercised
    current_model_id: str = ""  # the model in effect NOW
    prompt_stale: bool = False
    model_stale: bool = False
    result: dict = {}


class LastRunResponse(ResponseModel):
    """The most recent persisted run for EACH of a tab's eval keys — so a tab that runs more
    than one eval (e.g. live consolidation + its stability) restores BOTH on remount, not just
    whichever ran last. One ``LastRun`` per key that has any persisted run; empty ⇒ nothing to
    restore."""

    runs: list[LastRun] = []


# --- run request ------------------------------------------------------------
# (Only stability takes a param; others run with server defaults.)
