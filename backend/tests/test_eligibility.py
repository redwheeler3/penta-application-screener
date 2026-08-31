"""The per-member eligibility model and committee union pool."""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    Base,
    MemberEligibility,
    MemberRules,
    StatusSource,
    User,
    UserRole,
)
from app.schemas.settings import EligibilityRules
from app.services.eligibility import (
    effective_status_for,
    eligible_application_ids_for,
    union_eligible_application_ids,
)
from tests.application_support import activate_application, current_opening_id


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
        submitted_at=datetime.now(UTC),
    )
    return activate_application(db, app)


def set_member_rules(db: Session, user_id: int, **overrides: object) -> None:
    """Give a member a diverged ruleset (copy-on-write MemberRules row)."""
    db.add(
        MemberRules(
            opening_id=current_opening_id(db),
            user_id=user_id,
            rules=EligibilityRules(**overrides).model_dump(mode="json"),
        )
    )
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
            output={"flags": [{"category": "fake_contact"}]},
        )
    )
    db.commit()


def screen_pets(db: Session, application_id: int, *, dogs: int = 0, cats: int = 0,
                other_pets: list[str] | None = None) -> None:
    """Cache a screening result carrying only extracted pet facts (no flags), so the pet hard
    filter has facts to judge on read."""
    db.add(
        ApplicationAIResult(
            application_id=application_id,
            kind="screening",
            cache_key=f"pets-{application_id}",
            model_id="m",
            prompt_version="v",
            output={"flags": [], "pets": {"dogs": dogs, "cats": cats, "other_pets": other_pets or []}},
        )
    )
    db.commit()


def test_union_includes_machine_eligible_by_default() -> None:
    db = make_session()
    add_user(db, "m@x.com")
    clean = add_app(db, email="clean@x.com")
    add_app(db, email="rules-no@x.com", rules_ineligible=True)
    # Machine-eligible app is in the union; rules-ineligible is not.
    assert union_eligible_application_ids(db, current_opening_id(db)) == {clean.id}


def test_union_includes_applicant_one_member_overrode_to_eligible() -> None:
    """The core 1c behavior: an app machine-INELIGIBLE (AI-flagged) but overridden to
    ELIGIBLE by one member enters the union pool, even though no one else sees it."""
    db = make_session()
    alice = add_user(db, "alice@x.com")
    add_user(db, "bob@x.com")
    flagged = add_app(db, email="flagged@x.com")
    screen_flagged(db, flagged.id)  # machine verdict: ineligible/ai

    # Without an override, no member is eligible for it -> not in the union.
    assert union_eligible_application_ids(db, current_opening_id(db)) == set()

    # Alice overrides it to eligible -> it enters the union (eligible for at least one).
    db.add(
        MemberEligibility(
            opening_id=current_opening_id(db),
            application_id=flagged.id,
            user_id=alice.id,
            status=ApplicationStatus.ELIGIBLE,
            reviewed_fingerprint="fp",
        )
    )
    db.commit()
    assert union_eligible_application_ids(db, current_opening_id(db)) == {flagged.id}


def test_union_drops_machine_eligible_only_when_every_member_rejects() -> None:
    db = make_session()
    alice = add_user(db, "alice@x.com")
    bob = add_user(db, "bob@x.com")
    app = add_app(db, email="clean@x.com")  # machine-eligible

    # Only Alice rejects -> Bob still sees the machine verdict -> stays in the union.
    db.add(
        MemberEligibility(
            opening_id=current_opening_id(db),
            application_id=app.id, user_id=alice.id,
            status=ApplicationStatus.INELIGIBLE, reviewed_fingerprint="fp",
        )
    )
    db.commit()
    assert union_eligible_application_ids(db, current_opening_id(db)) == {app.id}

    # Both members reject -> nobody sees it eligible -> leaves the union.
    db.add(
        MemberEligibility(
            opening_id=current_opening_id(db),
            application_id=app.id, user_id=bob.id,
            status=ApplicationStatus.INELIGIBLE, reviewed_fingerprint="fp",
        )
    )
    db.commit()
    assert union_eligible_application_ids(db, current_opening_id(db)) == set()


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
            opening_id=current_opening_id(db),
            application_id=flagged.id, user_id=alice.id,
            status=ApplicationStatus.ELIGIBLE, reviewed_fingerprint="fp",
        )
    )
    db.commit()

    assert eligible_application_ids_for(db, alice.id, current_opening_id(db)) == {flagged.id, clean.id}
    assert eligible_application_ids_for(db, bob.id, current_opening_id(db)) == {clean.id}


