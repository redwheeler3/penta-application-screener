"""The in-UI eval cockpit (the Evals tab).

Thin HTTP over the eval RUNNERS in ``app.evals.*`` — the endpoints call the same functions
the CLI scripts do (``run_case``, ``judge_case``, ``stability_run``, ``run_invariants``), so
the UI and terminal exercise identical logic. Nothing is reimplemented; this maps runner
dataclasses to the camelCase wire schemas, streams the model's reasoning, and persists each
run as an ``EvalRun`` row.

Dependency direction: evals → app, never app → evals. This module imports production
plumbing (the shared NDJSON event vocabulary, the provider); no production module imports
anything here. Evals are a consumer of the app, not part of its shipped runtime.

Streaming mirrors the Rank job exactly: a worker thread runs the (blocking) model calls and
pushes reasoning deltas onto a queue; the generator drains the queue into NDJSON
``thinking`` lines, then a terminal ``EvalSummaryEvent`` carries the structured result. A
per-case failure is recorded and the run continues (non-fatal), same as Rank's item errors.

Auth: the standard ``require_current_user`` (no role gate — see dependencies.py). The
spending runs sit behind the same gate a Rank does; the UI shows a spend-confirm from the
catalog's call estimates. Catalog + invariants are FREE (no model calls).
"""

from __future__ import annotations

import queue
import threading
from collections import Counter
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.api.problems import Problem
from app.db.models import EvalRun, User
from app.db.session import get_db
from app.evals import stability
from app.evals.agreement import score_agreement
from app.evals.capture_scores import propose_cases as _propose_scores
from app.evals.capture_screening import propose_cases as _propose_screening
from app.evals.case_store import (
    CaseValidationError,
    UnknownEvalError,
    list_cases,
    save_case,
)
from app.evals.fixture import FIXTURE_PATH, load, record
from app.evals.invariants import INVARIANT_DESCRIPTIONS, INVARIANTS, run_invariants
from app.evals.judge import DEFAULT_MODEL as JUDGE_MODEL
from app.evals.judge import PROMPT_VERSION as JUDGE_PROMPT_VERSION
from app.evals.judge import judge_case, load_cases, stability_run
from app.evals.live_consolidate import load_cases as load_consolidation_cases
from app.evals.live_consolidate import run_case as run_consolidation_case
from app.evals.live_consolidate import stability_run as consolidation_stability_run
from app.evals.live_decompose import load_cases as load_decomposition_cases
from app.evals.live_decompose import run_case as run_decomposition_case
from app.evals.live_decompose import stability_run as decomposition_stability_run
from app.evals.live_matching import load_cases as load_matching_cases
from app.evals.live_matching import run_case as run_matching_case
from app.evals.live_matching import stability_run as matching_stability_run
from app.evals.live_scoring import load_golden, run_case
from app.evals.live_scoring import stability_run as scoring_stability_run
from app.evals.synthetic_guard import NonSyntheticPoolError
from app.schemas.base import ResponseModel
from app.schemas.evals import (
    AgreementOut,
    CasesResponse,
    EvalCatalogResponse,
    EvalDescriptor,
    HarvestResponse,
    InvariantOut,
    InvariantsResponse,
    JudgeCaseOut,
    JudgeRunResponse,
    LastRun,
    LastRunResponse,
    LiveConsolidationCaseOut,
    LiveConsolidationResponse,
    LiveConsolidationStabilityCaseOut,
    LiveConsolidationStabilityResponse,
    LiveDecompositionCaseOut,
    LiveDecompositionResponse,
    LiveDecompositionStabilityCaseOut,
    LiveDecompositionStabilityResponse,
    LiveMatchingCaseOut,
    LiveMatchingResponse,
    LiveMatchingStabilityCaseOut,
    LiveMatchingStabilityResponse,
    LiveScoringCaseOut,
    LiveScoringResponse,
    LiveScoringStabilityCaseOut,
    LiveScoringStabilityResponse,
    SaveCaseRequest,
    StabilityCaseOut,
    StabilityRunResponse,
)
from app.schemas.events import EvalSummaryEvent, ThinkingEvent, emit
from app.services.ranking_run import get_current_run
from app.services.settings import get_app_settings

