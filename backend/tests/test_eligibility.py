"""The per-member eligibility model and the union pool (M15 1c + per-member rules 1d)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    Base,
    MemberEligibility,
    MemberRules,
    User,
    UserRole,
)
from app.schemas.settings import EligibilityRules
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


def add_app(
    db: Session, *, email: str, rules_ineligible: bool = False, normalized: dict | None = None
) -> Application:
    """Reasons are computed on read from ``normalized`` + the member's rules (no stored
    column). ``rules_ineligible`` trips a deterministic filter for every default ruleset by
    owning real estate; ``normalized`` lets a test build a borderline (e.g. income) applicant.
    """
    normalized = dict(normalized or {})
    if rules_ineligible:
        normalized["has_real_estate"] = True
    app = Application(
        primary_email=email,
        applicant_name="A",
        raw_row={},
        raw_row_hash=email,
        normalized=normalized,
    )
    db.add(app)
    db.commit()
    return app


def set_member_rules(db: Session, user_id: int, **overrides: object) -> None:
    """Give a member a diverged ruleset (copy-on-write MemberRules row)."""
    db.add(MemberRules(user_id=user_id, rules=EligibilityRules(**overrides).model_dump(mode="json")))
    db.commit()


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
    add_app(db, email="rules-no@x.com", rules_ineligible=True)
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


def test_per_member_rules_change_who_each_member_sees_eligible() -> None:
    """M15 1d: two members with different income_min see different eligibility for the SAME
    borderline applicant, and the union includes an app eligible under EITHER member's rules.
    """
    db = make_session()
    strict = add_user(db, "strict@x.com")
    lenient = add_user(db, "lenient@x.com")
    # Income 60k: below a 70k floor, above a 50k floor. One complete child block (matches the
    # declared count, satisfies min_children=1), so income is the only lever that differs.
    borderline = add_app(
        db,
        email="borderline@x.com",
        normalized={
            "household_income": 60_000,
            "child_count": 1,
            "child_details": [{"first_name": "Kid", "last_name": "One", "age": 5}],
        },
    )

    # strict raises the income floor to 70k (borderline is rules-ineligible for them);
    # lenient drops it to 50k (borderline is rules-eligible for them).
    set_member_rules(db, strict.id, income_min=70_000)
    set_member_rules(db, lenient.id, income_min=50_000)

    assert eligible_application_ids_for(db, strict.id) == set()
    assert eligible_application_ids_for(db, lenient.id) == {borderline.id}

    # Eligible under lenient's rules with no override anywhere -> in the union pool.
    assert union_eligible_application_ids(db) == {borderline.id}
