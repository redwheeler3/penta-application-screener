from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.dimension_scoring import kind_for_dimension
from app.api.dependencies import require_current_user
from app.api.problems import Problem
from app.core.time import utc_isoformat
from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationNote,
    ApplicationStatus,
    StatusSource,
    User,
)
from app.db.session import get_db
from app.domain.ranking import rank_candidates
from app.domain.status import findings_fingerprint, is_stale, resolve_machine_status
from app.schemas.applications import (
    AIResultTraceOut,
    ApplicationDetail,
    ApplicationEnvelope,
    ApplicationListResponse,
    ApplicationSummary,
    DimensionContributionOut,
    DimensionScoringTraceOut,
    Facets,
    PrivateNoteUpdate,
    ScreeningFlagOut,
)
from app.services.application_import import extract_essays
from app.services.ranking_run import (
    current_dimension_report,
    dimension_weights,
    get_current_run,
    stored_tiers,
)
from app.services.ranking_view import candidate_scores

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


@router.get("", response_model=ApplicationListResponse)
def list_applications(
    status: str | None = Query(None, pattern="^(eligible|ineligible)$"),
    status_source: str | None = Query(
        None, alias="statusSource", pattern="^(untouched|rules|ai|human)$"
    ),
    search: str | None = Query(None, max_length=200),
    sort: str | None = Query(None, pattern="^(applicant|co_applicant|children|income|status)$"),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, alias="pageSize", ge=1, le=100),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationListResponse:
    # Filters mirror the real columns; named views are composed client-side.
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

    # Faceted counts: each facet applies every active filter except its own, so the
    # two filter groups stay consistent with each other.
    status_facet = with_conds(source_cond, search_cond)
    source_facet = with_conds(status_cond, search_cond)
    facets = {
        "status": _facet_counts(db, status_facet, Application.status, ApplicationStatus),
        "source": _facet_counts(db, source_facet, Application.status_source, StatusSource),
    }

    return ApplicationListResponse(
        applications=[
            _serialize_summary(app, flags=flags_by_app.get(app.id)) for app in applications
        ],
        total=total,
        page=page,
        page_size=page_size,
        facets=Facets(status=facets["status"], source=facets["source"]),
    )


def _facet_counts(db: Session, base_query, column, enum_cls) -> dict[str, int]:
    """Count rows per value of `column` within `base_query`, including zeros for
    enum values with no matches (so a filtered-out option shows "(0)")."""
    rows = db.execute(
        base_query.with_only_columns(column, func.count()).group_by(column)
    ).all()
    counts = dict(rows)
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