router = APIRouter(prefix="/evals", tags=["evals"])

# Default K for a stability run when the UI doesn't override it (K≥5 to trust a "stable"
# verdict, per the CLI habit), bounded so the default run's cost is predictable.
DEFAULT_STABILITY_K = 5


def _persist(db: Session, eval_key: str, prompt_version: str, result: ResponseModel, thinking: str) -> None:
    """Record one run as an EvalRun row. Best-effort — a persistence failure must not fail
    the run (the result already streamed to the user)."""
    try:
        db.add(EvalRun(
            eval_key=eval_key,
            prompt_version=prompt_version,
            result=result.model_dump(by_alias=True),
            thinking=thinking or None,
        ))
        db.commit()
    except Exception:  # telemetry write; never propagate
        db.rollback()


# --- free endpoints ---------------------------------------------------------


@router.get("/catalog", response_model=EvalCatalogResponse)
def catalog(user: User = Depends(require_current_user)) -> EvalCatalogResponse:
    """List the runnable evals + how many model calls each run costs (for the UI's
    spend-confirm). Free — computed from the committed fixtures, no model calls."""
    golden = load_golden()
    live_calls = len(golden) * 2  # every case: one score call + one judge call
    n_judge = len(load_cases())
    consolidation = load_consolidation_cases()
    # One confirm call per case + one judge call per case that carries a judge question.
    consolidation_calls = len(consolidation) + sum(1 for c in consolidation if c.judge)
    matching = load_matching_cases()
    matching_calls = len(matching) + sum(1 for c in matching if c.judge)
    decomposition = load_decomposition_cases()
    decomposition_calls = len(decomposition) + sum(1 for c in decomposition if c.judge)
    return EvalCatalogResponse(evals=[
        EvalDescriptor(
            key="invariants", label="Invariants",
            description="Deterministic checks on the committed baseline fixture (poles "
            "present, no protected attributes). Free, instant.",
            spends=False, estimated_calls=0,
        ),
        EvalDescriptor(
            key="live_scoring", label="Live scoring",
            description=f"Run {len(golden)} golden synthetic inputs through the REAL scoring "
            "prompt+model, then grade with assertions + the rubric judge.",
            spends=True, estimated_calls=live_calls,
        ),
        EvalDescriptor(
            key="live_scoring_stability", label="Live scoring — stability",
            description=f"Run the REAL scoring prompt K times (default K={DEFAULT_STABILITY_K}) per "
            "golden case on fixed input; flag when a case's assertion pass/fail wanders across runs.",
            spends=True, estimated_calls=len(golden) * DEFAULT_STABILITY_K,
        ),
        EvalDescriptor(
            key="live_consolidation", label="Live consolidation",
            description=f"Run {len(consolidation)} golden dimension pairs through the REAL "
            "consolidation prompt+model; grade merge/keep against the label (exact match). "
            "A case with a judge question also runs the judge as a label audit.",
            spends=True, estimated_calls=consolidation_calls,
        ),
        EvalDescriptor(
            key="live_consolidation_stability", label="Live consolidation — stability",
            description=f"Run the REAL consolidation prompt K times (default K={DEFAULT_STABILITY_K}) "
            f"per pair on fixed input to measure verdict stability. Costs K times a live run.",
            spends=True, estimated_calls=len(consolidation) * DEFAULT_STABILITY_K,
        ),
        EvalDescriptor(
            key="live_matching", label="Live matching",
            description=f"Run {len(matching)} golden prior/new dimension pairs through the REAL "
            "identity-match prompt+model; grade matches/mismatches against the label (exact match). "
            "A case with a judge question also runs the judge as a label audit.",
            spends=True, estimated_calls=matching_calls,
        ),
        EvalDescriptor(
            key="live_matching_stability", label="Live matching — stability",
            description=f"Run the REAL match prompt K times (default K={DEFAULT_STABILITY_K}) per "
            "pair on fixed input to measure verdict stability. Costs K times a live run.",
            spends=True, estimated_calls=len(matching) * DEFAULT_STABILITY_K,
        ),
        EvalDescriptor(
            key="live_decomposition", label="Live decomposition",
            description=f"Run {len(decomposition)} golden discovery-report sets through the REAL "
            "decomposition prompt+model; grade merge/keep (derived from the settled set) against "
            "the label (exact match). A case with a judge question also runs the judge as an audit.",
            spends=True, estimated_calls=decomposition_calls,
        ),
        EvalDescriptor(
            key="live_decomposition_stability", label="Live decomposition — stability",
            description=f"Run the REAL decompose prompt K times (default K={DEFAULT_STABILITY_K}) per "
            "set on fixed input to measure fold/keep stability. Costs K times a live run.",
            spends=True, estimated_calls=len(decomposition) * DEFAULT_STABILITY_K,
        ),
        EvalDescriptor(
            key="judge", label="Judge + agreement",
            description=f"Judge all {n_judge} labelled cases once and report judge-vs-human "
            "agreement (overall, kappa, per-step, failure recall).",
            spends=True, estimated_calls=n_judge,
        ),
        EvalDescriptor(
            key="stability", label="Stability",
            description=f"Judge each case K times on fixed inputs (default K={DEFAULT_STABILITY_K}) "
            "to measure verdict stability. Costs K times a judge run.",
            spends=True, estimated_calls=n_judge * DEFAULT_STABILITY_K,
        ),
    ])


