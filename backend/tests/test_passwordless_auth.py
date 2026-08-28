from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.time import as_utc
from app.db.models import (
    Application,
    Base,
    MagicLinkPurpose,
    PasswordlessIdentityKind,
    User,
)
from app.services.passwordless_auth import (
    authenticate_browser_session,
    consume_magic_link,
    create_browser_session,
    issue_magic_link,
    magic_link_request_allowed,
    revoke_browser_session,
    revoke_identity_magic_links,
    revoke_identity_sessions,
)

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _application(db: Session) -> Application:
    application = Application(
        primary_email="avery@example.test",
        applicant_name="Avery Example",
        raw_row={},
        raw_row_hash="synthetic",
        normalized={},
    )
    db.add(application)
    db.flush()
    return application


def _user(db: Session) -> User:
    user = User(email="member@example.test", display_name="Synthetic Member")
    db.add(user)
    db.flush()
    return user


def test_applicant_and_committee_links_share_the_24_hour_lifetime() -> None:
    db = _session()
    application = _application(db)
    user = _user(db)

    applicant = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW,
    )
    committee = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        email=user.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
        now=NOW,
    )

    assert as_utc(applicant.record.expires_at) == NOW + timedelta(hours=24)
    assert as_utc(committee.record.expires_at) == NOW + timedelta(hours=24)


def test_new_magic_link_revokes_only_older_links_for_the_same_identity_and_purpose() -> None:
    db = _session()
    first_application = _application(db)
    second_application = Application(
        primary_email="other@example.test",
        raw_row={},
        raw_row_hash="other-synthetic",
        normalized={},
    )
    db.add(second_application)
    db.flush()
    first = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=first_application.id,
        email=" Avery@Example.Test ",
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW,
    )
    other = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=second_application.id,
        email="avery@example.test",
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW,
    )

    replacement = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=first_application.id,
        email="avery@example.test",
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW + timedelta(minutes=1),
    )

    db.refresh(first.record)
    db.refresh(other.record)
    assert as_utc(first.record.revoked_at) == NOW + timedelta(minutes=1)
    assert other.record.revoked_at is None
    assert replacement.record.email == "avery@example.test"
    assert replacement.token != replacement.record.token_hash


def test_magic_link_is_single_use_and_expired_links_are_indistinguishable() -> None:
    db = _session()
    application = _application(db)
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW,
        lifetime=timedelta(minutes=5),
    )

    consumed = consume_magic_link(
        db,
        issued.token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW + timedelta(minutes=1),
    )

    assert consumed is not None
    assert consumed.application_id == application.id
    assert (
        consume_magic_link(
            db,
            issued.token,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            now=NOW + timedelta(minutes=2),
        )
        is None
    )

    expired = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW,
        lifetime=timedelta(minutes=1),
    )
    assert (
        consume_magic_link(
            db,
            expired.token,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            now=NOW + timedelta(minutes=1),
        )
        is None
    )
    assert (
        consume_magic_link(
            db,
            "unknown-token",
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            now=NOW,
        )
        is None
    )


def test_magic_link_purpose_must_match_its_identity_kind() -> None:
    db = _session()
    application = _application(db)

    with pytest.raises(ValueError, match="not valid"):
        issue_magic_link(
            db,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            application_id=application.id,
            email=application.primary_email,
            purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
            now=NOW,
        )


def test_magic_link_requests_are_coalesced_and_limited_per_identity() -> None:
    db = _session()
    application = _application(db)
    parameters = {
        "identity_kind": PasswordlessIdentityKind.APPLICANT,
        "application_id": application.id,
        "purpose": MagicLinkPurpose.APPLICANT_ACCESS,
        "request_limit": 3,
        "rate_window": timedelta(minutes=15),
        "coalesce_window": timedelta(seconds=60),
    }
    assert magic_link_request_allowed(db, now=NOW, **parameters)
    for minute in (0, 2, 4):
        issued_at = NOW + timedelta(minutes=minute)
        issue_magic_link(
            db,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            application_id=application.id,
            email=application.primary_email,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            now=issued_at,
        )
        assert not magic_link_request_allowed(
            db,
            now=issued_at + timedelta(seconds=30),
            **parameters,
        )

    assert not magic_link_request_allowed(
        db,
        now=NOW + timedelta(minutes=6),
        **parameters,
    )
    assert magic_link_request_allowed(
        db,
        now=NOW + timedelta(minutes=16),
        **parameters,
    )


