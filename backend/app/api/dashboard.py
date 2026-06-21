from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    StatusSource,
    User,
)
from app.db.session import get_db
from app.services.settings import get_app_settings

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
        },
    }


def _kind_exists(db: Session, kind: str) -> bool:
    return (
        db.scalar(
            select(ApplicationAIResult.id).where(ApplicationAIResult.kind == kind).limit(1)
        )
        is not None
    )


def _count_by(db: Session, column) -> dict:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {value: count for value, count in rows}