def _invariants_response() -> InvariantsResponse:
    """Run the invariants over the committed fixture and shape the response. Shared by the
    GET and the re-baseline POST (which returns the invariants of the freshly-recorded
    fixture)."""
    if not FIXTURE_PATH.exists():
        return InvariantsResponse(has_fixture=False, dimensions=0)
    fixture = load()
    by_check: dict[str, list[str]] = {}
    for v in run_invariants(fixture):
        by_check.setdefault(v.check, []).append(f"{v.subject}: {v.detail}")
    invariant_out = [
        InvariantOut(
            check=(name := check.__name__.removeprefix("check_")),
            description=INVARIANT_DESCRIPTIONS.get(name, ""),
            passed=name not in by_check,
            violations=by_check.get(name, []),
        )
        for check in INVARIANTS
    ]
    return InvariantsResponse(
        has_fixture=True, dimensions=len(fixture.dimensions), invariants=invariant_out,
    )


@router.get("/invariants", response_model=InvariantsResponse)
def invariants(user: User = Depends(require_current_user)) -> InvariantsResponse:
    """Run the deterministic invariants over the committed fixture. Free (no model calls).
    (Judgement signals — overlap, carry-forward rate — live on the Insights tab over the
    live run, which shows them better; they aren't duplicated here.)"""
    return _invariants_response()


@router.post("/baseline", response_model=InvariantsResponse)
def rebaseline(
    user: User = Depends(require_current_user), db: Session = Depends(get_db)
) -> InvariantsResponse:
    """Re-record the invariant baseline fixture from the CURRENT Rank (the tab action that
    replaces the old `python -m app.evals.fixture` CLI). Writes the committed
    rank_baseline.json — a deliberate re-bless, committed to git afterward — then returns
    the invariants of the fresh fixture. Free (no model calls; reads the stored run).
    409 if there is no current Rank to record."""
    try:
        record(db)
    except RuntimeError as exc:
        raise Problem("run_required", detail=str(exc)) from exc
    return _invariants_response()


