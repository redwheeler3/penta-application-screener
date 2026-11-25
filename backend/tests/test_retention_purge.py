from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    ApplicationAIResult,
    ApplicationParticipation,
    Feedback,
    OpeningOutcome,
    RetentionDeletion,
    User,
    UserRole,
)
from app.services.applications import purge
from app.services.applications.locking import lock_application
from app.services.applications.purge import purge_due_applicant_data
from tests.application_support import current_opening
from tests.db_support import memory_session
from tests.opening_support import create_direct_selection_opening
from tests.test_write_concurrency import request_sessions


def _db():
    return memory_session(foreign_keys=True)


def _due_application(db) -> Application:
    application = Application(
        primary_email="applicant@example.com",
        applicant_name="Synthetic Applicant",
        raw_row={"synthetic": True},
        raw_row_hash="synthetic",
        normalized={},
        submitted_at=datetime(2025, 8, 26, tzinfo=UTC),
        retention_due_on=date(2026, 8, 26),
        synthetic_data=True,
    )
    user = User(
        email="admin@example.com",
        display_name="Synthetic Admin",
        role=UserRole.ADMIN,
    )
    db.add_all([application, user])
    db.flush()
    db.add_all(
        [
            ApplicationAIResult(
                producer_application_id=application.id,
                kind="screening",
                cache_key="synthetic-cache-key",
                model_id="synthetic-model",
                prompt_version="synthetic",
                output={},
            ),
            Feedback(
                user_id=user.id,
                body="Synthetic feedback",
                applicant_id=application.id,
                app_version="test",
            ),
        ]
    )
    db.commit()
    return application


@pytest.mark.parametrize(("lifecycle", "expected_rule"), [
    ("private", "draft_actionability"),
    ("unsuccessful", "one_year"),
    ("selected", "selected_seven_years"),
])
def test_due_application_is_completely_purged(lifecycle, expected_rule) -> None:
    db = _db()
    application = _due_application(db)
    if lifecycle == "private":
        application.submitted_at = None
    elif lifecycle == "selected":
        opening = current_opening(db)
        opening.decided_at = datetime(2019, 8, 26, 18, tzinfo=UTC)
        db.add(ApplicationParticipation(application_id=application.id, opening_id=opening.id,
            applied_at=opening.decided_at, outcome=OpeningOutcome.SELECTED))
    db.commit()
    application_id = application.id
    result = purge_due_applicant_data(db, now=datetime(2026, 8, 26, 18, tzinfo=UTC))

    assert result.applications_purged == 1
    assert db.get(Application, application_id) is None
    assert db.scalar(select(ApplicationAIResult)) is None
    assert db.scalar(select(Feedback)) is None
    deletion = db.scalar(select(RetentionDeletion))
    assert deletion is not None
    assert deletion.record_kind == "application"
    assert deletion.record_id == application_id
    assert deletion.retention_rule == expected_rule


@pytest.mark.parametrize("resolved", [False, True])
def test_purge_removes_linked_feedback_without_erasing_general_or_other_applicant_feedback(resolved):
    db = _db()
    _due_application(db)
    linked = db.scalar(select(Feedback))
    linked.resolved_at = datetime.now(UTC) if resolved else None
    other = Application(primary_email="retained@example.com", raw_row={}, raw_row_hash="retained", normalized={})
    db.add(other)
    db.flush()
    for applicant_id in (None, other.id):
        db.add(Feedback(user_id=linked.user_id, applicant_id=applicant_id, body="Unrelated synthetic feedback", app_version="test"))
    db.commit()
    purge_due_applicant_data(db, now=datetime(2026, 8, 26, 18, tzinfo=UTC))
    remaining = list(db.scalars(select(Feedback)))
    assert len(remaining) == 2
    assert {item.applicant_id for item in remaining} == {None, other.id}
    assert all(item.body == "Unrelated synthetic feedback" for item in remaining)


def test_due_unclaimed_draft_is_completely_purged() -> None:
    db = _db()
    draft = ApplicantDraft(
        email="draft@example.com",
        intent=ApplicantDraftIntent.SAVE,
        draft_token_hash="synthetic-draft-token",
        created_at=datetime(2025, 8, 26, tzinfo=UTC),
        saved_at=datetime(2025, 8, 26, tzinfo=UTC),
        expires_on=date(2026, 8, 26),
    )
    db.add(draft)
    db.commit()
    draft_id = draft.id

    result = purge_due_applicant_data(db, now=datetime(2026, 8, 26, 18, tzinfo=UTC))

    assert result.drafts_purged == 1
    assert db.get(ApplicantDraft, draft_id) is None
    deletion = db.scalar(select(RetentionDeletion))
    assert deletion is not None
    assert deletion.record_kind == "applicant_draft"
    assert deletion.record_id == draft_id
    assert deletion.retention_rule == "draft_actionability"


def test_selection_after_sweep_read_preserves_new_retention(monkeypatch) -> None:
    factory, _opening_id, admin_id, ids = request_sessions(closed=True)
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    with factory() as db:
        db.get(Application, ids[0]).retention_due_on = today + timedelta(days=1)
        db.commit()

    def select_before_lock(db, application_id):
        with factory() as other:
            create_direct_selection_opening(other, application_id,
                move_in_date=today + timedelta(days=30), decided_by=other.get(User, admin_id), now=now)
        return lock_application(db, application_id)

    monkeypatch.setattr(purge, "lock_application", select_before_lock)
    with factory() as db:
        result = purge_due_applicant_data(db, now=now + timedelta(days=1))
    with factory() as db:
        assert result.applications_purged == 0
        assert db.get(Application, ids[0]).retention_due_on.year == today.year + 7
        assert db.scalar(select(RetentionDeletion)) is None