def test_per_member_rules_change_who_each_member_sees_eligible() -> None:
    """Two members with different income floors see different eligibility for the same
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

    assert eligible_application_ids_for(db, strict.id, current_opening_id(db)) == set()
    assert eligible_application_ids_for(db, lenient.id, current_opening_id(db)) == {borderline.id}

    # Eligible under lenient's rules with no override anywhere -> in the union pool.
    assert union_eligible_application_ids(db, current_opening_id(db)) == {borderline.id}


def test_per_member_pet_limit_changes_eligibility_from_extracted_facts() -> None:
    """Pet eligibility diverges per member like income. An applicant with two
    dogs is rules-ineligible for a member on the default max_dogs=1, but eligible for a member
    who raised max_dogs to 2 — driven purely by the AI-extracted pet facts + each member's
    limit. The union includes them (eligible under the lenient member's rules)."""
    db = make_session()
    strict = add_user(db, "strict@x.com")          # default rules: max_dogs=1
    lenient = add_user(db, "lenient@x.com")
    two_dogs = add_app(
        db,
        email="twodogs@x.com",
        normalized={
            "household_income": 100_000,
            "child_count": 1,
            "child_details": [{"first_name": "Kid", "last_name": "One", "age": 5}],
        },
    )
    # The screening pass extracted two dogs (a fact); no flags.
    screen_pets(db, two_dogs.id, dogs=2)

    set_member_rules(db, lenient.id, max_dogs=2)

    assert eligible_application_ids_for(db, strict.id, current_opening_id(db)) == set()       # over the default limit
    assert eligible_application_ids_for(db, lenient.id, current_opening_id(db)) == {two_dogs.id}
    assert union_eligible_application_ids(db, current_opening_id(db)) == {two_dogs.id}


def test_pet_facts_absent_before_screening_do_not_gate() -> None:
    """Before screening there are no extracted pet facts, so the pet check can't gate — a
    strict pet limit doesn't exclude an unscreened applicant (we need the screen to get the
    counts). This keeps the screening-eligibility gate consistent with import."""
    db = make_session()
    strict = add_user(db, "strict@x.com")
    unscreened = add_app(
        db,
        email="unscreened@x.com",
        normalized={
            "household_income": 100_000,
            "child_count": 1,
            "child_details": [{"first_name": "Kid", "last_name": "One", "age": 5}],
        },
    )
    set_member_rules(db, strict.id, max_dogs=0, max_cats=0)

    # No screening result cached -> no pet facts -> pet check skipped -> still eligible.
    assert eligible_application_ids_for(db, strict.id, current_opening_id(db)) == {unscreened.id}


def test_pet_only_ineligible_attributes_to_ai_source(monkeypatch) -> None:
    """A pet-limit verdict shows source AI, not Rules, because AI extracts the
    counts from free text first, so they land at Screen. The applicant is otherwise clean, so
    pets are the sole reason."""
    db = make_session()
    member = add_user(db, "m@x.com")
    over = add_app(
        db,
        email="dogs@x.com",
        normalized={
            "household_income": 100_000,
            "child_count": 1,
            "child_details": [{"first_name": "Kid", "last_name": "One", "age": 5}],
        },
    )
    screen_pets(db, over.id, dogs=2)  # committee default max_dogs=1 -> over the limit

    status, source = effective_status_for(db, member.id, current_opening_id(db), over)
    assert status == ApplicationStatus.INELIGIBLE
    assert source == StatusSource.AI


def test_mixed_pet_and_numeric_ineligible_stays_rules_source(monkeypatch) -> None:
    """A numeric reason present alongside pets keeps source Rules: the numeric reason alone
    made it ineligible from submitted fields, so Rules is the honest higher-trust source. Only a pet-ONLY
    verdict moves to AI."""
    db = make_session()
    member = add_user(db, "m@x.com")
    # Owns real estate (numeric rule) AND two dogs (pet rule).
    over = add_app(
        db,
        email="both@x.com",
        rules_ineligible=True,
        normalized={
            "household_income": 100_000,
            "child_count": 1,
            "child_details": [{"first_name": "Kid", "last_name": "One", "age": 5}],
        },
    )
    screen_pets(db, over.id, dogs=2)

    status, source = effective_status_for(db, member.id, current_opening_id(db), over)
    assert status == ApplicationStatus.INELIGIBLE
    assert source == StatusSource.RULES


def test_member_muting_a_flag_category_makes_them_eligible() -> None:
    """A member who disables an AI flag category is not gated by it, while a member
    who has not muted it still sees the applicant as ineligible."""
    db = make_session()
    picky = add_user(db, "picky@x.com")
    lenient = add_user(db, "lenient@x.com")
    flagged = add_app(db, email="flagged@x.com")
    screen_flagged(db, flagged.id)  # a fake_contact flag

    # lenient mutes fake_contact; picky keeps it.
    set_member_rules(db, lenient.id, disabled_checks=["fake_contact"])

    assert eligible_application_ids_for(db, picky.id, current_opening_id(db)) == set()          # still gated
    assert eligible_application_ids_for(db, lenient.id, current_opening_id(db)) == {flagged.id}  # muted -> eligible
    # Union includes it: eligible for the lenient member, no override anywhere.
    assert union_eligible_application_ids(db, current_opening_id(db)) == {flagged.id}


def test_muted_flag_effective_status_is_untouched_not_ai() -> None:
    """A muted flag doesn't just flip eligibility — the source reads UNTOUCHED (nothing is
    gating), not AI, because the flag no longer counts for that member."""
    db = make_session()
    member = add_user(db, "m@x.com")
    flagged = add_app(db, email="flagged@x.com")
    screen_flagged(db, flagged.id)
    set_member_rules(db, member.id, disabled_checks=["fake_contact"])

    status, source = effective_status_for(db, member.id, current_opening_id(db), flagged)
    assert status == ApplicationStatus.ELIGIBLE
    assert source == StatusSource.UNTOUCHED