def _current_prompt_version(eval_key: str, db: Session) -> str:
    """The prompt version a fresh run of ``eval_key`` would exercise right now — so a
    rehydrated last run can be flagged stale when the prompt has since changed. Judge and
    stability share the judge prompt; live_scoring uses the scoring prompt."""
    if eval_key in ("live_scoring", "live_scoring_stability"):
        from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

        return SCORING_PROMPT_VERSION
    if eval_key in ("live_consolidation", "live_consolidation_stability"):
        from app.ai.dimension_consolidate import (
            PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
        )

        return CONSOLIDATE_PROMPT_VERSION
    if eval_key in ("live_matching", "live_matching_stability"):
        from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

        return MATCH_PROMPT_VERSION
    if eval_key in ("live_decomposition", "live_decomposition_stability"):
        from app.ai.dimension_decompose import (
            PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION,
        )

        return DECOMPOSE_PROMPT_VERSION
    if eval_key in ("judge", "stability"):
        return JUDGE_PROMPT_VERSION
    return ""


@router.get("/last-run", response_model=LastRunResponse)
def last_run(
    keys: str, user: User = Depends(require_current_user), db: Session = Depends(get_db)
) -> LastRunResponse:
    """The most recent persisted run for EACH of the comma-separated ``keys`` (a tab restores
    its last run(s) on remount — Live scoring passes ``live_scoring``; Judge passes
    ``judge,stability``; Live consolidation passes ``live_consolidation,live_consolidation_stability``).
    Returns one entry per key that has a run — so a tab running two evals restores BOTH, not
    just whichever ran last. Result JSON as the UI reads it, WITHOUT the thinking narration;
    each carries a ``stale`` flag when its prompt no longer matches the current one."""
    wanted = [k.strip() for k in keys.split(",") if k.strip()]
    runs: list[LastRun] = []
    for key in wanted:
        row = (
            db.query(EvalRun)
            .filter(EvalRun.eval_key == key)
            # id.desc() breaks a created_at tie (two runs in the same tick) — autoincrement
            # id is insertion order, so this is a stable "most recent".
            .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
            .first()
        )
        if row is None:
            continue
        current = _current_prompt_version(row.eval_key, db)
        runs.append(LastRun(
            eval_key=row.eval_key,
            ran_at=row.created_at.isoformat(),
            prompt_version=row.prompt_version or "",
            current_prompt_version=current,
            stale=bool(current and row.prompt_version and row.prompt_version != current),
            result=row.result,
        ))
    return LastRunResponse(runs=runs)


# --- cases (read the versioned dataset; edit through the UI to the JSON file) -


@router.get("/cases/{eval_key}", response_model=CasesResponse)
def get_cases(eval_key: str, user: User = Depends(require_current_user)) -> CasesResponse:
    """An eval's cases, straight from its committed fixture (free). 404 for an eval with
    no editable case set (invariants; stability reads the judge set)."""
    try:
        return CasesResponse(eval_key=eval_key, cases=list_cases(eval_key))
    except UnknownEvalError as exc:
        raise Problem("not_found", detail=f"No editable cases for eval {eval_key!r}.") from exc


@router.put("/cases/{eval_key}", response_model=CasesResponse)
def put_case(
    eval_key: str, body: SaveCaseRequest, user: User = Depends(require_current_user)
) -> CasesResponse:
    """Upsert one case (by key) into the eval's fixture FILE (the operator commits it to
    git deliberately). Validated server-side; a bad payload is refused (422)."""
    try:
        cases = save_case(eval_key, body.case)
    except UnknownEvalError as exc:
        raise Problem("not_found", detail=f"No editable cases for eval {eval_key!r}.") from exc
    except CaseValidationError as exc:
        raise Problem("invalid_case", detail=str(exc)) from exc
    return CasesResponse(eval_key=eval_key, cases=cases)


# --- harvest: propose judge cases from the CURRENT run (fidelity-preserving) --

# family -> the guard-gated proposer that turns the current run's cached output into
# unlabelled candidate judge cases. This is the sanctioned "copy an exact slice from a real
# run" path (opaque-indexed, synthetic-pool-gated) the hand-editor can't be: it pulls the
# real evidence the model saw. The operator labels each candidate in the editor before save.
_HARVESTERS = {"scoring": _propose_scores, "screening": _propose_screening}


