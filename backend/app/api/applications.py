from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import Application, HardFilterStatus, User
from app.db.session import get_db

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("")
def list_applications(
    status: str | None = Query(None, pattern="^(eligible|filtered_out)$"),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(Application)

    if status:
        query = query.where(Application.hard_filter_status == HardFilterStatus(status))

    if search:
        pattern = f"%{search}%"
        query = query.where(
            Application.applicant_name.ilike(pattern)
            | Application.co_applicant_name.ilike(pattern)
            | Application.primary_email.ilike(pattern)
        )

    total_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(total_query) or 0

    offset = (page - 1) * page_size
    applications = db.scalars(
        query.order_by(Application.id).offset(offset).limit(page_size)
    ).all()

    return {
        "applications": [_serialize_summary(app) for app in applications],
        "total": total,
        "page": page,
        "pageSize": page_size,
    }


@router.get("/{application_id}")
def get_application(
    application_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    result: dict[str, Any] = {
        "application": _serialize_detail(application, include_raw=user.role == "admin")
    }
    return result


def _serialize_summary(app: Application) -> dict[str, Any]:
    normalized = app.normalized or {}
    return {
        "id": app.id,
        "primaryEmail": app.primary_email,
        "applicantName": app.applicant_name,
        "coApplicantName": app.co_applicant_name,
        "hardFilterStatus": app.hard_filter_status.value,
        "hardFilterReasons": app.hard_filter_reasons,
        "childCount": normalized.get("child_count"),
        "householdIncome": normalized.get("household_income"),
        "createdAt": app.created_at.isoformat() if app.created_at else None,
    }


def _serialize_detail(app: Application, include_raw: bool = False) -> dict[str, Any]:
    detail = _serialize_summary(app)
    detail["normalized"] = app.normalized
    if include_raw:
        detail["rawRow"] = app.raw_row
    return detail
