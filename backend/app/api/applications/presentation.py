from dataclasses import asdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.model_catalog import supports_reasoning_effort
from app.ai.schemas import PoolDimensionReport
from app.core.time import as_utc, pacific_date, pacific_today, utc_isoformat
from app.db.models import (
    Analysis,
    Application,
    ApplicationAIResult,
    ApplicationCommitteeNote,
    ApplicationNote,
    ApplicationParticipation,
    ApplicationVersion,
    MemberEligibility,
    Opening,
    OpeningOutcome,
    User,
)
from app.domain.ranking import CandidateScores, rank_candidates
from app.schemas.applications import (
    AIModelTraceOut,
    AIResultTraceOut,
    ApplicationDetail,
    ApplicationSummary,
    CommitteeNoteOut,
    CommitteeOpeningOut,
    DimensionContributionOut,
    DimensionScoringTraceOut,
    EligibilityUpdate,
    PetFactsOut,
    ScreeningFlagOut,
)
from app.services.applications.content import extract_essays
from app.services.applications.screening_results import selected_screening_results
from app.services.applications.shared_shortlist import is_shortlisted
from app.services.applications.stars import is_starred
from app.services.eligibility.evaluation import (
    active_flags,
    overrides_by_app,
)
from app.services.eligibility.rules import (
    hard_filter_reasons_for,
    normalized_with_ages,
    pet_facts_from_screening,
    rules_config_for,
)
from app.services.eligibility.status import (
    effective_status,
    override_is_stale,
    resolve_machine_status,
)
from app.services.openings.catalog import opening_phase
from app.services.openings.participation import opening_ids_by_application
from app.services.ranking.analysis import get_current_analysis
from app.services.ranking.dimensions import current_dimension_report
from app.services.ranking.member_state import (
    dimension_weights,
    get_or_reconcile_member_ranking,
)
from app.services.ranking.view import (
    candidate_scores,
    scored_dimensions,
    selected_application_scores,
)


def serialize_summary(
    app: Application,
    reasons: list[dict[str, Any]],
    override: MemberEligibility | None = None,
    flags: list[dict[str, Any]] | None = None,
    starred: bool = False,
    shortlisted: bool = False,
    opening_ids: list[int] | None = None,
    selected: bool = False,
) -> ApplicationSummary:
    """One application as the signed-in member sees it. ``status``/``status_source``/``stale``
    are that member's effective view: their override if present, else the machine verdict
    computed from the current findings — where ``reasons`` are the deterministic hard-filter
    reasons derived on read under this member's rules."""
    normalized = app.normalized or {}
    status, source = effective_status(
        override,
        reasons=reasons,
        has_ai_flags=bool(flags),
    )
    return ApplicationSummary(
        id=app.id,
        primary_email=app.primary_email,
        applicant_name=app.applicant_name,
        co_applicant_name=app.co_applicant_name,
        status=status.value,
        status_source=source.value,
        stale=override_is_stale(override, reasons, flags),
        hard_filter_reasons=reasons,
        child_count=normalized.get("child_count"),
        household_income=normalized.get("household_income"),
        # null = screening pass not run; int = flag count (0 = ran clean).
        flag_count=None if flags is None else len(flags),
        # Distinct flag categories from the latest pass, for the list REASON cell.
        flag_categories=None if flags is None else _distinct_categories(flags),
        starred_by_me=starred,
        shortlisted=shortlisted,
        opening_ids=opening_ids or [],
        selected=selected,
    )


def committee_opening(opening: Opening) -> CommitteeOpeningOut:
    return CommitteeOpeningOut(
        id=opening.id,
        unit_size_bedrooms=opening.unit_size_bedrooms,
        housing_charge_cents=opening.housing_charge_cents,
        application_open_date=opening.application_open_date,
        application_close_date=opening.application_close_date,
        move_in_date=opening.move_in_date,
        phase=opening_phase(opening).value,
    )