@router.get("/{application_id}", response_model=ApplicationEnvelope)
def get_application(
    application_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    application = db.get(Application, application_id)
    if application is None:
        raise Problem("not_found", detail="Application not found.")

    return ApplicationEnvelope(application=_serialize_detail(application, db, user))


class StatusOverride(BaseModel):
    status: ApplicationStatus


@router.patch("/{application_id}/status", response_model=ApplicationEnvelope)
def override_status(
    application_id: int,
    body: StatusOverride,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Human override of an application's status.

    Any committee member may set status. Sets status_source to human (sticky against
    future machine runs) and snapshots the current findings fingerprint, so later
    runs that change the findings mark it stale. Machine records are never altered.
    """
    application = db.get(Application, application_id)
    if application is None:
        raise Problem("not_found", detail="Application not found.")

    flags = _latest_flags(db, [application_id]).get(application_id)
    application.status = body.status
    application.status_source = StatusSource.HUMAN
    application.reviewed_fingerprint = findings_fingerprint(
        application.hard_filter_reasons, flags
    )
    db.commit()
    db.refresh(application)

    return ApplicationEnvelope(application=_serialize_detail(application, db, user))


@router.delete("/{application_id}/status", response_model=ApplicationEnvelope)
def clear_status_override(
    application_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Remove a human override, handing the decision back to the machine.

    Recomputes status from the *current* findings (rules then AI), so the result can
    differ from the pre-override value — which is the point of reverting to
    automatic. No-op if no human override is set.
    """
    application = db.get(Application, application_id)
    if application is None:
        raise Problem("not_found", detail="Application not found.")

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

    return ApplicationEnvelope(application=_serialize_detail(application, db, user))


@router.put("/{application_id}/note", response_model=ApplicationEnvelope)
def save_private_note(
    application_id: int,
    body: PrivateNoteUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ApplicationEnvelope:
    """Create or replace the current member's private application note."""
    application = db.get(Application, application_id)
    if application is None:
        raise Problem("not_found", detail="Application not found.")

    note = db.scalar(
        select(ApplicationNote).where(
            ApplicationNote.application_id == application_id,
            ApplicationNote.user_id == user.id,
        )
    )
    if note is None:
        note = ApplicationNote(application_id=application_id, user_id=user.id, note=body.note)
        db.add(note)
    else:
        note.note = body.note
    db.commit()

    return ApplicationEnvelope(application=_serialize_detail(application, db, user))


def _serialize_summary(
    app: Application, flags: list[dict[str, Any]] | None = None
) -> ApplicationSummary:
    normalized = app.normalized or {}
    return ApplicationSummary(
        id=app.id,
        primary_email=app.primary_email,
        applicant_name=app.applicant_name,
        co_applicant_name=app.co_applicant_name,
        status=app.status.value,
        status_source=app.status_source.value,
        stale=is_stale(app, flags),
        hard_filter_reasons=app.hard_filter_reasons,
        child_count=normalized.get("child_count"),
        household_income=normalized.get("household_income"),
        # null = screening pass not run; int = flag count (0 = ran clean).
        flag_count=None if flags is None else len(flags),
        # Distinct flag categories from the latest pass, for the list REASON cell.
        flag_categories=None if flags is None else _distinct_categories(flags),
        created_at=utc_isoformat(app.created_at),
    )


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
    """Flags from each application's most recent screening result, as
    {application_id: flag_list}. Applications with no result are absent. Pass
    application_ids to scope the query to one page.
    """
    latest = _latest_results(db, "screening", application_ids)
    return {
        app_id: (result.output or {}).get("flags", [])
        for app_id, result in latest.items()
    }


def _latest_results(
    db: Session, kind: str, application_ids: list[int] | None = None
) -> dict[int, ApplicationAIResult]:
    """Most recent AI result of ``kind`` per application, as {application_id:
    result}. Applications with no result of that kind are absent. Pass
    application_ids to scope to one page.
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


def _serialize_detail(app: Application, db: Session, user: User) -> ApplicationDetail:
    # The raw source row and AI narrative are shown to any committee member: they're
    # trusted screeners, and these just back the data the member already sees.
    flag_result = _latest_results(db, "screening", [app.id]).get(app.id)
    flags = (flag_result.output or {}).get("flags", []) if flag_result else None
    summary = _serialize_summary(app, flags=flags)
    # What the machine would decide from the current findings, whoever owns status
    # now — lets the UI show the live automatic verdict (the result of clearing an
    # override) without re-deriving the rules client-side.
    auto_status, auto_source = resolve_machine_status(
        has_reasons=bool(app.hard_filter_reasons), has_ai_flags=bool(flags)
    )

    dimension_scores = _dimension_scores(db, app)
    return ApplicationDetail(
        **summary.model_dump(),
        auto_status=auto_status.value,
        auto_status_source=auto_source.value,
        normalized=app.normalized,
        essays=extract_essays(app.raw_row or {}),
        flags=(
            [ScreeningFlagOut(**f) for f in flags] if flags is not None else None
        ),
        raw_row=app.raw_row,
        ai_narrative=flag_result.narrative if flag_result is not None else None,
        screening_trace=_result_trace(flag_result),
        # This candidate's scores against the current run's dimensions, joined to
        # their labels. null = no run, or not scored under it.
        dimension_scores=dimension_scores,
        dimension_scoring_trace=_dimension_scoring_trace(db, app.id),
        private_note=_private_note(db, app.id, user.id),
    )


def _private_note(db: Session, application_id: int, user_id: int) -> str:
    note = db.scalar(
        select(ApplicationNote.note).where(
            ApplicationNote.application_id == application_id,
            ApplicationNote.user_id == user_id,
        )
    )
    return note or ""


def _result_trace(result: ApplicationAIResult | None) -> AIResultTraceOut | None:
    if result is None:
        return None
    return AIResultTraceOut(
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
    )


def _dimension_scoring_trace(
    db: Session, application_id: int
) -> DimensionScoringTraceOut | None:
    run = get_current_run(db)
    report = current_dimension_report(run) if run is not None else None
    if report is None:
        return None
    kinds = {kind_for_dimension(dimension.key) for dimension in report.dimensions}
    latest: dict[str, ApplicationAIResult] = {}
    for result in db.scalars(
        select(ApplicationAIResult)
        .where(
            ApplicationAIResult.application_id == application_id,
            ApplicationAIResult.kind.in_(kinds),
        )
        .order_by(ApplicationAIResult.created_at)
    ):
        latest[result.kind] = result
    results = list(latest.values())
    if not results:
        return None
    return DimensionScoringTraceOut(
        dimension_count=len(results),
        model_ids=sorted({result.model_id for result in results}),
        prompt_versions=sorted({result.prompt_version for result in results}),
        input_tokens=sum(result.input_tokens for result in results),
        output_tokens=sum(result.output_tokens for result in results),
        cost_usd=round(sum(result.cost_usd for result in results), 6),
    )


def _dimension_scores(
    db: Session, app: Application
) -> list[DimensionContributionOut] | None:
    """The candidate's per-dimension scores under the current run, ordered by
    importance to THIS candidate's ranking.

    Returns None when there is no run or the candidate has no scores for its
    dimension set. These are the candidate's ranking ``contributions`` (the
    ranked-list row is the top slice of this list), ordered by ``abs(impact)``
    (``impact = weight · (score − pool_mean)``) so the dimensions that most moved
    this candidate come first. Weight-0 (Ignored) dimensions are dropped — they
    contribute nothing to the ranking.
    """
    run = get_current_run(db)
    report = current_dimension_report(run) if run is not None else None
    if report is None:
        return None

    # An all-Ignore board intentionally falls back to uniform weights so the ranked
    # list has a stable opening order. It is not a committee weighting decision,
    # though, so applicant details should not present every raw score as relevant.
    tiers = stored_tiers(run)
    if not any(tier.get("dimension_keys") for tier in tiers):
        return []

    weights = dimension_weights(run)
    ranked = rank_candidates(candidate_scores(db, run), weights)
    candidate = next((c for c in ranked if c.application_id == app.id), None)
    if candidate is None:
        return None

    contributions = sorted(
        (c for c in candidate.contributions if c.weight > 0),
        key=lambda c: abs(c.impact),
        reverse=True,
    )
    return [DimensionContributionOut(**asdict(c)) for c in contributions]
