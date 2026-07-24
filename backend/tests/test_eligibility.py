"""The per-member eligibility model and the union pool (M15 1c)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    Base,
    MemberEligibility,
    User,
    UserRole,
)
from app.services.eligibility import (
    eligible_application_ids_for,
    union_eligible_application_ids,
)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def add_user(db: Session, email: str) -> User:
    user = User(email=email, display_name=email, role=UserRole.MEMBER, is_active=True)
    db.add(user)
    db.commit()
    return user


def add_app(db: Session, *, email: str, hard_filter_reasons: list[dict] | None = None) -> Application:
    app = Application(
        primary_email=email,
        applicant_name="A",
        raw_row={},
        raw_row_hash=email,
        normalized={},
        hard_filter_reasons=hard_filter_reasons or [],
    )
    db.add(app)
    db.commit()
    return app


def screen_flagged(db: Session, application_id: int) -> None:
    """Cache a screening result with a flag, so the machine verdict reads ineligible/ai."""
    db.add(
        ApplicationAIResult(
            application_id=application_id,
            kind="screening",
            cache_key=f"k-{application_id}",
            model_id="m",
            prompt_version="v",
            output={"flags": [{"category": "pet_policy"}]},
        )
    )
    db.commit()


def test_union_includes_machine_eligible_by_default() -> None:
    db = make_session()
    add_user(db, "m@x.com")
    clean = add_app(db, email="clean@x.com")
    add_app(
        db,
        email="rules-no@x.com",
        hard_filter_reasons=[{"code": "owns_real_estate", "message": "x", "details": {}}],
    )
    # Machine-eligible app is in the union; rules-ineligible is not.
    assert union_eligible_application_ids(db) == {clean.id}


def test_union_includes_applicant_one_member_overrode_to_eligible() -> None:
    """The core 1c behavior: an app machine-INELIGIBLE (AI-flagged) but overridden to
    ELIGIBLE by one member enters the union pool, even though no one else sees it."""
    db = make_session()
    alice = add_user(db, "alice@x.com")
    add_user(db, "bob@x.com")
    flagged = add_app(db, email="flagged@x.com")
    screen_flagged(db, flagged.id)  # machine verdict: ineligible/ai

    # Without an override, no member is eligible for it -> not in the union.
    assert union_eligible_application_ids(db) == set()

    # Alice overrides it to eligible -> it enters the union (eligible for at least one).
    db.add(
        MemberEligibility(
            application_id=flagged.id,
            user_id=alice.id,
            status=ApplicationStatus.ELIGIBLE,
            reviewed_fingerprint="fp",
        )
    )
    db.commit()
    assert union_eligible_application_ids(db) == {flagged.id}


def test_union_drops_machine_eligible_only_when_every_member_rejects() -> None:
    db = make_session()
    alice = add_user(db, "alice@x.com")
    bob = add_user(db, "bob@x.com")
    app = add_app(db, email="clean@x.com")  # machine-eligible

    # Only Alice rejects -> Bob still sees the machine verdict -> stays in the union.
    db.add(
        MemberEligibility(
            application_id=app.id, user_id=alice.id,
            status=ApplicationStatus.INELIGIBLE, reviewed_fingerprint="fp",
        )
    )
    db.commit()
    assert union_eligible_application_ids(db) == {app.id}

    # Both members reject -> nobody sees it eligible -> leaves the union.
    db.add(
        MemberEligibility(
            application_id=app.id, user_id=bob.id,
            status=ApplicationStatus.INELIGIBLE, reviewed_fingerprint="fp",
        )
    )
    db.commit()
    assert union_eligible_application_ids(db) == set()


def test_per_member_view_reflects_only_that_members_overrides() -> None:
    db = make_session()
    alice = add_user(db, "alice@x.com")
    bob = add_user(db, "bob@x.com")
    flagged = add_app(db, email="flagged@x.com")
    screen_flagged(db, flagged.id)  # machine: ineligible for everyone
    clean = add_app(db, email="clean@x.com")  # machine: eligible for everyone

    # Alice overrides the flagged one to eligible; Bob does nothing.
    db.add(
        MemberEligibility(
            application_id=flagged.id, user_id=alice.id,
            status=ApplicationStatus.ELIGIBLE, reviewed_fingerprint="fp",
        )
    )
    db.commit()

    assert eligible_application_ids_for(db, alice.id) == {flagged.id, clean.id}
    assert eligible_application_ids_for(db, bob.id) == {clean.id}
