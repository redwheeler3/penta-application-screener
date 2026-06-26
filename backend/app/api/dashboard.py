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
    SyncRun,
    User,
)
from app.db.session import get_db
from app.services.application_import import settings_fingerprint
from app.services.settings import get_app_settings

# Scope + cache-key helpers reused from the passes themselves, so "coverage" counts
# exactly what a re-run would process (never a parallel definition that could drift).
from app.ai.analysis import cache_key
from app.ai.dimension_scoring import (
    PROMPT_VERSION as SCORING_PROMPT_VERSION,
    applications_to_score,
    kind_for_dimension,
)
from app.ai.essay_analysis import PROMPT_VERSION as ESSAY_PROMPT_VERSION
from app.ai.essay_analysis import applications_to_analyze as essay_scope
from app.ai.quality_flags import PROMPT_VERSION as QUALITY_PROMPT_VERSION
from app.ai.quality_flags import applications_to_analyze as quality_scope
from app.services.screening_run import (
    current_pattern_report,
    get_current_run,
    ranking_is_current,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def read_dashboard(
    _: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_app_settings(db)
    total = db.scalar(select(func.count()).select_from(Application)) or 0

    # Counts keyed by the real columns; named views are composed client-side.
    by_status = _count_by(db, Application.status)
    by_source = _count_by(db, Application.status_source)

    return {
        "settingsComplete": bool(settings.google_sheet_id),
        "counts": {
            "submitted": total,
            "status": {s.value: by_status.get(s, 0) for s in ApplicationStatus},
            "source": {s.value: by_source.get(s, 0) for s in StatusSource},
        },
        # Whether each step has run, from persisted data so workflow gating survives
        # a reload. Sync is "done" once any application exists; the AI steps once any
        # result of their kind exists.
        "workflow": {
            "synced": total > 0,
            # Whether the latest import used the settings as they are now. Changed
            # import-relevant settings flag Import amber (a re-import would
            # reclassify eligibility). We can't detect a changed spreadsheet, so this
            # is "probably fresh," not a guarantee. Null fingerprint reads as current.
            "importCurrent": _import_is_current(db, settings),
            "qualityChecksRun": _kind_exists(db, "quality_flags"),
            "essaysAnalyzed": _kind_exists(db, "essay_analysis"),
            # Pattern discovery is a screening run, not a per-application result.
            "patternsDiscovered": _run_exists(db),
            # Scoring kinds are per-dimension, so match by prefix.
            "candidatesScored": _kind_prefix_exists(db, "dimension_scoring:"),
            # Same truth the Rank no-op gate uses, so the "needs re-run" badge and
            # the Rank button agree even when every candidate has a cached score.
            "rankingCurrent": ranking_is_current(db, get_current_run(db)),
        },
        # Per-AI-step coverage of the current scope: {cached, inScope}. A step whose
        # results predate a re-sync goes stale (cached < inScope) even though it ran,
        # so the UI warns instead of showing a misleading done-check.
        "coverage": _coverage(db, settings),
    }


def _import_is_current(db: Session, settings) -> bool:
    """True when the latest import's settings fingerprint matches the live one.
    Also true if there's no import yet or the sync predates fingerprinting (can't
    tell, so don't nag). False only when a stored fingerprint differs.
    """
    latest = db.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
    if latest is None or latest.settings_fingerprint is None:
        return True
    return latest.settings_fingerprint == settings_fingerprint(settings)


def _coverage(db: Session, settings) -> dict[str, dict[str, int]]:
    model = settings.ai.first_pass_model

    def covered(applications, kind: str, prompt_version: str) -> dict[str, int]:
        cached = sum(
            1
            for app in applications
            if db.scalar(
                select(ApplicationAIResult.id).where(
                    ApplicationAIResult.cache_key
                    == cache_key(
                        application=app, kind=kind, model_id=model,
                        prompt_version=prompt_version,
                    )
                )
            )
            is not None
        )
        return {"cached": cached, "inScope": len(applications)}

    result = {
        "qualityChecksRun": covered(
            quality_scope(db), "quality_flags", QUALITY_PROMPT_VERSION
        ),
        "essaysAnalyzed": covered(
            essay_scope(db), "essay_analysis", ESSAY_PROMPT_VERSION
        ),
    }
    # Scoring coverage is only meaningful against the current run. A candidate
    # counts as scored once it has a cached row for EVERY dimension key, so partial
    # coverage reads as not-yet-complete.
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    if report is not None:
        kinds = [kind_for_dimension(d.key) for d in report.dimensions]
        applications = applications_to_score(db)
        fully_scored = sum(
            1
            for app in applications
            if all(
                db.scalar(
                    select(ApplicationAIResult.id).where(
                        ApplicationAIResult.cache_key
                        == cache_key(
                            application=app, kind=kind, model_id=model,
                            prompt_version=SCORING_PROMPT_VERSION,
                        )
                    )
                )
                is not None
                for kind in kinds
            )
        )
        result["candidatesScored"] = {
            "cached": fully_scored,
            "inScope": len(applications),
        }
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