@router.get("/harvest/{family}", response_model=HarvestResponse)
def harvest(family: str, user: User = Depends(require_current_user), db: Session = Depends(get_db)) -> HarvestResponse:
    """Propose unlabelled judge cases from the current run's scoring/screening output.
    Guard-gated: refuses a non-synthetic pool (committing applicant evidence quotes is only
    safe on synthetic data). 404 unknown family; 409 no current run; 422 non-synthetic pool.
    Candidates whose key already exists in the judge set are dropped (already harvested)."""
    if family not in _HARVESTERS:
        raise Problem("not_found", detail=f"No harvester for family {family!r} (scoring | screening).")
    run = get_current_run(db)
    if run is None:
        raise Problem("run_required", detail="No current Rank to harvest from — run a Rank first.")
    try:
        proposed = _HARVESTERS[family](db, run)
    except NonSyntheticPoolError as exc:
        raise Problem("invalid_case", detail=str(exc)) from exc
    existing = {c.get("key") for c in list_cases("judge")}
    fresh = [c for c in proposed if c.get("key") not in existing]
    return HarvestResponse(family=family, candidates=fresh)


# --- streaming runs ---------------------------------------------------------


def _stream(db: Session, eval_key: str, prompt_version: str, work) -> StreamingResponse:
    """Shared streaming scaffold (mirrors the Rank job): run ``work(on_delta)`` on a worker
    thread, drain its reasoning deltas to NDJSON ``thinking`` lines, then emit the terminal
    ``EvalSummaryEvent`` with the structured result, persisting the run to an EvalRun row.

    ``work`` receives ``on_delta`` (append a reasoning delta) and must return a
    ``ResponseModel``. Model calls block, so they run off-thread; a generator can't yield
    from the provider's ``on_delta`` callback, hence the queue. The request-scoped ``db``
    lives for the whole stream (as the Rank job's does), so persistence uses it directly."""
    def gen() -> Iterator[str]:
        q: queue.Queue[str | None] = queue.Queue()
        thinking_parts: list[str] = []
        outcome: dict[str, Any] = {}

        def on_delta(text: str) -> None:
            q.put(text)

        def do_work() -> None:
            try:
                outcome["result"] = work(on_delta)
            except Exception as exc:  # surfaced as a stream error below
                outcome["error"] = exc
            finally:
                q.put(None)

        worker = threading.Thread(target=do_work, daemon=True)
        worker.start()
        while True:
            item = q.get()
            if item is None:
                break
            thinking_parts.append(item)
            yield emit(ThinkingEvent(phase=eval_key, text=item))
        worker.join()

        if "error" in outcome:
            from app.schemas.events import ErrorEvent
            yield emit(ErrorEvent(phase=eval_key, message=f"{type(outcome['error']).__name__}: {outcome['error']}"))
            return
        result: ResponseModel = outcome["result"]
        _persist(db, eval_key, prompt_version, result, "".join(thinking_parts))
        yield emit(EvalSummaryEvent(eval=eval_key, result=result.model_dump(by_alias=True)))

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _select(items: list, case: str | None, key):
    """Filter a case list to a single ``case`` key when given (for a per-row run), or return
    all. 404 if the key is unknown — a stray key shouldn't silently run the whole set."""
    if case is None:
        return items
    picked = [it for it in items if key(it) == case]
    if not picked:
        raise Problem("not_found", detail=f"No case with key {case!r}.")
    return picked


