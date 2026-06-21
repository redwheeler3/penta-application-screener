from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    ScreeningRun,
    StatusSource,
    User,
)
from app.db.session import get_db
from app.services.settings import get_app_settings

# Scope + cache-key helpers reused from the passes themselves, so "coverage"
# counts exactly what a re-run would (re)process — never a parallel definition
# that could drift from the real scope.
from app.ai.analysis import cache_key
from app.ai.dimension_scoring import applications_to_score, kind_for
from app.ai.essay_analysis import applications_to_analyze as essay_scope
from app.ai.quality_flags import applications_to_analyze as quality_scope
from app.services.screening_run import current_pattern_report, get_current_run

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def read_dashboard(
    _: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_app_settings(db)
    total = db.scalar(select(func.count()).select_from(Application)) or 0

    # Counts keyed by the real columns. Named views (e.g. "needs review" =
    # source 'ai') are composed and labeled by the client, not invented here.
    by_status = _count_by(db, Application.status)
    by_source = _count_by(db, Application.status_source)

    return {
        "settingsComplete": bool(settings.google_sheet_id),
        "counts": {
            "submitted": total,
            "status": {s.value: by_status.get(s, 0) for s in ApplicationStatus},
            "source": {s.value: by_source.get(s, 0) for s in StatusSource},
        },
        # Whether each screening step has run, derived from persisted data so the
        # ordered workflow gating survives a page reload. Sync is "done" once any
        # application exists; the AI steps once any result of their kind exists.
        "workflow": {
            "synced": total > 0,
            "qualityChecksRun": _kind_exists(db, "quality_flags"),
            "essaysAnalyzed": _kind_exists(db, "essay_analysis"),
            # Pattern discovery is a screening run, not a per-application result.
            "patternsDiscovered": _run_exists(db),
            # Scoring kinds are per-run ("dimension_scoring:<hash>"), so match by
            # prefix rather than an exact kind.
            "candidatesScored": _kind_prefix_exists(db, "dimension_scoring:"),
        },
        # Per-AI-step coverage of the CURRENT scope: {cached, inScope}. A step
        # whose results predate a re-sync goes stale (cached < inScope) even
        # though "it ran" — this is what lets the UI warn instead of showing a
        # misleading done-check. Counts match what a re-run would process,
        # because they reuse the passes' own scope + cache-key logic.
        "coverage": _coverage(db, settings),
    }


def _coverage(db: Session, settings) -> dict[str, dict[str, int]]:
    model = settings.ai.first_pass_model

    def covered(applications, kind: str) -> dict[str, int]:
        cached = sum(
            1
            for app in applications
            if db.scalar(
                select(ApplicationAIResult.id).where(
                    ApplicationAIResult.cache_key
                    == cache_key(application=app, kind=kind, model_id=model)
                )
            )
            is not None
        )
        return {"cached": cached, "inScope": len(applications)}

    result = {
        "qualityChecksRun": covered(quality_scope(db), "quality_flags"),
        "essaysAnalyzed": covered(essay_scope(db), "essay_analysis"),
    }
    # Scoring coverage is only meaningful against the current run's dimension set
    # (its kind embeds the dimensions hash). Absent a run, leave it unset.
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    if report is not None:
        result["candidatesScored"] = covered(applications_to_score(db), kind_for(report))
    return result


def _kind_exists(db: Session, kind: str) -> bool:
    return (
        db.scalar(
            select(ApplicationAIResult.id).where(ApplicationAIResult.kind == kind).limit(1)
        )
        is not None
    )


def _kind_prefix_exists(db: Session, prefix: str) -> bool:
    return (
        db.scalar(
            select(ApplicationAIResult.id)
            .where(ApplicationAIResult.kind.startswith(prefix))
            .limit(1)
        )
        is not None
    )


def _run_exists(db: Session) -> bool:
    return db.scalar(select(ScreeningRun.id).limit(1)) is not None


def _count_by(db: Session, column) -> dict:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {value: count for value, count in rows}
