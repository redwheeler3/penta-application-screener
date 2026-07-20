"""Free (no-model-call) eval endpoints: the catalog, invariants, re-baseline, and last-run
rehydration. These read committed fixtures + the DB; none spends. The streaming pass runs live
in ``runs``."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.api.evals._shared import (
    DEFAULT_STABILITY_K,
    current_prompt_version,
    live_case_keys,
)
from app.api.problems import Problem
from app.core.time import utc_isoformat
from app.db.models import EvalRun, User
from app.db.session import get_db
from app.evals.consolidate import load_cases as load_consolidation_cases
from app.evals.decompose import load_cases as load_decomposition_cases
from app.evals.fixture import FIXTURE_PATH, load, record
from app.evals.invariants import INVARIANT_DESCRIPTIONS, INVARIANTS, run_invariants
from app.evals.judge import load_cases
from app.evals.matching import load_cases as load_matching_cases
from app.evals.scoring import load_golden
from app.evals.screening import load_cases as load_screening_cases
from app.schemas.evals import (
    EvalCatalogResponse,
    EvalDescriptor,
    InvariantOut,
    InvariantsResponse,
    LastRun,
    LastRunResponse,
)

router = APIRouter()


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
    """Re-record the invariant baseline fixture from the CURRENT Rank. Writes the committed
    rank_baseline.json — a deliberate re-bless, committed to git afterward — then returns
    the invariants of the fresh fixture. Free (no model calls; reads the stored run).
    409 if there is no current Rank to record."""
    try:
        record(db)
    except RuntimeError as exc:
        raise Problem("run_required", detail=str(exc)) from exc
    return _invariants_response()


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
        keys_now = live_case_keys(key)
        merged: dict[str, dict] = {}
        for row in rows:
            if (row.prompt_version or "") != (newest.prompt_version or ""):
                break  # older prompt version — don't mix it into the accumulation
            for case in (row.result or {}).get("cases", []):
                if not (isinstance(case, dict) and "key" in case) or case["key"] in merged:
                    continue
                if keys_now is None or case["key"] in keys_now:
                    merged[case["key"]] = case  # newest-wins (rows iterate newest→oldest)
        if "cases" in result:
            result["cases"] = list(merged.values())
        current = current_prompt_version(newest.eval_key, db)
        runs.append(LastRun(
            eval_key=newest.eval_key,
            ran_at=utc_isoformat(newest.created_at),
            prompt_version=newest.prompt_version or "",
            current_prompt_version=current,
            stale=bool(current and newest.prompt_version and newest.prompt_version != current),
            result=result,
        ))
    return LastRunResponse(runs=runs)
