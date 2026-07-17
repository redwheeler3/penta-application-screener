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
from app.evals.agreement import score_agreement
from app.evals.case_store import (
    CaseValidationError,
    UnknownEvalError,
    list_cases,
    save_case,
)
from app.evals.fixture import FIXTURE_PATH, load
from app.evals.judge import DEFAULT_MODEL as JUDGE_MODEL
from app.evals.judge import PROMPT_VERSION as JUDGE_PROMPT_VERSION
from app.evals.judge import judge_case, load_cases, stability_run
from app.evals.live_scoring import load_golden, run_case
from app.evals.properties import INVARIANTS, SIGNALS, run_invariants, run_signals
from app.schemas.base import ResponseModel
from app.schemas.evals import (
    AgreementOut,
    CasesResponse,
    EvalCatalogResponse,
    EvalDescriptor,
    InvariantOut,
    InvariantsResponse,
    JudgeCaseOut,
    JudgeRunResponse,
    LiveScoringCaseOut,
    LiveScoringResponse,
    SaveCaseRequest,
    SignalOut,
    StabilityCaseOut,
    StabilityRunResponse,
)
from app.schemas.events import EvalSummaryEvent, ThinkingEvent, emit
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
    live_calls = sum(2 if c.judge else 1 for c in golden)  # score (+ judge if the case asks)
    n_judge = len(load_cases())
    return EvalCatalogResponse(evals=[
        EvalDescriptor(
            key="invariants", label="Invariants",
            description="Deterministic checks on the committed baseline fixture (poles "
            "present, no protected attributes) + review signals. Free, instant.",
            spends=False, estimated_calls=0,
        ),
        EvalDescriptor(
            key="live_scoring", label="Live scoring",
            description=f"Run {len(golden)} golden synthetic inputs through the REAL scoring "
            "prompt+model, then grade with assertions + the rubric judge.",
            spends=True, estimated_calls=live_calls,
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


@router.get("/invariants", response_model=InvariantsResponse)
def invariants(user: User = Depends(require_current_user)) -> InvariantsResponse:
    """Run the deterministic invariants + review signals over the committed fixture.
    Free (no model calls). Mirrors ``python -m app.evals.run``."""
    if not FIXTURE_PATH.exists():
        return InvariantsResponse(has_fixture=False, dimensions=0)
    fixture = load()
    by_check: dict[str, list[str]] = {}
    for v in run_invariants(fixture):
        by_check.setdefault(v.check, []).append(f"{v.subject}: {v.detail}")
    invariant_out = [
        InvariantOut(
            check=(name := check.__name__.removeprefix("check_")),
            passed=name not in by_check,
            violations=by_check.get(name, []),
        )
        for check in INVARIANTS
    ]
    sig_by: dict[str, list] = {}
    for s in run_signals(fixture):
        sig_by.setdefault(s.check, []).append(s)
    signal_out = [
        SignalOut(
            check=(name := sig.__name__.removeprefix("signal_")),
            notes=[s.note for s in sig_by.get(name, [])],
            has_concern=any(s.concern for s in sig_by.get(name, [])),
        )
        for sig in SIGNALS
    ]
    return InvariantsResponse(
        has_fixture=True, dimensions=len(fixture.dimensions),
        invariants=invariant_out, signals=signal_out,
    )


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
            results.append(judge_case(provider, c, model_id=JUDGE_MODEL))
            r = results[-1]
            on_delta(f"→ {r.report.verdict.value}: {r.report.reason}\n")
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
            if not rep.flipped:
                marker = "[stable]"
            elif c.contested:
                marker = "[contested-split]"
            else:
                marker = "[UNSTABLE]"
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
