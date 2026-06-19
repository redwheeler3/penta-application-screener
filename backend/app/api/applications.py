from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_current_user
from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    StatusSource,
    User,
)
from app.db.session import get_db
from app.domain.status import findings_fingerprint, is_stale
from app.services.application_import import extract_essays

router = APIRouter(prefix="/applications", tags=["applications"])

# Sort keys the client may request. Name and status are real columns; the rest
# live in the normalized JSON blob and are sorted in Python after fetching.
_COLUMN_SORTS = {
    "applicant": Application.applicant_name,
    "co_applicant": Application.co_applicant_name,
    "status": Application.status,
}
_NORMALIZED_SORTS = {
    "children": "child_count",
    "income": "household_income",
}


@router.get("")
def list_applications(
    status: str | None = Query(None, pattern="^(eligible|ineligible)$"),
    status_source: str | None = Query(None, pattern="^(untouched|rules|ai|human)$"),
    search: str | None = Query(None, max_length=200),
    sort: str | None = Query(None, pattern="^(applicant|co_applicant|children|income|status)$"),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Filters mirror the real columns. Named views (e.g. "needs review" =
    # status_source=ai) are composed by the client, not invented here.
    status_cond = (
        Application.status == ApplicationStatus(status) if status else None
    )
    source_cond = (
        Application.status_source == StatusSource(status_source) if status_source else None
    )
    search_cond = None
    if search:
        pattern = f"%{search}%"
        search_cond = (
            Application.applicant_name.ilike(pattern)
            | Application.co_applicant_name.ilike(pattern)
            | Application.primary_email.ilike(pattern)
        )

    def with_conds(*conds) -> Any:
        q = select(Application)
        for cond in conds:
            if cond is not None:
                q = q.where(cond)
        return q

    query = with_conds(status_cond, source_cond, search_cond)

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

    # Batch-fetch flags for just this page rather than per-row querying.
    flags_by_app = _latest_flags(db, [app.id for app in applications])

    # Faceted counts: each facet applies every active filter EXCEPT its own, so
    # the Status counts reflect the chosen Decided-by (and vice versa), plus
    # search. This keeps the two filter groups consistent with each other.
    status_facet = with_conds(source_cond, search_cond)
    source_facet = with_conds(status_cond, search_cond)
    facets = {
        "status": _facet_counts(db, status_facet, Application.status, ApplicationStatus),
        "source": _facet_counts(db, source_facet, Application.status_source, StatusSource),
    }

    return {
        "applications": [
            _serialize_summary(app, flags=flags_by_app.get(app.id)) for app in applications
        ],
        "total": total,
        "page": page,
        "pageSize": page_size,
        "facets": facets,
    }


def _facet_counts(db: Session, base_query, column, enum_cls) -> dict[str, int]:
    """Count rows per value of `column` within `base_query`, including zeros for
    enum values with no matches (so a filtered-out option shows "(0)")."""
    rows = db.execute(
        base_query.with_only_columns(column, func.count()).group_by(column)
    ).all()
    counts = {value: count for value, count in rows}
    # Keys may come back as the enum or its value depending on the driver.
    result = {}
    for member in enum_cls:
        result[member.value] = counts.get(member, counts.get(member.value, 0))
    return result


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
        "application": _serialize_detail(application, db, include_raw=user.role == "admin")
    }
    return result


class StatusOverride(BaseModel):
    status: ApplicationStatus


@router.patch("/{application_id}/status")
def override_status(
    application_id: int,
    body: StatusOverride,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Human override of an application's status.

    Sets status_source to human (sticky against future machine runs) and snapshots
    the current findings fingerprint, so later runs that change the findings mark
    the application stale. Machine reason/flag records are never altered.
    """
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    flags = _latest_flags(db, [application_id]).get(application_id)
    application.status = body.status
    application.status_source = StatusSource.HUMAN
    application.reviewed_fingerprint = findings_fingerprint(
        application.hard_filter_reasons, flags
    )
    db.commit()
    db.refresh(application)

    return {
        "application": _serialize_detail(application, db, include_raw=user.role == "admin")
    }


def _serialize_summary(
    app: Application, flags: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    normalized = app.normalized or {}
    return {
        "id": app.id,
        "primaryEmail": app.primary_email,
        "applicantName": app.applicant_name,
        "coApplicantName": app.co_applicant_name,
        "status": app.status.value,
        "statusSource": app.status_source.value,
        "stale": is_stale(app, flags),
        "hardFilterReasons": app.hard_filter_reasons,
        "childCount": normalized.get("child_count"),
        "householdIncome": normalized.get("household_income"),
        # null = quality-flag pass not run; int = flag count (0 = ran clean).
        "flagCount": None if flags is None else len(flags),
        # Distinct flag categories from the latest pass, for the list REASON cell.
        "flagCategories": None if flags is None else _distinct_categories(flags),
        "createdAt": app.created_at.isoformat() if app.created_at else None,
    }


def _distinct_categories(flags: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for flag in flags:
        category = flag.get("category")
        if category and category not in seen:
            seen.append(category)
    return seen


def _latest_flags(
    db: Session, application_ids: list[int] | None = None
) -> dict[int, list[dict[str, Any]]]:
    """Flags from each application's most recent quality-flag result.

    Returns {application_id: flag_list}. Applications with no quality-flag result
    are absent (their state is unknown / not-yet-run). Pass application_ids to
    scope the query to one page.
    """
    latest = _latest_quality_flag_results(db, application_ids)
    return {
        app_id: (result.output or {}).get("flags", [])
        for app_id, result in latest.items()
    }


def _latest_quality_flag_results(
    db: Session, application_ids: list[int] | None = None
) -> dict[int, ApplicationAIResult]:
    query = select(ApplicationAIResult).where(ApplicationAIResult.kind == "quality_flags")
    if application_ids is not None:
        if not application_ids:
            return {}
        query = query.where(ApplicationAIResult.application_id.in_(application_ids))

    # Most recent result per application wins (a re-run supersedes older rows).
    latest: dict[int, ApplicationAIResult] = {}
    for result in db.scalars(query.order_by(ApplicationAIResult.created_at)):
        latest[result.application_id] = result
    return latest


def _serialize_detail(
    app: Application, db: Session, include_raw: bool = False
) -> dict[str, Any]:
    ai_result = _latest_quality_flag_results(db, [app.id]).get(app.id)
    flags = (ai_result.output or {}).get("flags", []) if ai_result else None
    detail = _serialize_summary(app, flags=flags)
    detail["normalized"] = app.normalized
    detail["essays"] = extract_essays(app.raw_row or {})
    detail["qualityFlags"] = flags
    if include_raw:
        detail["rawRow"] = app.raw_row
        if ai_result is not None:
            detail["rawAiOutput"] = ai_result.output
    return detail
