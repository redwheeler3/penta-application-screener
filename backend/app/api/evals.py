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
from app.core.time import utc_isoformat
from app.db.models import EvalRun, User
from app.db.session import get_db
from app.evals import stability
from app.evals.agreement import score_agreement
from app.evals.capture_scores import propose_cases as _propose_scores
from app.evals.capture_screening import propose_cases as _propose_screening
from app.evals.case_store import (
    CaseValidationError,
    UnknownEvalError,
    get_background,
    list_cases,
    save_background,
    save_case,
)
from app.evals.consolidate import load_cases as load_consolidation_cases
from app.evals.consolidate import run_case as run_consolidation_case
from app.evals.consolidate import stability_run as consolidation_stability_run
from app.evals.decompose import load_cases as load_decomposition_cases
from app.evals.decompose import run_case as run_decomposition_case
from app.evals.decompose import stability_run as decomposition_stability_run
from app.evals.fixture import FIXTURE_PATH, load, record
from app.evals.invariants import INVARIANT_DESCRIPTIONS, INVARIANTS, run_invariants
from app.evals.judge import DEFAULT_MODEL as JUDGE_MODEL
from app.evals.judge import judge_case, load_cases, stability_run
from app.evals.judge import prompt_version as judge_prompt_version
from app.evals.matching import load_cases as load_matching_cases
from app.evals.matching import run_case as run_matching_case
from app.evals.matching import stability_run as matching_stability_run
from app.evals.scoring import load_golden, run_case
from app.evals.scoring import stability_run as scoring_stability_run
from app.evals.screening import fire_label as screening_fire_label
from app.evals.screening import load_cases as load_screening_cases
from app.evals.screening import run_case as run_screening_case
from app.evals.screening import stability_run as screening_stability_run
from app.evals.synthetic_guard import NonSyntheticPoolError
from app.schemas.base import ResponseModel
from app.schemas.evals import (
    AgreementOut,
    CasesResponse,
    ConsolidationCaseOut,
    ConsolidationResponse,
    ConsolidationStabilityCaseOut,
    ConsolidationStabilityResponse,
    DecompositionCaseOut,
    DecompositionResponse,
    DecompositionStabilityCaseOut,
    DecompositionStabilityResponse,
    EvalCatalogResponse,
    EvalDescriptor,
    HarvestResponse,
    InvariantOut,
    InvariantsResponse,
    JudgeBackground,
    JudgeBackgroundsResponse,
    JudgeCaseOut,
    JudgeRunResponse,
    LastRun,
    LastRunResponse,
    MatchingCaseOut,
    MatchingResponse,
    MatchingStabilityCaseOut,
    MatchingStabilityResponse,
    SaveBackgroundRequest,
    SaveCaseRequest,
    ScoringCaseOut,
    ScoringResponse,
    ScoringStabilityCaseOut,
    ScoringStabilityResponse,
    ScreeningCaseOut,
    ScreeningResponse,
    ScreeningStabilityCaseOut,
    ScreeningStabilityResponse,
    StabilityCaseOut,
    StabilityRun,
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


def _runs_out(report) -> list[StabilityRun]:
    """The per-run outcome+reasoning of a stability report, as wire shapes. Shared by every
    live pass so a flip carries the model's own 'why' for each of the K runs."""
    return [StabilityRun(outcome=r.outcome, detail=r.detail) for r in report.runs]


# --- free endpoints ---------------------------------------------------------


@router.get("/catalog", response_model=EvalCatalogResponse)
def catalog(user: User = Depends(require_current_user)) -> EvalCatalogResponse:
    """List the runnable evals + how many model calls each run costs (for the UI's
    spend-confirm). Free — computed from the committed fixtures, no model calls."""
    golden = load_golden()
    scoring_calls = len(golden)  # one score call per case; the per-pass evals are judge-free
    n_judge = len(load_cases())
    consolidation = load_consolidation_cases()
    consolidation_calls = len(consolidation)  # one confirm call per case
    matching = load_matching_cases()
    matching_calls = len(matching)
    decomposition = load_decomposition_cases()
    decomposition_calls = len(decomposition)
    n_screening = len(load_screening_cases())  # one screening call per applicant
    return EvalCatalogResponse(evals=[
        EvalDescriptor(
            key="invariants", label="Invariants",
            description="Deterministic checks on the committed baseline fixture (poles "
            "present, no protected attributes). Free, instant.",
            spends=False, estimated_calls=0,
        ),
        EvalDescriptor(
            key="scoring", label="Scoring",
            description=f"Run {len(golden)} golden synthetic inputs through the REAL scoring "
            "prompt+model; grade each produced score against its expected [min, max] band.",
            spends=True, estimated_calls=scoring_calls,
        ),
        EvalDescriptor(
            key="scoring_stability", label="Scoring — stability",
            description=f"Run the REAL scoring prompt K times (default K={DEFAULT_STABILITY_K}) per "
            "golden case on fixed input; flag when a case's pass/fail wanders across runs.",
            spends=True, estimated_calls=len(golden) * DEFAULT_STABILITY_K,
        ),
        EvalDescriptor(
            key="consolidation", label="Consolidation",
            description=f"Run {len(consolidation)} golden dimension pairs through the REAL "
            "consolidation prompt+model; grade merge/keep against the label (exact match).",
            spends=True, estimated_calls=consolidation_calls,
        ),
        EvalDescriptor(
            key="consolidation_stability", label="Consolidation — stability",
            description=f"Run the REAL consolidation prompt K times (default K={DEFAULT_STABILITY_K}) "
            f"per pair on fixed input to measure verdict stability. Costs K times a run.",
            spends=True, estimated_calls=len(consolidation) * DEFAULT_STABILITY_K,
        ),
        EvalDescriptor(
            key="matching", label="Matching",
            description=f"Run {len(matching)} golden prior/new dimension pairs through the REAL "
            "identity-match prompt+model; grade matches/mismatches against the label (exact match).",
            spends=True, estimated_calls=matching_calls,
        ),
        EvalDescriptor(
            key="matching_stability", label="Matching — stability",
            description=f"Run the REAL match prompt K times (default K={DEFAULT_STABILITY_K}) per "
            "pair on fixed input to measure verdict stability. Costs K times a run.",
            spends=True, estimated_calls=len(matching) * DEFAULT_STABILITY_K,
        ),
        EvalDescriptor(
            key="decomposition", label="Decomposition",
            description=f"Run {len(decomposition)} golden discovery-report sets through the REAL "
            "decomposition prompt+model; grade merge/keep (derived from the settled set) against "
            "the label (exact match).",
            spends=True, estimated_calls=decomposition_calls,
        ),
        EvalDescriptor(
            key="decomposition_stability", label="Decomposition — stability",
            description=f"Run the REAL decompose prompt K times (default K={DEFAULT_STABILITY_K}) per "
            "set on fixed input to measure fold/keep stability. Costs K times a run.",
            spends=True, estimated_calls=len(decomposition) * DEFAULT_STABILITY_K,
        ),
        EvalDescriptor(
            key="screening", label="Screening",
            description=f"Run {n_screening} golden synthetic applicants through the REAL screening "
            "prompt+model; grade the produced flags per-category (expected fires present, "
            "over-reach guards absent, clean applicants flag-free).",
            spends=True, estimated_calls=n_screening,
        ),
        EvalDescriptor(
            key="screening_stability", label="Screening — stability",
            description=f"Run the REAL screening prompt K times (default K={DEFAULT_STABILITY_K}) per "
            "applicant on fixed input to measure whether the flag set holds. Costs K times a run.",
            spends=True, estimated_calls=n_screening * DEFAULT_STABILITY_K,
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
    stability share the judge prompt; scoring uses the scoring prompt."""
    if eval_key in ("scoring", "scoring_stability"):
        from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

        return SCORING_PROMPT_VERSION
    if eval_key in ("consolidation", "consolidation_stability"):
        from app.ai.dimension_consolidate import (
            PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
        )

        return CONSOLIDATE_PROMPT_VERSION
    if eval_key in ("matching", "matching_stability"):
        from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

        return MATCH_PROMPT_VERSION
    if eval_key in ("decomposition", "decomposition_stability"):
        from app.ai.dimension_decompose import (
            PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION,
        )

        return DECOMPOSE_PROMPT_VERSION
    if eval_key in ("screening", "screening_stability"):
        from app.ai.screening import screening_prompt_version

        return screening_prompt_version(get_app_settings(db))
    if eval_key in ("judge", "stability"):
        return judge_prompt_version()
    return ""


def _live_case_keys(run_key: str) -> set[str] | None:
    """The case keys that CURRENTLY exist for a run key's pass, for filtering a merged
    historical last-run (so a renamed/removed case can't resurrect). ``run_key`` may be a live
    eval or its ``_stability`` sibling (same golden set), or judge/stability (the aggregated
    set). None ⇒ no editable case set for this key (don't filter)."""
    base = run_key.removesuffix("_stability")
    case_key = "judge" if base in ("judge", "stability") else base
    try:
        return {c["key"] for c in list_cases(case_key) if "key" in c}
    except UnknownEvalError:
        return None


@router.get("/last-run", response_model=LastRunResponse)
def last_run(
    keys: str, user: User = Depends(require_current_user), db: Session = Depends(get_db)
) -> LastRunResponse:
    """The most recent persisted run for EACH of the comma-separated ``keys`` (a tab restores
    its last run(s) on remount — Live scoring passes ``scoring``; Judge passes
    ``judge,stability``; Live consolidation passes ``consolidation,consolidation_stability``).
    Returns one entry per key that has a run — so a tab running two evals restores BOTH, not
    just whichever ran last. Result JSON as the UI reads it, WITHOUT the thinking narration;
    each carries a ``stale`` flag when its prompt no longer matches the current one."""
    wanted = [k.strip() for k in keys.split(",") if k.strip()]
    runs: list[LastRun] = []
    for key in wanted:
        # Recent rows newest-first. A per-case run persists a row holding only THAT case, so the
        # newest row alone would show just one case; we merge recent rows (newest-wins per case
        # key) to reconstruct the accumulated per-case view the tab showed before a refresh —
        # exactly matching the dots. Bounded to a small window; only rows sharing the newest
        # row's prompt version are merged, so a prompt change starts a fresh accumulation.
        rows = (
            db.query(EvalRun)
            .filter(EvalRun.eval_key == key)
            .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
            .limit(30)
            .all()
        )
        if not rows:
            continue
        newest = rows[0]
        result = dict(newest.result or {})
        # Only merge cases whose key still exists in the pass's current golden set, so a merged
        # historical run can't resurrect a since-renamed/removed case (which would inflate the
        # count past the dots). None ⇒ this key has no editable case set; keep all.
        live_keys = _live_case_keys(key)
        merged: dict[str, dict] = {}
        for row in rows:
            if (row.prompt_version or "") != (newest.prompt_version or ""):
                break  # older prompt version — don't mix it into the accumulation
            for case in (row.result or {}).get("cases", []):
                if not (isinstance(case, dict) and "key" in case) or case["key"] in merged:
                    continue
                if live_keys is None or case["key"] in live_keys:
                    merged[case["key"]] = case  # newest-wins (rows iterate newest→oldest)
        if "cases" in result:
            result["cases"] = list(merged.values())
        current = _current_prompt_version(newest.eval_key, db)
        runs.append(LastRun(
            eval_key=newest.eval_key,
            ran_at=utc_isoformat(newest.created_at),
            prompt_version=newest.prompt_version or "",
            current_prompt_version=current,
            stale=bool(current and newest.prompt_version and newest.prompt_version != current),
            result=result,
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


# --- judge backgrounds (the editable per-pass brief the blind judge is given) ----

# The passes the Judge tab audits, in pipeline order (matches JudgeCase.pass_name).
_JUDGE_PASSES = ("screening", "decomposition", "matching", "scoring", "consolidation")


@router.get("/judge-backgrounds", response_model=JudgeBackgroundsResponse)
def judge_backgrounds(user: User = Depends(require_current_user)) -> JudgeBackgroundsResponse:
    """The per-pass ``judge_background`` briefs the Judge tab lists + edits, with how many
    golden cases each pass contributes to the blind audit. Free (reads the committed files)."""
    counts = Counter(c.pass_name for c in load_cases())
    return JudgeBackgroundsResponse(backgrounds=[
        JudgeBackground(pass_name=p, background=get_background(p), case_count=counts.get(p, 0))
        for p in _JUDGE_PASSES
    ])


@router.put("/judge-backgrounds/{pass_name}", response_model=JudgeBackground)
def put_judge_background(
    pass_name: str, body: SaveBackgroundRequest, user: User = Depends(require_current_user)
) -> JudgeBackground:
    """Write one pass's ``judge_background`` to its golden file (operator commits to git). The
    edited brief is what the blind judge reads on the NEXT run, and it changes the judge's
    version hash (``judge.prompt_version`` folds in all five briefs), so a prior judge run
    rehydrates as stale until re-run — see judge.py."""
    try:
        saved = save_background(pass_name, body.background)
    except UnknownEvalError as exc:
        raise Problem("not_found", detail=f"No judge background for pass {pass_name!r}.") from exc
    except CaseValidationError as exc:
        raise Problem("invalid_case", detail=str(exc)) from exc
    counts = Counter(c.pass_name for c in load_cases())
    return JudgeBackground(pass_name=pass_name, background=saved, case_count=counts.get(pass_name, 0))


# --- harvest: propose judge cases from the CURRENT run (fidelity-preserving) --

# family -> the guard-gated proposer that turns the current run's cached output into
# unlabelled candidate judge cases. This is the sanctioned "copy an exact slice from a real
# run" path (opaque-indexed, synthetic-pool-gated) the hand-editor can't be: it pulls the
# real evidence the model saw. The operator labels each candidate in the editor before save.
_HARVESTERS = {"scoring": _propose_scores, "screening": _propose_screening}


@router.get("/harvest/{family}", response_model=HarvestResponse)
def harvest(family: str, user: User = Depends(require_current_user), db: Session = Depends(get_db)) -> HarvestResponse:
    """Propose unlabelled golden cases from the current run's scoring/screening output.
    Guard-gated: refuses a non-synthetic pool (committing applicant evidence quotes is only
    safe on synthetic data). 404 unknown family; 409 no current run; 422 non-synthetic pool.
    Candidates whose key already exists in that pass's golden set are dropped (already
    harvested). The operator labels + saves each candidate into the pass's golden file."""
    if family not in _HARVESTERS:
        raise Problem("not_found", detail=f"No harvester for family {family!r} (scoring | screening).")
    run = get_current_run(db)
    if run is None:
        raise Problem("run_required", detail="No current Rank to harvest from — run a Rank first.")
    try:
        proposed = _HARVESTERS[family](db, run)
    except NonSyntheticPoolError as exc:
        raise Problem("invalid_case", detail=str(exc)) from exc
    # Dedup against the pass's own golden set (scoring -> scoring, screening -> screening).
    existing = {c.get("key") for c in list_cases(f"live_{family}")}
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


def _case_workers(settings, *, fan_out: int = 1) -> int:
    """How many cases to run concurrently. Governed by the SAME ``settings.max_workers`` knob
    Rank already runs at (default 50) — the system's proven ceiling — so there's one concurrency
    dial, not a second. ``fan_out`` is the per-case inner concurrency: a STABILITY case fans out
    K model calls of its own, so we divide by K to keep TOTAL in-flight calls (cases × K) under
    the ceiling; a plain run (one call per case) passes fan_out=1 and gets the full width."""
    return max(1, settings.ai.max_workers // max(1, fan_out))


def _over_cases(cases: list, run_case_fn, *, on_delta, max_workers: int) -> list:
    """Run ``run_case_fn(case, case_on_delta)`` for each case CONCURRENTLY (bounded by
    ``max_workers`` — see ``_case_workers``), returning results in the ORIGINAL case order. Each
    case gets its own buffered ``case_on_delta``; a finished case's buffered narration is flushed
    to the real ``on_delta`` as ONE block, so cases never interleave in the thinking box even
    though they run in parallel (and only this thread ever writes the stream — the per-case fns
    write to their own buffers). For a stability case, within-case K-parallelism still applies
    inside ``run_case_fn`` (run_stability's own pool)."""
    from app.ai.analysis import run_in_pool

    def work(indexed):
        i, c = indexed
        buf: list[str] = []
        result = run_case_fn(c, buf.append)
        return i, result, buf

    slots: dict[int, tuple] = {}
    for _item, packed, err in run_in_pool(
        list(enumerate(cases)), call=work, max_workers=min(max_workers, len(cases) or 1)
    ):
        if err is not None:
            raise err
        i, result, buf = packed
        slots[i] = (result, buf)

    ordered = []
    for i in range(len(cases)):
        result, buf = slots[i]
        for line in buf:
            on_delta(line)  # flush this case's narration as one contiguous block, in case order
        ordered.append(result)
    return ordered


@router.post("/scoring")
def run_scoring(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a scoring run: golden inputs → real scoring prompt+model → deterministic
    band check (the produced score must fall in the expected [min, max], + confidence). The
    scoring model's reasoning streams as ``thinking``. ``case`` runs just that one golden case
    (per-row run); omitted runs all."""
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

    settings = get_app_settings(db)
    scoring_model = settings.ai.dimension_scoring_model
    golden = _select(list(load_golden()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_case(provider, c, scoring_model=scoring_model, on_delta=case_delta)

    def work(on_delta) -> ScoringResponse:
        results = _over_cases(golden, one, on_delta=on_delta, max_workers=_case_workers(settings))
        return ScoringResponse(
            scoring_prompt_version=SCORING_PROMPT_VERSION,
            scoring_model=scoring_model,
            passed=sum(1 for r in results if r.passed),
            total=len(results),
            cases=[
                ScoringCaseOut(
                    key=r.case.key, passed=r.passed, score=r.score, confidence=r.confidence,
                    evidence=r.evidence, failures=r.failures,
                )
                for r in results
            ],
        )

    return _stream(db, "scoring", SCORING_PROMPT_VERSION, work)


@router.post("/scoring-stability")
def run_scoring_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a scoring STABILITY run: the REAL scoring prompt K times per golden case on
    fixed input, reporting whether each case's assertion pass/fail held (a flip = the score
    wandered across the assertion boundary). No judge — measures the production scoring prompt's
    own stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    scoring_model = settings.ai.dimension_scoring_model
    golden = _select(list(load_golden()), case, lambda c: c.key)

    def one(c, case_delta) -> ScoringStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        res = scoring_stability_run(provider, c, scoring_model=scoring_model, k=k, on_delta=case_delta)
        lo, hi = res.score_spread
        return ScoringStabilityCaseOut(
            key=c.key, marker=res.stability.marker, agreement=res.stability.agreement,
            flipped=res.stability.flipped, tally=res.stability.tally,
            score_min=lo, score_max=hi, runs=_runs_out(res.stability),
        )

    def work(on_delta) -> ScoringStabilityResponse:
        out = _over_cases(golden, one, on_delta=on_delta, max_workers=_case_workers(settings, fan_out=k))
        return ScoringStabilityResponse(
            scoring_prompt_version=SCORING_PROMPT_VERSION, scoring_model=scoring_model, k=k, cases=out,
        )

    return _stream(db, "scoring_stability", SCORING_PROMPT_VERSION, work)


@router.post("/consolidation")
def run_consolidation(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a consolidation run: golden dimension pairs → the REAL consolidation
    confirm prompt+model → merge/keep graded against the label by exact match. ``case`` runs
    just that one pair (per-row run); omitted runs all. A contested case counts as passed
    whichever way it lands (both verdicts defensible) — it's a pass with special treatment, not
    excluded from the tally."""
    from app.ai.dimension_consolidate import (
        PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
    )

    settings = get_app_settings(db)
    model = settings.ai.consolidate_model
    cases = _select(list(load_consolidation_cases()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_consolidation_case(provider, c, consolidate_model=model, on_delta=case_delta)

    def work(on_delta) -> ConsolidationResponse:
        results = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings))
        return ConsolidationResponse(
            prompt_version=CONSOLIDATE_PROMPT_VERSION,
            model=model,
            passed=sum(1 for r in results if r.case.contested or r.passed),
            total=len(results),
            cases=[
                ConsolidationCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return _stream(db, "consolidation", CONSOLIDATE_PROMPT_VERSION, work)


@router.post("/consolidation-stability")
def run_consolidation_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a consolidation STABILITY run: the REAL confirm prompt K times per pair on
    fixed input, reporting verdict stability (flip = the production prompt is unstable). ``k``
    is clamped so a stray value can't blow up spend. ``case`` runs just that one pair."""
    from app.ai.dimension_consolidate import (
        PROMPT_VERSION as CONSOLIDATE_PROMPT_VERSION,
    )

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.consolidate_model
    cases = _select(list(load_consolidation_cases()), case, lambda c: c.key)

    def one(c, case_delta) -> ConsolidationStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        rep = consolidation_stability_run(provider, c, consolidate_model=model, k=k, on_delta=case_delta)
        return ConsolidationStabilityCaseOut(
            key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
            contested=c.contested, agreement=rep.agreement, flipped=rep.flipped,
            tally=rep.tally, runs=_runs_out(rep),
        )

    def work(on_delta) -> ConsolidationStabilityResponse:
        out = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings, fan_out=k))
        return ConsolidationStabilityResponse(
            prompt_version=CONSOLIDATE_PROMPT_VERSION, model=model, k=k, cases=out,
        )

    return _stream(db, "consolidation_stability", CONSOLIDATE_PROMPT_VERSION, work)


@router.post("/matching")
def run_matching(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a matching run: golden prior/new dimension pairs → the REAL identity-match
    prompt+model → matches/mismatches graded against the label by exact match. ``case`` runs
    just that one pair. A case with a judge question also runs the judge as a label audit."""
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

    settings = get_app_settings(db)
    model = settings.ai.match_model
    cases = _select(list(load_matching_cases()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_matching_case(provider, c, match_model=model, on_delta=case_delta)

    def work(on_delta) -> MatchingResponse:
        results = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings))
        return MatchingResponse(
            prompt_version=MATCH_PROMPT_VERSION, model=model,
            passed=sum(1 for r in results if r.case.contested or r.passed), total=len(results),
            cases=[
                MatchingCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return _stream(db, "matching", MATCH_PROMPT_VERSION, work)


@router.post("/matching-stability")
def run_matching_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a matching STABILITY run: the REAL match prompt K times per pair on fixed
    input, reporting verdict stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.match_model
    cases = _select(list(load_matching_cases()), case, lambda c: c.key)

    def one(c, case_delta) -> MatchingStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        rep = matching_stability_run(provider, c, match_model=model, k=k, on_delta=case_delta)
        return MatchingStabilityCaseOut(
            key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
            contested=c.contested, agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
            runs=_runs_out(rep),
        )

    def work(on_delta) -> MatchingStabilityResponse:
        out = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings, fan_out=k))
        return MatchingStabilityResponse(prompt_version=MATCH_PROMPT_VERSION, model=model, k=k, cases=out)

    return _stream(db, "matching_stability", MATCH_PROMPT_VERSION, work)


@router.post("/decomposition")
def run_decomposition(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a decomposition run: golden discovery-report sets → the REAL decomposition
    prompt+model → merge/keep DERIVED from the settled set (all carvings in one axis = merge;
    spread across ≥2 = keep), graded against the label by exact match. ``case`` runs just that
    one set. A case with a judge question also runs the judge as a label audit."""
    from app.ai.dimension_decompose import PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION

    settings = get_app_settings(db)
    model = settings.ai.decompose_model
    cases = _select(list(load_decomposition_cases()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_decomposition_case(provider, c, decompose_model=model, on_delta=case_delta)

    def work(on_delta) -> DecompositionResponse:
        results = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings))
        return DecompositionResponse(
            prompt_version=DECOMPOSE_PROMPT_VERSION, model=model,
            passed=sum(1 for r in results if r.case.contested or r.passed), total=len(results),
            cases=[
                DecompositionCaseOut(
                    key=r.case.key, passed=r.passed, verdict=r.verdict,
                    expected=r.case.expected, contested=r.case.contested,
                    reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return _stream(db, "decomposition", DECOMPOSE_PROMPT_VERSION, work)


@router.post("/decomposition-stability")
def run_decomposition_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a decomposition STABILITY run: the REAL decompose prompt K times per set on
    fixed input, reporting fold/keep stability. ``k`` clamped; ``case`` runs just that one."""
    from app.ai.dimension_decompose import PROMPT_VERSION as DECOMPOSE_PROMPT_VERSION

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.decompose_model
    cases = _select(list(load_decomposition_cases()), case, lambda c: c.key)

    def one(c, case_delta) -> DecompositionStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        rep = decomposition_stability_run(provider, c, decompose_model=model, k=k, on_delta=case_delta)
        return DecompositionStabilityCaseOut(
            key=c.key, marker=rep.marker, majority=rep.majority, expected=c.expected,
            contested=c.contested, agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
            runs=_runs_out(rep),
        )

    def work(on_delta) -> DecompositionStabilityResponse:
        out = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings, fan_out=k))
        return DecompositionStabilityResponse(prompt_version=DECOMPOSE_PROMPT_VERSION, model=model, k=k, cases=out)

    return _stream(db, "decomposition_stability", DECOMPOSE_PROMPT_VERSION, work)


@router.post("/screening")
def run_screening(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a screening run: golden synthetic applicants → the REAL screening
    prompt+model → the produced flag list graded per-category (expected fires present, guarded
    categories absent, clean applicants flag-free). ``case`` runs just that one applicant."""
    from app.ai.screening import screening_prompt_version

    settings = get_app_settings(db)
    model = settings.ai.screening_model
    version = screening_prompt_version(settings)
    cases = _select(list(load_screening_cases()), case, lambda c: c.key)

    def one(c, case_delta):
        case_delta(f"\n\n### {c.key}\n")
        return run_screening_case(provider, c, screening_model=model, settings=settings, on_delta=case_delta)

    def work(on_delta) -> ScreeningResponse:
        results = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings))
        return ScreeningResponse(
            prompt_version=version, model=model,
            passed=sum(1 for r in results if r.passed), total=len(results),
            cases=[
                ScreeningCaseOut(
                    key=r.case.key, passed=r.passed, categories=r.categories,
                    fires=[screening_fire_label(f) for f in r.case.fires],
                    absent=r.case.absent, reason=r.reason, failures=r.failures,
                )
                for r in results
            ],
        )

    return _stream(db, "screening", version, work)


@router.post("/screening-stability")
def run_screening_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a screening STABILITY run: the REAL screening prompt K times per applicant
    on fixed input, reporting whether the FLAG SET held. ``k`` clamped; ``case`` runs one."""
    from app.ai.screening import screening_prompt_version

    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    model = settings.ai.screening_model
    version = screening_prompt_version(settings)
    cases = _select(list(load_screening_cases()), case, lambda c: c.key)

    def one(c, case_delta) -> ScreeningStabilityCaseOut:
        case_delta(f"\n\n### {c.key} (x{k})\n")
        rep = screening_stability_run(provider, c, screening_model=model, settings=settings, k=k, on_delta=case_delta)
        return ScreeningStabilityCaseOut(
            key=c.key, marker=rep.marker, majority=rep.majority,
            agreement=rep.agreement, flipped=rep.flipped, tally=rep.tally,
            runs=_runs_out(rep),
        )

    def work(on_delta) -> ScreeningStabilityResponse:
        out = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings, fan_out=k))
        return ScreeningStabilityResponse(prompt_version=version, model=model, k=k, cases=out)

    return _stream(db, "screening_stability", version, work)


def _seed_str(expected: object) -> str:
    """A compact display token for a case's human label, for the stability ``seed`` field.
    Categorical labels are strings; scoring/screening labels are dicts (a band or fires/absent),
    which we render as a short key summary."""
    if isinstance(expected, str):
        return expected
    if isinstance(expected, dict):
        if "fires" in expected or "absent" in expected:
            parts = []
            if expected.get("fires"):
                parts.append("fires: " + ", ".join(expected["fires"]))
            if expected.get("absent"):
                parts.append("absent: " + ", ".join(expected["absent"]))
            return " · ".join(parts) or "clean"
        lo, hi = expected.get("score_min", "-1"), expected.get("score_max", "1")
        conf = f" {expected['confidence']}" if "confidence" in expected else ""
        return f"[{lo}, {hi}]{conf}"
    return str(expected)


@router.post("/judge")
def run_judge(
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a blind label-audit run over every pass's golden cases, then compute
    judge-vs-human agreement. Each case is reproduced by an INDEPENDENT model (blind to the
    label) and graded against the human label — see judge.py. ``case`` runs just that one
    (per-row run); agreement needs ≥2 scored cases, so a single-case run reports no agreement
    block, only the verdict."""
    settings = get_app_settings(db)
    cases = _select(list(load_cases()), case, lambda c: c.key)
    pv = judge_prompt_version()  # snapshot the briefs' hash for this run

    def one(c, case_delta):
        case_delta(f"\n\n### [{c.pass_name}] {c.key}\n")
        case_delta(f"Reproducing blind on `{JUDGE_MODEL}`…\n\n")
        r = judge_case(provider, c, model_id=JUDGE_MODEL)
        rp = r.reproduced
        agree = "agrees with" if rp.agrees else "DISAGREES with"
        case_delta(f"**judge: {rp.judge_label}** — {agree} label ({rp.human_label}). {rp.detail}\n")
        return r

    def work(on_delta) -> JudgeRunResponse:
        results = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings))
        case_out = [
            JudgeCaseOut(
                key=r.case.key, pass_name=r.case.pass_name, marker=r.marker,
                human_label=r.reproduced.human_label, judge_label=r.reproduced.judge_label,
                contested=r.case.contested, detail=r.reproduced.detail,
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
            judge_prompt_version=pv, judge_model=JUDGE_MODEL,
            cases=case_out, agreement=agreement,
        )

    return _stream(db, "judge", pv, work)


@router.post("/stability")
def run_stability(
    k: int = DEFAULT_STABILITY_K,
    case: str | None = None,
    user: User = Depends(require_current_user),
    provider: AIProvider = Depends(get_ai_provider),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream a stability run: blind-audit each case K times on fixed inputs, report whether the
    judge's verdict held. ``k`` is clamped to a sane range so a stray value can't blow up spend.
    ``case`` runs just that one (per-row stability check)."""
    k = max(2, min(k, 10))
    settings = get_app_settings(db)
    cases = _select(list(load_cases()), case, lambda c: c.key)
    pv = judge_prompt_version()  # snapshot the briefs' hash for this run

    def one(c, case_delta) -> StabilityCaseOut:
        case_delta(f"\n\n### [{c.pass_name}] {c.key} (x{k})\n")
        rep = stability_run(provider, c, k=k, model_id=JUDGE_MODEL)
        tally = dict(Counter(rep.labels).most_common())
        marker = stability.marker(rep.labels, contested=c.contested)
        case_delta(f"→ {marker} {rep.agreement:.0%}: {tally}\n")
        return StabilityCaseOut(
            key=c.key, pass_name=c.pass_name, marker=marker,
            majority=rep.majority, seed=_seed_str(c.expected),
            agreement=rep.agreement, flipped=rep.flipped, tally=tally,
        )

    def work(on_delta) -> StabilityRunResponse:
        out = _over_cases(cases, one, on_delta=on_delta, max_workers=_case_workers(settings, fan_out=k))
        return StabilityRunResponse(
            judge_prompt_version=pv, judge_model=JUDGE_MODEL, k=k, cases=out,
        )

    return _stream(db, "stability", pv, work)