@router.post("/live-scoring")
def run_live_scoring(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a live-scoring run: golden inputs → real scoring prompt+model → assertions +
    rubric judge. The scoring model's reasoning streams as ``thinking``. ``case`` runs just
    that one golden case (per-row run); omitted runs all."""
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

    settings = get_app_settings(db)
    scoring_model = settings.ai.dimension_scoring_model
    golden = _select(list(load_golden()), case, lambda c: c.key)

    def work(on_delta) -> LiveScoringResponse:
        results = []
        for c in golden:
            on_delta(f"\n\n### {c.key}\n")
            results.append(run_case(
                provider, c, scoring_model=scoring_model, judge_model=JUDGE_MODEL, on_delta=on_delta,
            ))
        return LiveScoringResponse(
            scoring_prompt_version=SCORING_PROMPT_VERSION,
            scoring_model=scoring_model,
            judge_model=JUDGE_MODEL,
            passed=sum(1 for r in results if r.passed),
            total=len(results),
            cases=[
                LiveScoringCaseOut(
                    key=r.case.key, passed=r.passed, score=r.score, confidence=r.confidence,
                    evidence=r.evidence, failures=r.failures,
                    judge_verdict=r.judge_verdict.value if r.judge_verdict else None,
                )
                for r in results
            ],
        )

    return _stream(db, "live_scoring", SCORING_PROMPT_VERSION, work)


@router.post("/live-scoring-stability")
def run_live_scoring_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a live-scoring STABILITY run: the REAL scoring prompt K times per golden case on
    fixed input, reporting whether each case's assertion pass/fail held (a flip = the score
    wandered across the assertion boundary). No judge — measures the production scoring prompt's
    own stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    scoring_model = settings.ai.dimension_scoring_model
    golden = _select(list(load_golden()), case, lambda c: c.key)

    def work(on_delta) -> LiveScoringStabilityResponse:
        out = []
        for c in golden:
            on_delta(f"\n\n### {c.key} (x{k})\n")
            res = scoring_stability_run(provider, c, scoring_model=scoring_model, k=k, on_delta=on_delta)
            lo, hi = res.score_spread
            out.append(LiveScoringStabilityCaseOut(
                key=c.key, marker=res.stability.marker, agreement=res.stability.agreement,
                flipped=res.stability.flipped, tally=res.stability.tally,
                score_min=lo, score_max=hi,
            ))
        return LiveScoringStabilityResponse(
            scoring_prompt_version=SCORING_PROMPT_VERSION, scoring_model=scoring_model, k=k, cases=out,
        )

    return _stream(db, "live_scoring_stability", SCORING_PROMPT_VERSION, work)


@router.post("/live-consolidation")
def run_live_consolidation(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a live-consolidation run: golden dimension pairs → the REAL consolidation
    confirm prompt+model → merge/keep graded against the label by exact match. ``case`` runs
    just that one pair (per-row run); omitted runs all. Contested cases are reported but
    excluded from passed/total. A case carrying a ``judge`` question ALSO runs the independent
    judge as a label audit (informational — never gates the pass/fail)."""
    from app.ai.dimension_consolidate import (
        PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
    )

    settings = get_app_settings(db)
    model = settings.ai.consolidate_model
    cases = _select(list(load_consolidation_cases()), case, lambda c: c.key)

    def work(on_delta) -> LiveConsolidationResponse:
        results = []
        for c in cases:
            on_delta(f"\n\n### {c.key}\n")
            results.append(run_consolidation_case(
                provider, c, consolidate_model=model, judge_model=JUDGE_MODEL, on_delta=on_delta,
            ))
        scored = [r for r in results if not r.case.contested]
        return LiveConsolidationResponse(
            prompt_version=CONSOLIDATE_PROMPT_VERSION,
            model=model,
            passed=sum(1 for r in scored if r.passed),
            total=len(scored),
            cases=[
                LiveConsolidationCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures, judge_verdict=r.judge_verdict,
                )
                for r in results
            ],
        )

    return _stream(db, "live_consolidation", CONSOLIDATE_PROMPT_VERSION, work)


@router.post("/live-consolidation-stability")
def run_live_consolidation_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a live-consolidation STABILITY run: the REAL confirm prompt K times per pair on
    fixed input, reporting verdict stability (flip = the production prompt is unstable). ``k``
    is clamped so a stray value can't blow up spend. ``case`` runs just that one pair."""
    from app.ai.dimension_consolidate import (
        PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
    )

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.consolidate_model
    cases = _select(list(load_consolidation_cases()), case, lambda c: c.key)

    def work(on_delta) -> LiveConsolidationStabilityResponse:
        out = []
        for c in cases:
            on_delta(f"\n\n### {c.key} (x{k})\n")
            rep = consolidation_stability_run(provider, c, consolidate_model=model, k=k, on_delta=on_delta)
            out.append(LiveConsolidationStabilityCaseOut(
                key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
                contested=c.contested, agreement=rep.agreement, flipped=rep.flipped,
                tally=rep.tally,
            ))
        return LiveConsolidationStabilityResponse(
            prompt_version=CONSOLIDATE_PROMPT_VERSION, model=model, k=k, cases=out,
        )

    return _stream(db, "live_consolidation_stability", CONSOLIDATE_PROMPT_VERSION, work)


