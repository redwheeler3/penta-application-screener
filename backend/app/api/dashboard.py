from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import Application, ApplicationStatus, StatusSource, User
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
    }


def _count_by(db: Session, column) -> dict:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {value: count for value, count in rows}
