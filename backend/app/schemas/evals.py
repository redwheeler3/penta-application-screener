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

    key: str  # "live_scoring" | "judge" | "stability" | "invariants"
    label: str
    description: str
    spends: bool  # True if a run makes model calls (UI shows a spend-confirm)
    estimated_calls: int  # model calls one run makes (0 for invariants)


class EvalCatalogResponse(ResponseModel):
    evals: list[EvalDescriptor] = []


# --- live scoring -----------------------------------------------------------


class LiveScoringCaseOut(ResponseModel):
    key: str
    passed: bool
    score: float
    confidence: str
    evidence: str
    failures: list[str] = []  # deterministic assertion breaches
    judge_verdict: str | None = None  # rubric judge, when the case asked for one


class LiveScoringResponse(ResponseModel):
    scoring_prompt_version: str
    scoring_model: str
    judge_model: str
    passed: int
    total: int
    cases: list[LiveScoringCaseOut] = []


# --- judge + agreement ------------------------------------------------------


class JudgeCaseOut(ResponseModel):
    key: str
    pass_name: str
    title: str
    marker: str  # "[ok]" | "[review]" | "[contested]"
    expected: str
    verdict: str
    contested: bool
    reason: str


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
    title: str
    marker: str  # "[stable]" | "[UNSTABLE]" | "[contested-split]"
    majority: str
    seed: str  # the case's label/leaning
    agreement: float  # modal verdict's share of K
    flipped: bool
    tally: dict[str, int]  # verdict value -> count


class StabilityRunResponse(ResponseModel):
    judge_prompt_version: str
    judge_model: str
    k: int
    cases: list[StabilityCaseOut] = []


# --- invariants (free) ------------------------------------------------------


class InvariantOut(ResponseModel):
    check: str
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


class HarvestResponse(ResponseModel):
    """Unlabelled candidate judge cases proposed from the CURRENT run's output (scoring or
    screening). Each is a full case dict with placeholder ``expected``/``label_rationale``
    the operator fills in the editor before saving — capture never labels. ``candidates``
    excludes cases whose key already exists in the judge set (already harvested)."""

    family: str  # "scoring" | "screening"
    candidates: list[dict] = []


# --- run request ------------------------------------------------------------
# (Only stability takes a param; others run with server defaults.)