def test_same_email_can_have_separate_applicant_and_committee_identities() -> None:
    db = _session()
    application = _application(db)
    user = User(email=application.primary_email, display_name="Avery Committee Member")
    db.add(user)
    db.flush()
    applicant_link = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW,
    )
    committee_link = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        email=user.email,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
        now=NOW,
    )

    consumed_applicant = consume_magic_link(
        db,
        applicant_link.token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW,
    )
    consumed_committee = consume_magic_link(
        db,
        committee_link.token,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
        now=NOW,
    )

    assert consumed_applicant is not None
    assert consumed_committee is not None
    assert consumed_applicant.application_id == application.id
    assert consumed_committee.user_id == user.id


def test_remembered_session_slides_idle_expiry_but_respects_absolute_expiry() -> None:
    db = _session()
    application = _application(db)
    issued = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        now=NOW,
        idle_lifetime=timedelta(days=7),
        absolute_lifetime=timedelta(days=30),
    )

    after_five_days = authenticate_browser_session(
        db,
        issued.token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        now=NOW + timedelta(days=5),
        idle_lifetime=timedelta(days=7),
    )
    assert after_five_days is not None
    assert as_utc(after_five_days.idle_expires_at) == NOW + timedelta(days=12)

    near_hard_limit = after_five_days
    for day in (10, 15, 20, 25):
        near_hard_limit = authenticate_browser_session(
            db,
            issued.token,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            now=NOW + timedelta(days=day),
            idle_lifetime=timedelta(days=7),
        )
    assert near_hard_limit is not None
    assert as_utc(near_hard_limit.idle_expires_at) == NOW + timedelta(days=30)

    assert (
        authenticate_browser_session(
            db,
            issued.token,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            now=NOW + timedelta(days=30),
            idle_lifetime=timedelta(days=7),
        )
        is None
    )
    assert issued.record.revoked_at == NOW + timedelta(days=30)


def test_sessions_are_hashed_and_revocable() -> None:
    db = _session()
    user = _user(db)
    first = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        now=NOW,
        idle_lifetime=timedelta(days=7),
        absolute_lifetime=timedelta(days=30),
    )
    second = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
        now=NOW,
        idle_lifetime=timedelta(days=7),
        absolute_lifetime=timedelta(days=30),
    )

    assert first.token != first.record.token_hash
    assert revoke_browser_session(db, first.token, now=NOW + timedelta(hours=1))
    assert (
        authenticate_browser_session(
            db,
            first.token,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            now=NOW + timedelta(hours=2),
        )
        is None
    )
    assert (
        revoke_identity_sessions(
            db,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            user_id=user.id,
            now=NOW + timedelta(hours=1),
        )
        == 1
    )
    db.refresh(second.record)
    assert as_utc(second.record.revoked_at) == NOW + timedelta(hours=1)


def test_all_unused_links_can_be_revoked_without_touching_consumed_links() -> None:
    db = _session()
    application = _application(db)
    consumed = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        now=NOW,
    )
    assert (
        consume_magic_link(
            db,
            consumed.token,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            now=NOW,
        )
        is not None
    )
    unused = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        email="new-address@example.test",
        purpose=MagicLinkPurpose.EMAIL_CHANGE,
        now=NOW,
    )

    assert (
        revoke_identity_magic_links(
            db,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            application_id=application.id,
            now=NOW + timedelta(minutes=1),
        )
        == 1
    )
    db.refresh(consumed.record)
    db.refresh(unused.record)
    assert consumed.record.revoked_at is None
    assert as_utc(unused.record.revoked_at) == NOW + timedelta(minutes=1)
