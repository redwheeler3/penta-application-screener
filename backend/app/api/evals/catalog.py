"""Free (no-model-call) eval endpoints: the catalog, invariants, re-baseline, and last-run
rehydration. These read committed fixtures + the DB; none spends. The streaming pass runs live
in ``runs``."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.model_catalog import supports_reasoning_effort
from app.api.dependencies import require_admin
from app.api.evals._shared import (
    DEFAULT_STABILITY_K,
    current_model,
    current_prompt_version,
    current_reasoning_effort,
    require_local_fixture_write,
    result_model,
    result_reasoning_effort,
)
from app.api.evals.history import latest_case_results
from app.core.config import get_settings
from app.core.problems import Problem
from app.core.time import utc_isoformat
from app.db.models import EvalRun, User
from app.db.session import get_db
from app.evals.dataset import case_identity, load_dataset
from app.evals.fixture import FIXTURE_PATH, load, record
from app.evals.invariants import INVARIANT_DESCRIPTIONS, INVARIANTS, run_invariants
from app.evals.paths import GOLDEN_FILES
from app.schemas.evals import (
    EvalCatalogResponse,
    EvalConfiguration,
    EvalDescriptor,
    InvariantOut,
    InvariantsResponse,
    LastRun,
    LastRunResponse,
)
from app.services.settings import get_app_settings

router = APIRouter()


@router.get("/catalog", response_model=EvalCatalogResponse)
def catalog(user: User = Depends(require_admin)) -> EvalCatalogResponse:
    """List the runnable evals + how many model calls each run costs (for the UI's
    spend-confirm). Free — computed from the committed fixtures, no model calls."""
    dataset = load_dataset()
    golden = dataset.families["scoring"]["cases"]
    scoring_calls = len(golden)  # one score call per case; the per-pass evals are judge-free
    n_judge = sum(len(data["cases"]) for data in dataset.families.values())
    consolidation = dataset.families["consolidation"]["cases"]
    consolidation_calls = len(consolidation)  # one confirm call per case
    matching = dataset.families["matching"]["cases"]
    matching_calls = len(matching)
    decomposition = dataset.families["decomposition"]["cases"]
    decomposition_calls = len(decomposition)
    n_screening = len(dataset.families["screening"]["cases"])  # one screening call per applicant
    return EvalCatalogResponse(fixture_editing_enabled=get_settings().eval_fixture_editing_enabled, evals=[
        EvalDescriptor(
            key="invariants", label="Invariants",
            description="Deterministic checks on the committed baseline fixture (poles "
            "present, no protected attributes). Free, instant.",
            spends=False, estimated_calls=0, repetitions=0,
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
            spends=True, estimated_calls=len(golden) * DEFAULT_STABILITY_K, repetitions=DEFAULT_STABILITY_K,
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
            spends=True, estimated_calls=len(consolidation) * DEFAULT_STABILITY_K, repetitions=DEFAULT_STABILITY_K,
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
            spends=True, estimated_calls=len(matching) * DEFAULT_STABILITY_K, repetitions=DEFAULT_STABILITY_K,
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
            spends=True, estimated_calls=len(decomposition) * DEFAULT_STABILITY_K, repetitions=DEFAULT_STABILITY_K,
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
            spends=True, estimated_calls=n_screening * DEFAULT_STABILITY_K, repetitions=DEFAULT_STABILITY_K,
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
            spends=True, estimated_calls=n_judge * DEFAULT_STABILITY_K, repetitions=DEFAULT_STABILITY_K,
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
def invariants(user: User = Depends(require_admin)) -> InvariantsResponse:
    """Run the deterministic invariants over the committed fixture. Free (no model calls).
    (Judgement signals — overlap, carry-forward rate — live on the Observability tab over the
    live run, which shows them better; they aren't duplicated here.)"""
    return _invariants_response()


@router.post("/baseline", response_model=InvariantsResponse)
def rebaseline(
    user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> InvariantsResponse:
    """Re-record the invariant baseline fixture from the CURRENT Rank. Writes the committed
    rank_baseline.json — a deliberate re-bless, committed to git afterward — then returns
    the invariants of the fresh fixture. Free (no model calls; reads the stored run).
    409 if there is no current Rank to record."""
    try:
        require_local_fixture_write(db, user.id)
        record(db)
    except RuntimeError as exc:
        raise Problem("run_required", detail=str(exc)) from exc
    return _invariants_response()


@router.get("/last-run", response_model=LastRunResponse)
def last_run(
    keys: str, user: User = Depends(require_admin), db: Session = Depends(get_db)
) -> LastRunResponse:
    """The most recent persisted run for EACH of the comma-separated ``keys`` (a tab restores
    its last run(s) on remount — Live scoring passes ``scoring``; Judge passes
    ``judge,stability``; Live consolidation passes ``consolidation,consolidation_stability``).
    Returns one entry per key that has a run — so a tab running two evals restores BOTH, not
    just whichever ran last. Result JSON as the UI reads it, WITHOUT the thinking narration;
    each identifies prompt/model drift so an old result is never presented as current."""
    wanted = list(dict.fromkeys(k.strip() for k in keys.split(",") if k.strip()))
    families = {"judge" if key in ("judge", "stability") else key.removesuffix("_stability") for key in wanted}
    if not families <= {*GOLDEN_FILES, "judge"}:
        raise Problem("invalid_settings", detail="Unknown eval mode.")
    dataset = load_dataset(families)
    settings = get_app_settings(db)
    current = {}
    newest_runs = []
    for key in wanted:
        family = "judge" if key in ("judge", "stability") else key.removesuffix("_stability")
        current[key] = EvalConfiguration(prompt_version=current_prompt_version(key, dataset),
            model_id=current_model(key, settings), reasoning_effort=current_reasoning_effort(key, settings),
            case_fingerprints=dataset.case_fingerprints(family))
        newest = (db.query(EvalRun.id, EvalRun.eval_key, EvalRun.created_at, EvalRun.prompt_version, EvalRun.result)
                  .filter(EvalRun.eval_key == key)
                  .order_by(EvalRun.created_at.desc(), EvalRun.id.desc()).first())
        if newest is not None:
            newest_runs.append(newest)
    runs: list[LastRun] = []
    for newest in newest_runs:
        key = newest.eval_key
        result = dict(newest.result or {})
        model = result_model(result)
        reasoning_effort = result_reasoning_effort(result)
        fingerprints = current[key].case_fingerprints
        case_run_ids = {}
        if "cases" in result:
            cases, case_run_ids = latest_case_results(db, key, newest.prompt_version or "", result, set(fingerprints))
            # Aggregate counts describe the reconstructed cases. Judge agreement belongs
            # to its original full run, so don't attach it to an accumulated partial set.
            def by_identity(items):
                return {case_identity(item["key"], item.get("passName", "")): item for item in items}
            if by_identity(cases) != by_identity(result["cases"]):
                result["agreement"] = None
            result["cases"] = cases
            if "total" in result:
                result["total"] = len(cases)
                result["passed"] = sum(bool(case.get("passed") or case.get("contested")) for case in cases)
        runs.append(LastRun(
            run_id=newest.id,
            eval_key=newest.eval_key,
            ran_at=utc_isoformat(newest.created_at),
            prompt_version=newest.prompt_version or "",
            model_id=model,
            supports_reasoning_effort=supports_reasoning_effort(model),
            reasoning_effort=reasoning_effort,
            case_run_ids=case_run_ids,
            result=result,
        ))
    return LastRunResponse(runs=runs, current=current)
