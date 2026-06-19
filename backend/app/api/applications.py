from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import Application, HardFilterStatus, User
from app.db.session import get_db
from app.services.application_import import extract_essays

router = APIRouter(prefix="/applications", tags=["applications"])

# Sort keys the client may request. Name and status are real columns; the rest
# live in the normalized JSON blob and are sorted in Python after fetching.
_COLUMN_SORTS = {
    "applicant": Application.applicant_name,
    "co_applicant": Application.co_applicant_name,
    "status": Application.hard_filter_status,
}
_NORMALIZED_SORTS = {
    "children": "child_count",
    "income": "household_income",
}


@router.get("")
def list_applications(
    status: str | None = Query(None, pattern="^(eligible|filtered_out)$"),
    search: str | None = Query(None, max_length=200),
    sort: str | None = Query(None, pattern="^(applicant|co_applicant|children|income|status)$"),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
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
    descending = direction == "desc"

    if sort in _NORMALIZED_SORTS:
        # The value lives in the JSON blob, so sort the full result set in Python
        # before paginating. Nulls always sort last regardless of direction.
        field = _NORMALIZED_SORTS[sort]
        rows = db.scalars(query.order_by(Application.id)).all()
        rows.sort(key=lambda app: _sort_key((app.normalized or {}).get(field), descending))
        offset = (page - 1) * page_size
        applications = rows[offset : offset + page_size]
    else:
        column = _COLUMN_SORTS.get(sort, Application.id)
        order = column.desc() if descending else column.asc()
        offset = (page - 1) * page_size
        applications = db.scalars(query.order_by(order).offset(offset).limit(page_size)).all()

    return {
        "applications": [_serialize_summary(app) for app in applications],
        "total": total,
        "page": page,
        "pageSize": page_size,
    }


def _sort_key(value: Any, descending: bool) -> tuple[int, Any]:
    """Sort missing values last in both directions; numbers compare naturally."""
    if value is None:
        return (1, 0)
    # Flip the value for descending so the null sentinel (group 1) stays last.
    if isinstance(value, (int, float)):
        return (0, -value if descending else value)
    return (0, value)


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
    detail["essays"] = extract_essays(app.raw_row or {})
    if include_raw:
        detail["rawRow"] = app.raw_row
    return detail
