from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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
from app.domain.ranking import rank_candidates
from app.domain.status import findings_fingerprint, is_stale, resolve_machine_status
from app.services.application_import import extract_essays
from app.services.ranking_view import candidate_scores
from app.services.screening_run import (
    current_pattern_report,
    dimension_weights,
    get_current_run,
)

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
    _: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    result: dict[str, Any] = {
        "application": _serialize_detail(application, db)
    }
    return result


class StatusOverride(BaseModel):
    status: ApplicationStatus


@router.patch("/{application_id}/status")
def override_status(
    application_id: int,
    body: StatusOverride,
    _: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Human override of an application's status.

    Any committee member (not only admins) may set an application's status — the
    whole tool exists for members to make these judgments. Sets status_source to
    human (sticky against future machine runs) and snapshots the current findings
    fingerprint, so later runs that change the findings mark the application
    stale. Machine reason/flag records are never altered.
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
        "application": _serialize_detail(application, db)
    }


@router.delete("/{application_id}/status")
def clear_status_override(
    application_id: int,
    _: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Remove a human override, handing the decision back to the machine.

    Recomputes status from the *current* findings (rules then AI) and clears the
    human ownership, so future machine runs resume control. Because it reflects
    the latest findings rather than a stored pre-override value, the result can
    differ from what the status was before the human acted — which is the point
    of reverting to automatic. No-op (idempotent) if no human override is set.
    """
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    if application.status_source == StatusSource.HUMAN:
        flags = _latest_flags(db, [application_id]).get(application_id)
        status, source = resolve_machine_status(
            has_reasons=bool(application.hard_filter_reasons),
            has_ai_flags=bool(flags),
        )
        application.status = status
        application.status_source = source
        application.reviewed_fingerprint = None
        db.commit()
        db.refresh(application)

    return {
        "application": _serialize_detail(application, db)
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
    latest = _latest_results(db, "quality_flags", application_ids)
    return {
        app_id: (result.output or {}).get("flags", [])
        for app_id, result in latest.items()
    }


def _latest_results(
    db: Session, kind: str, application_ids: list[int] | None = None
) -> dict[int, ApplicationAIResult]:
    """Most recent AI result of ``kind`` per application (a re-run supersedes
    older rows). Returns {application_id: result}; applications with no result of
    that kind are absent. Pass application_ids to scope to one page.
    """
    query = select(ApplicationAIResult).where(ApplicationAIResult.kind == kind)
    if application_ids is not None:
        if not application_ids:
            return {}
        query = query.where(ApplicationAIResult.application_id.in_(application_ids))

    latest: dict[int, ApplicationAIResult] = {}
    for result in db.scalars(query.order_by(ApplicationAIResult.created_at)):
        latest[result.application_id] = result
    return latest


def _serialize_detail(app: Application, db: Session) -> dict[str, Any]:
    # The raw source row and AI narrative are shown to any committee member, not
    # only admins: members are trusted screeners, and these are just the source
    # and reasoning behind data the member already sees.
    flag_result = _latest_results(db, "quality_flags", [app.id]).get(app.id)
    flags = (flag_result.output or {}).get("flags", []) if flag_result else None
    detail = _serialize_summary(app, flags=flags)
    # What the machine would decide from the current findings, regardless of who
    # owns the status now. Lets the UI show the live automatic verdict — i.e. the
    # result of clearing a human override — without re-deriving the rules client-side.
    auto_status, auto_source = resolve_machine_status(
        has_reasons=bool(app.hard_filter_reasons), has_ai_flags=bool(flags)
    )
    detail["autoStatus"] = auto_status.value
    detail["autoStatusSource"] = auto_source.value
    detail["normalized"] = app.normalized
    detail["essays"] = extract_essays(app.raw_row or {})
    detail["qualityFlags"] = flags
    detail["rawRow"] = app.raw_row
    if flag_result is not None:
        detail["aiNarrative"] = flag_result.narrative

    # Essay analysis (milestone 6): informational, never affects status.
    # null = pass not yet run for this application. No raw narrative: unlike the
    # quality-flag pass, essay analysis no longer asks the model for a reasoning
    # preamble — an A/B run showed it doesn't change the extracted fields (see
    # SPEC "Essay Analysis"), so the structured output is the whole product.
    essay_result = _latest_results(db, "essay_analysis", [app.id]).get(app.id)
    detail["essayAnalysis"] = essay_result.output if essay_result else None

    # Dimension scoring (milestone 7): this candidate's scores against the
    # current run's discovered dimensions. null = no run, or not scored under it.
    # Scores are joined to their dimension labels so the UI shows names, not keys.
    detail["dimensionScores"] = _dimension_scores(db, app)
    return detail


def _dimension_scores(db: Session, app: Application) -> list[dict[str, Any]] | None:
    """The candidate's per-dimension scores under the current run, ordered by
    importance to THIS candidate's ranking.

    Returns None when there is no current run or the candidate has no scores for
    its dimension set (the scoring pass keys results on a per-run ``kind``, so a
    stale prior run's scores never leak into a new run's view).

    These are exactly the candidate's ranking ``contributions`` — the ranked-list
    row is the top slice of this same list — so the detail page and the row tell
    one story. Ordered by ``abs(impact)`` (``impact = weight · (score −
    pool_mean)``): the dimensions that most moved this candidate up or down come
    first, whether they helped or hurt. The score band's colour carries direction
    (strength vs. weakness); the order carries importance.

    Weight-0 (Ignored) dimensions are dropped: they contribute exactly 0 to fit
    and 0 impact, so they are irrelevant to the ranking — showing them would only
    clutter the page with axes the committee chose not to weigh.
    """
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    if report is None:
        return None

    weights = dimension_weights(run)
    ranked = rank_candidates(candidate_scores(db, report), weights)
    candidate = next((c for c in ranked if c.application_id == app.id), None)
    if candidate is None:
        return None

    contributions = sorted(
        (c for c in candidate.contributions if c.weight > 0),
        key=lambda c: abs(c.impact),
        reverse=True,
    )
    return [asdict(c) for c in contributions]