@router.post("/live-matching")
def run_live_matching(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a live-matching run: golden prior/new dimension pairs → the REAL identity-match
    prompt+model → matches/mismatches graded against the label by exact match. ``case`` runs
    just that one pair. A case with a judge question also runs the judge as a label audit."""
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

    settings = get_app_settings(db)
    model = settings.ai.match_model
    cases = _select(list(load_matching_cases()), case, lambda c: c.key)

    def work(on_delta) -> LiveMatchingResponse:
        results = []
        for c in cases:
            on_delta(f"\n\n### {c.key}\n")
            results.append(run_matching_case(
                provider, c, match_model=model, judge_model=JUDGE_MODEL, on_delta=on_delta,
            ))
        scored = [r for r in results if not r.case.contested]
        return LiveMatchingResponse(
            prompt_version=MATCH_PROMPT_VERSION, model=model,
            passed=sum(1 for r in scored if r.passed), total=len(scored),
            cases=[
                LiveMatchingCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures, judge_verdict=r.judge_verdict,
                )
                for r in results
            ],
        )

    return _stream(db, "live_matching", MATCH_PROMPT_VERSION, work)


@router.post("/live-matching-stability")
def run_live_matching_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a live-matching STABILITY run: the REAL match prompt K times per pair on fixed
    input, reporting verdict stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.match_model
    cases = _select(list(load_matching_cases()), case, lambda c: c.key)

    def work(on_delta) -> LiveMatchingStabilityResponse:
        out = []
        for c in cases:
            on_delta(f"\n\n### {c.key} (x{k})\n")
            rep = matching_stability_run(provider, c, match_model=model, k=k, on_delta=on_delta)
            out.append(LiveMatchingStabilityCaseOut(
                key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
                contested=c.contested, agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
            ))
        return LiveMatchingStabilityResponse(prompt_version=MATCH_PROMPT_VERSION, model=model, k=k, cases=out)

    return _stream(db, "live_matching_stability", MATCH_PROMPT_VERSION, work)


@router.post("/live-decomposition")
def run_live_decomposition(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a live-decomposition run: golden discovery-report sets → the REAL decomposition
    prompt+model → merge/keep DERIVED from the settled set (all carvings in one axis = merge;
    spread across ≥2 = keep), graded against the label by exact match. ``case`` runs just that
    one set. A case with a judge question also runs the judge as a label audit."""
    from app.ai.dimension_decompose import PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION

    settings = get_app_settings(db)
    model = settings.ai.decompose_model
    cases = _select(list(load_decomposition_cases()), case, lambda c: c.key)

    def work(on_delta) -> LiveDecompositionResponse:
        results = []
        for c in cases:
            on_delta(f"\n\n### {c.key}\n")
            results.append(run_decomposition_case(
                provider, c, decompose_model=model, judge_model=JUDGE_MODEL, on_delta=on_delta,
            ))
        scored = [r for r in results if not r.case.contested]
        return LiveDecompositionResponse(
            prompt_version=DECOMPOSE_PROMPT_VERSION, model=model,
            passed=sum(1 for r in scored if r.passed), total=len(scored),
            cases=[
                LiveDecompositionCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures, judge_verdict=r.judge_verdict,
                )
                for r in results
            ],
        )

    return _stream(db, "live_decomposition", DECOMPOSE_PROMPT_VERSION, work)