def _distinct_categories(flags: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for flag in flags:
        category = flag.get("category")
        if category and category not in seen:
            seen.append(category)
    return seen


def _pet_facts_out(output: dict[str, Any] | None) -> PetFactsOut | None:
    """The pets block of a screening result as the detail's ``PetFactsOut`` — counts plus the
    AI's reasoning (the read shown at the pet finding). None when no pet facts exist."""
    pets = (output or {}).get("pets") if output else None
    if not pets:
        return None
    return PetFactsOut(
        dogs=pets.get("dogs", 0),
        cats=pets.get("cats", 0),
        other_pets=list(pets.get("other_pets", []) or []),
        reasoning=pets.get("reasoning", "") or "",
    )


def eligibility_update(app: Application, db: Session, user: User, opening_id: int) -> EligibilityUpdate:
    """Current eligibility fields without loading essays, notes, or ranking scores."""
    rules = rules_config_for(db, user.id, opening_id)
    result = selected_screening_results(db, [app.id]).get(app.id)
    flags = active_flags((result.output or {}).get("flags", []) if result else None, rules.disabled_checks)
    facts = pet_facts_from_screening(result.output) if result else None
    reasons = hard_filter_reasons_for(rules, app, pet_facts=facts)
    override = overrides_by_app(db, user.id, opening_id, [app.id]).get(app.id)
    status, source = effective_status(override, reasons=reasons, has_ai_flags=bool(flags))
    automatic, automatic_source = resolve_machine_status(reasons=reasons, has_ai_flags=bool(flags))
    return EligibilityUpdate(
        id=app.id, status=status.value, status_source=source.value,
        stale=override_is_stale(override, reasons, flags), hard_filter_reasons=reasons,
        auto_status=automatic.value, auto_status_source=automatic_source.value,
    )


def serialize_detail(
    app: Application, db: Session, user: User, opening_id: int
) -> ApplicationDetail:
    # The raw source row and AI narrative are shown to any committee member: they're
    # trusted screeners, and these just back the data the member already sees.
    rules_config = rules_config_for(db, user.id, opening_id)
    flag_result = selected_screening_results(db, [app.id]).get(app.id)
    # Active flags drive both the displayed findings and the member's verdict.
    flags = active_flags(
        (flag_result.output or {}).get("flags", []) if flag_result else None,
        rules_config.disabled_checks,
    )
    pet_facts = pet_facts_from_screening(flag_result.output) if flag_result else None
    override = overrides_by_app(db, user.id, opening_id, [app.id]).get(app.id)
    opening_ids = opening_ids_by_application(db, [app.id])[app.id]
    reasons = hard_filter_reasons_for(
        rules_config,
        app,
        pet_facts=pet_facts,
    )
    is_selected = (
        db.scalar(
            select(ApplicationParticipation.id).where(
                ApplicationParticipation.application_id == app.id,
                ApplicationParticipation.opening_id == opening_id,
                ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
            )
        )
        is not None
    )
    summary = serialize_summary(
        app, reasons=reasons, override=override, flags=flags,
        starred=is_starred(db, app.id, user.id),
        shortlisted=is_shortlisted(db, opening_id, app.id),
        opening_ids=opening_ids,
        selected=is_selected,
    )
    # What the machine would decide from the current findings, independent of this
    # member's override — lets the UI show the live automatic verdict (the result of
    # clearing the override) without re-deriving the rules client-side. Uses THIS member's
    # rules for the reasons half.
    auto_status, auto_source = resolve_machine_status(
        reasons=reasons, has_ai_flags=bool(flags)
    )
    submission_version_count, first_submitted_at = db.execute(
        select(func.count(), func.min(ApplicationVersion.submitted_at)).where(
            ApplicationVersion.application_id == app.id
        )
    ).one()

    analysis = get_current_analysis(db, opening_id)
    report = current_dimension_report(analysis) if analysis is not None else None
    results = selected_application_scores(db, app.id, report) if report is not None else []
    scoring_trace = _dimension_scoring_trace(results)
    captured_candidate = CandidateScores(
        application_id=app.id, name=app.applicant_name,
        scores=scored_dimensions(report, {result.kind: result.output or {} for result in results}) if report is not None else [],
    )
    dimension_scores = _dimension_scores(
        db,
        app,
        user,
        analysis,
        report,
        captured_candidate,
        include_historical=is_selected,
    )
    return ApplicationDetail(
        **summary.model_dump(),
        auto_status=auto_status.value,
        auto_status_source=auto_source.value,
        first_submitted_at=utc_isoformat(first_submitted_at or app.submitted_at),
        last_submitted_at=utc_isoformat(app.submitted_at),
        submission_version_count=submission_version_count,
        normalized=normalized_with_ages(
            app.normalized or {},
            pacific_date(app.submitted_at) if app.submitted_at is not None else pacific_today(),
        ),
        essays=extract_essays(app.raw_row or {}),
        flags=(
            [ScreeningFlagOut(**f) for f in flags] if flags is not None else None
        ),
        # Pull the pets block (incl. the AI's neutral summary) straight from the screening
        # output — the domain pet_facts above carries only the counts the filter judges, not
        # the display prose.
        pet_facts=_pet_facts_out(flag_result.output if flag_result else None),
        raw_row=app.raw_row,
        ai_narrative=flag_result.narrative if flag_result is not None else None,
        screening_trace=_result_trace(flag_result),
        # This candidate's scores against the current run's dimensions, joined to
        # their labels. null = no run, or not scored under it.
        dimension_scores=dimension_scores,
        dimension_scoring_trace=scoring_trace,
        private_note=_private_note(db, app.id, user.id),
        committee_notes=committee_notes(db, app.id, user.id),
    )


def _private_note(db: Session, application_id: int, user_id: int) -> str:
    note = db.scalar(
        select(ApplicationNote.note).where(
            ApplicationNote.application_id == application_id,
            ApplicationNote.user_id == user_id,
        )
    )
    return note or ""


def committee_notes(
    db: Session, application_id: int, current_user_id: int
) -> list[CommitteeNoteOut]:
    rows = db.execute(
        select(ApplicationCommitteeNote, User)
        .join(User, User.id == ApplicationCommitteeNote.author_user_id)
        .where(ApplicationCommitteeNote.application_id == application_id)
        .order_by(
            ApplicationCommitteeNote.created_at.desc(),
            ApplicationCommitteeNote.id.desc(),
        )
    ).all()
    return [
        CommitteeNoteOut(
            id=note.id,
            author_name=author.display_name.strip() or author.email,
            body=note.body,
            created_at=as_utc(note.created_at),
            updated_at=as_utc(note.updated_at),
            editable_by_me=note.author_user_id == current_user_id,
        )
        for note, author in rows
    ]


def _result_trace(result: ApplicationAIResult | None) -> AIResultTraceOut | None:
    if result is None:
        return None
    return AIResultTraceOut(
        model_id=result.model_id,
        supports_reasoning_effort=supports_reasoning_effort(result.model_id),
        reasoning_effort=result.reasoning_effort,
        prompt_version=result.prompt_version,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
    )


def _dimension_scoring_trace(
    results: list[ApplicationAIResult],
) -> DimensionScoringTraceOut | None:
    if not results:
        return None
    return DimensionScoringTraceOut(
        dimension_count=len(results),
        models=[
            AIModelTraceOut(
                model_id=model_id,
                supports_reasoning_effort=supports_reasoning_effort(model_id),
                reasoning_effort=reasoning_effort,
            )
            for model_id, reasoning_effort in sorted(
                {
                    (result.model_id, result.reasoning_effort)
                    for result in results
                },
                key=lambda item: (item[0], item[1] or ""),
            )
        ],
        prompt_versions=sorted({result.prompt_version for result in results}),
        input_tokens=sum(result.input_tokens for result in results),
        output_tokens=sum(result.output_tokens for result in results),
        cost_usd=round(sum(result.cost_usd for result in results), 6),
    )


def _dimension_scores(
    db: Session,
    app: Application,
    user: User,
    analysis: Analysis | None,
    report: PoolDimensionReport | None,
    captured_candidate: CandidateScores,
    *,
    include_historical: bool,
) -> list[DimensionContributionOut] | None:
    """The candidate's per-dimension scores under the current analysis, ordered by
    importance to THIS candidate's ranking in the signed-in member's weighting.

    Returns None when there is no run or the candidate has no scores for its
    dimension set. These are the candidate's ranking ``contributions`` (the
    ranked-list row is the top slice of this list), ordered by ``abs(impact)``
    (``impact = weight · (score − pool_mean)``) so the dimensions that most moved
    this candidate come first. Weight-0 (Ignored) dimensions are dropped — they
    contribute nothing to the ranking.
    """
    if report is None:
        return None
    member_ranking = get_or_reconcile_member_ranking(db, analysis, user)

    weights = dimension_weights(member_ranking, report=report)
    if not any(weight > 0 for weight in weights.values()):
        return []

    ranked = rank_candidates(
        candidate_scores(
            db,
            analysis,
            include_application=app if include_historical else None,
            report=report,
            captured_candidate=captured_candidate,
        ),
        weights,
    )
    candidate = next((c for c in ranked if c.application_id == app.id), None)
    if candidate is None:
        return None

    contributions = sorted(
        (c for c in candidate.contributions if c.weight > 0),
        key=lambda c: abs(c.impact),
        reverse=True,
    )
    return [DimensionContributionOut(**asdict(c)) for c in contributions]