def test_draft_renewed_after_sweep_read_is_not_deleted() -> None:
    db = _db()
    now = datetime(2026, 8, 26, 18, tzinfo=UTC)
    draft = ApplicantDraft(
        email="draft@example.com", intent=ApplicantDraftIntent.SAVE, draft_token_hash="synthetic",
        created_at=now, saved_at=now, expires_on=date(2026, 8, 26),
    )
    db.add(draft)
    db.commit()
    draft_id = draft.id
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    renewed = []

    def renew_before_delete(_connection, _cursor, statement, _parameters, _context, _many):
        if not renewed and "UPDATE applicant_drafts SET saved_at=applicant_drafts.saved_at" in statement:
            renewed.append(True)
            with factory() as other:
                other.get(ApplicantDraft, draft_id).expires_on = date(2026, 9, 1)
                other.commit()

    event.listen(db.get_bind(), "before_cursor_execute", renew_before_delete)
    try:
        result = purge_due_applicant_data(db, now=now)
        assert renewed == [True]
        assert result.drafts_purged == 0
        assert db.get(ApplicantDraft, draft_id).expires_on == date(2026, 9, 1)
        assert db.scalar(select(RetentionDeletion)) is None
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", renew_before_delete)


def test_retention_expiry_blocks_sessions_scope_and_direct_selection() -> None:
    from app.db.models import PasswordlessIdentityKind
    from app.services.applications.scope import opening_applications
    from app.services.auth.applicant import authenticate_applicant
    from app.services.auth.passwordless import create_browser_session
    from app.services.openings.direct_selection import available_previous_applicant

    factory, opening_id, _, ids = request_sessions(closed=True)
    now = datetime.now(UTC)
    with factory() as db:
        application = db.get(Application, ids[0])
        token = create_browser_session(db, identity_kind=PasswordlessIdentityKind.APPLICANT,
                                       application_id=application.id, now=now - timedelta(days=1))
        application.retention_due_on = pacific_today(now=now)
        db.commit()
        assert application.id not in {app.id for app in opening_applications(db, opening_id)}
        assert available_previous_applicant(db, application.id) is None
        assert authenticate_applicant(db, token.token, now=now) is None


@pytest.mark.parametrize("legacy", [False, True])
def test_first_source_purge_removes_pool_text_but_preserves_generic_criteria_and_costs(legacy):
    from app.db.models import (
        Analysis,
        AnalysisAudit,
        MemberRanking,
        Opening,
        RunCostLedger,
        RunPassCost,
    )
    from app.schemas.settings import AppSettings
    from app.services.applications.purge import purge_expired_application
    from app.services.ranking.analysis import apply_consolidation
    from app.services.ranking.audit import fan_out_audit_view
    from app.services.ranking.dimensions import current_dimension_report
    from tests.ranking_support import a_pattern_report
    db = _db()
    now = datetime.now(UTC)
    source = _due_application(db)
    source_id = source.id
    opening = current_opening(db)
    retained = Application(primary_email="retained@example.com", raw_row={}, raw_row_hash="retained", normalized={},
        submitted_at=now, retention_due_on=pacific_today(now=now) + timedelta(days=100))
    db.add(retained)
    db.flush()
    db.add(ApplicationParticipation(application_id=source_id, opening_id=opening.id, applied_at=now))
    marker = "SYNTHETIC_IDENTIFYING_MARKER"
    report = a_pattern_report().model_dump(mode="json")
    report["dimensions"][0]["why_it_differentiates"] = marker
    sources = None if legacy else [source_id, retained.id]
    affected = Analysis(opening_id=opening.id, source_application_ids=sources, dimension_report=report,
        audit=AnalysisAudit(discovery_narrative=marker, fan_out={"passes": [{"narrative": marker}]},
            decompose={"settled": [{"decision": marker}]}, match={"match_narrative": marker}, consolidate={"narrative": marker}))
    other = Opening(unit_size_bedrooms=1, housing_charge_cents=100000,
        application_close_date=opening.application_close_date, move_in_date=opening.move_in_date)
    db.add(other)
    db.flush()
    inherited = Analysis(opening_id=other.id, source_application_ids=[source_id, retained.id], dimension_report=report,
        audit=AnalysisAudit(discovery_narrative=marker))
    unrelated = Analysis(opening_id=opening.id, source_application_ids=[retained.id], dimension_report=a_pattern_report().model_dump(mode="json"),
        audit=AnalysisAudit(discovery_narrative="Unrelated retained trace"))
    ledger = RunCostLedger(kind="rank", passes=[RunPassCost(label="Pattern discovery", cost_usd=0.25)])
    db.add_all([affected, inherited, unrelated, ledger])
    db.commit()
    assert purge_expired_application(db, source, now=now)
    db.commit()
    assert db.get(Application, source_id) is None
    for analysis in [affected, inherited]:
        assert analysis.audit is None
        assert analysis.pool_text_purged
        assert marker not in str(analysis.dimension_report)
        assert current_dimension_report(analysis).dimensions[0].definition == a_pattern_report().dimensions[0].definition
        assert fan_out_audit_view(analysis) is None
    assert unrelated.audit.discovery_narrative == "Unrelated retained trace"
    assert db.get(Application, retained.id) is not None
    assert ledger.passes[0].cost_usd == 0.25
    # A late consolidation reply must not republish prose into the purged analysis.
    member = MemberRanking(analysis_id=affected.id, user_id=db.scalar(select(User.id)), run_state={})
    db.add(member)
    db.commit()
    apply_consolidation(db, affected, member, merges={}, audit=[], narrative=marker, settings=AppSettings())
    assert affected.audit is None