@router.post("/live-decomposition-stability")
def run_live_decomposition_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a live-decomposition STABILITY run: the REAL decompose prompt K times per set on
    fixed input, reporting fold/keep stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_decompose import PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.decompose_model
    cases = _select(list(load_decomposition_cases()), case, lambda c: c.key)

    def work(on_delta) -> LiveDecompositionStabilityResponse:
        out = []
        for c in cases:
            on_delta(f"\n\n### {c.key} (x{k})\n")
            rep = decomposition_stability_run(provider, c, decompose_model=model, k=k, on_delta=on_delta)
            out.append(LiveDecompositionStabilityCaseOut(
                key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
                contested=c.contested, agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
            ))
        return LiveDecompositionStabilityResponse(prompt_version=DECOMPOSE_PROMPT_VERSION, model=model, k=k, cases=out)

    return _stream(db, "live_decomposition_stability", DECOMPOSE_PROMPT_VERSION, work)


@router.post("/judge")
def run_judge(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a judge run over all labelled cases, then compute judge-vs-human agreement.
    ``case`` runs just that one (per-row run); agreement needs ≥2 scored cases so a
    single-case run reports no agreement block, only the verdict."""
    cases = _select(list(load_cases()), case, lambda c: c.key)

    def work(on_delta) -> JudgeRunResponse:
        results = []
        for c in cases:
            on_delta(f"\n\n### [{c.pass_name}] {c.title}\n")
            on_delta(f"Judging on `{JUDGE_MODEL}` — _{c.task}_\n\n")
            results.append(judge_case(provider, c, model_id=JUDGE_MODEL))
            r = results[-1]
            on_delta(f"**{r.report.verdict.value}** — {r.report.reason}\n")
        case_out = [
            JudgeCaseOut(
                key=r.case.key, pass_name=r.case.pass_name, title=r.case.title,
                marker=r.marker, expected=r.case.expected.value, verdict=r.report.verdict.value,
                contested=r.case.contested, reason=r.report.reason,
            )
            for r in results
        ]
        scored = [r for r in results if not r.case.contested]
        agreement = None
        if len(scored) >= 2:
            rep = score_agreement(results)
            agreement = AgreementOut(
                n_scored=rep.n_scored, n_agree=rep.n_agree, n_contested=rep.n_contested,
                agreement=rep.agreement, kappa=rep.kappa,
                per_category={k: [v[0], v[1]] for k, v in rep.per_category.items()},
                failure_total=rep.failure_total, failure_caught=rep.failure_caught,
                failure_recall=rep.failure_recall, failure_precision=rep.failure_precision,
            )
        return JudgeRunResponse(
            judge_prompt_version=JUDGE_PROMPT_VERSION, judge_model=JUDGE_MODEL,
            cases=case_out, agreement=agreement,
        )

    return _stream(db, "judge", JUDGE_PROMPT_VERSION, work)


@router.post("/stability")
def run_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a stability run: judge each case K times on fixed inputs, report verdict
    stability. ``k`` is clamped to a sane range so a stray value can't blow up spend.
    ``case`` runs just that one (per-row stability check)."""
    k = max(2, min(k, 10))
    cases = _select(list(load_cases()), case, lambda c: c.key)

    def work(on_delta) -> StabilityRunResponse:
        out = []
        for c in cases:
            on_delta(f"\n\n### [{c.pass_name}] {c.title} (x{k})\n")
            rep = stability_run(provider, c, k=k, model_id=JUDGE_MODEL)
            tally = {v.value: n for v, n in Counter(rep.verdicts).most_common()}
            marker = stability.marker(rep.verdicts, contested=c.contested)
            on_delta(f"→ {marker} {rep.agreement:.0%}: {tally}\n")
            out.append(StabilityCaseOut(
                key=c.key, pass_name=c.pass_name, title=c.title, marker=marker,
                majority=rep.majority.value, seed=c.expected.value,
                agreement=rep.agreement, flipped=rep.flipped, tally=tally,
            ))
        return StabilityRunResponse(
            judge_prompt_version=JUDGE_PROMPT_VERSION, judge_model=JUDGE_MODEL, k=k, cases=out,
        )

    return _stream(db, "stability", JUDGE_PROMPT_VERSION, work)
