"""Case + judge-background editing endpoints. These read/write the committed golden fixtures
(the operator commits to git afterward); free, no model calls."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends

from app.api.dependencies import require_current_user
from app.api.problems import Problem
from app.db.models import User
from app.evals.case_store import (
    CaseValidationError,
    UnknownEvalError,
    get_background,
    list_cases,
    save_background,
    save_case,
)
from app.evals.judge import load_cases
from app.schemas.evals import (
    CasesResponse,
    JudgeBackground,
    JudgeBackgroundsResponse,
    SaveBackgroundRequest,
    SaveCaseRequest,
)

router = APIRouter()

# The passes the Judge tab audits, in pipeline order (matches JudgeCase.pass_name).
_JUDGE_PASSES = ("screening", "decomposition", "matching", "scoring", "consolidation")


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
