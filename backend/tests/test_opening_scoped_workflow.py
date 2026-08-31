from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import (
    Analysis,
    Application,
    ApplicationParticipation,
    ApplicationShortlist,
    ApplicationStatus,
    Base,
    MemberEligibility,
    Opening,
    OpeningOutcome,
    OpeningRules,
    User,
    UserRole,
)
from app.schemas.openings import OpeningCreate
from app.schemas.settings import EligibilityRules
from app.services.application_scope import (
    opening_ai_applications,
    opening_applications,
    visible_committee_openings,
)
from app.services.eligibility import effective_status_for
from app.services.openings import create_opening
from app.services.ranking.analysis import all_known_dimensions, get_current_analysis
from app.services.rules import committee_default_rules
from app.services.shared_shortlist import is_shortlisted


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def opening(db: Session, *, bedrooms: int, move_offset: int) -> Opening:
    today = pacific_today()
    record = Opening(
        unit_size_bedrooms=bedrooms,
        housing_charge_cents=100_000,
        application_open_date=today - timedelta(days=10),
        application_close_date=today + timedelta(days=10),
        move_in_date=today + timedelta(days=move_offset),
        published_at=datetime.now(UTC),
    )
    db.add(record)
    db.flush()
    return record


def applicant(db: Session, *openings: Opening, income: int = 80_000) -> Application:
    sequence = db.query(Application).count() + 1
    record = Application(
        primary_email=f"applicant-{sequence}@example.com",
        applicant_name="Applicant",
        raw_row={},
        raw_row_hash=f"hash-{sequence}",
        normalized={"household_income": income, "child_count": 0},
        submitted_at=datetime.now(UTC),
    )
    db.add(record)
    db.flush()
    for context in openings:
        db.add(
            ApplicationParticipation(
                application_id=record.id,
                opening_id=context.id,
                applied_at=record.submitted_at,
            )
        )
    db.commit()
    return record


def rules(*, income_min: int) -> dict:
    return EligibilityRules(
        income_min=income_min,
        min_children=0,
        max_children=10,
    ).model_dump(mode="json")


def test_opening_context_isolates_rules_overrides_shortlist_and_current_analysis() -> None:
    db = make_db()
    first = opening(db, bedrooms=2, move_offset=30)
    second = opening(db, bedrooms=1, move_offset=60)
    db.add_all(
        [
            OpeningRules(opening_id=first.id, rules=rules(income_min=70_000)),
            OpeningRules(opening_id=second.id, rules=rules(income_min=90_000)),
        ]
    )
    user = User(email="member@example.com", display_name="Member", role=UserRole.MEMBER)
    db.add(user)
    db.commit()
    application = applicant(db, first, second)

    first_status, _ = effective_status_for(db, user.id, first.id, application)
    second_status, _ = effective_status_for(db, user.id, second.id, application)
    assert first_status == ApplicationStatus.ELIGIBLE
    assert second_status == ApplicationStatus.INELIGIBLE

    db.add(
        MemberEligibility(
            opening_id=second.id,
            application_id=application.id,
            user_id=user.id,
            status=ApplicationStatus.ELIGIBLE,
        )
    )
    db.add(
        ApplicationShortlist(
            opening_id=first.id,
            application_id=application.id,
            added_by_user_id=user.id,
        )
    )
    first_analysis = Analysis(opening_id=first.id, dimension_report={"dimensions": []})
    second_analysis = Analysis(opening_id=second.id, dimension_report={"dimensions": []})
    db.add_all([first_analysis, second_analysis])
    db.commit()

    assert effective_status_for(db, user.id, second.id, application)[0] == ApplicationStatus.ELIGIBLE
    assert is_shortlisted(db, first.id, application.id)
    assert not is_shortlisted(db, second.id, application.id)
    assert get_current_analysis(db, first.id).id == first_analysis.id
    assert get_current_analysis(db, second.id).id == second_analysis.id


def test_dimension_history_is_global_while_current_analyses_are_opening_specific() -> None:
    db = make_db()
    first = opening(db, bedrooms=2, move_offset=30)
    second = opening(db, bedrooms=1, move_offset=60)
    dimension = {
        "key": "community_participation",
        "name": "Community participation",
        "definition": "Willingness to contribute to shared work.",
        "high_end": "specific sustained contribution",
        "low_end": "little stated contribution",
        "why_it_differentiates": "Applicants describe different levels of participation.",
    }
    db.add(
        Analysis(
            opening_id=first.id,
            dimension_report={"dimensions": [dimension]},
        )
    )
    db.add(Analysis(opening_id=second.id, dimension_report={"dimensions": []}))
    db.commit()

    history = all_known_dimensions(db)
    assert history is not None
    assert [item.key for item in history.dimensions] == ["community_participation"]
    assert get_current_analysis(db, second.id).dimension_report == {"dimensions": []}


def test_new_opening_copies_latest_defaults_as_an_independent_snapshot() -> None:
    db = make_db()
    source = opening(db, bedrooms=2, move_offset=30)
    db.add(OpeningRules(opening_id=source.id, rules=rules(income_min=82_000)))
    db.commit()
    today = pacific_today()

    created = create_opening(
        db,
        OpeningCreate.model_validate(
            {
                "unitSizeBedrooms": 1,
                "housingChargeCents": 95_000,
                "applicationCloseDate": today + timedelta(days=20),
                "moveInDate": today + timedelta(days=60),
            }
        ),
    )
    db.commit()

    assert committee_default_rules(db, created.id).income_min == 82_000
    source_rules = db.query(OpeningRules).filter_by(opening_id=source.id).one()
    source_rules.rules = rules(income_min=99_000)
    db.commit()
    assert committee_default_rules(db, created.id).income_min == 82_000


def test_selected_household_is_visible_but_never_keeps_selector_or_ai_pool_alive() -> None:
    db = make_db()
    context = opening(db, bedrooms=2, move_offset=30)
    selected = applicant(db, context)
    remaining = applicant(db, context)
    participation = db.query(ApplicationParticipation).filter_by(
        application_id=selected.id, opening_id=context.id
    ).one()
    participation.outcome = OpeningOutcome.SELECTED
    db.commit()

    assert {item.id for item in opening_applications(db, context.id)} == {
        selected.id,
        remaining.id,
    }
    assert [item.id for item in opening_ai_applications(db, context.id)] == [remaining.id]
    assert [item.id for item in visible_committee_openings(db)] == [context.id]

    remaining.withdrawn_at = datetime.now(UTC)
    db.commit()
    assert [item.id for item in opening_applications(db, context.id)] == [selected.id]
    assert opening_ai_applications(db, context.id) == []
    assert visible_committee_openings(db) == []
