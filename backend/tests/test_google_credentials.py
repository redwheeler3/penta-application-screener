from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.services.google_credentials import get_google_token, save_google_token

IDENTITY = "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"
READER = IDENTITY + " https://www.googleapis.com/auth/drive.file"


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_identity_login_does_not_downgrade_a_stored_reader_token() -> None:
    # The bug: a routine identity-only login overwrote the admin's drive.file reader token,
    # breaking sync (ACCESS_TOKEN_SCOPE_INSUFFICIENT) for the whole committee. The reader token
    # must survive a later narrower login.
    db = make_session()
    save_google_token(db, user_id=1, token={"access_token": "reader", "scope": READER,
                                            "refresh_token": "r1"})

    save_google_token(db, user_id=1, token={"access_token": "identity", "scope": IDENTITY})

    stored = get_google_token(db, user_id=1)
    assert stored is not None
    assert stored["access_token"] == "reader"
    assert "drive.file" in stored["scope"]


def test_relinking_with_drive_file_updates_the_token() -> None:
    # A re-consent that re-grants drive.file (the Picker flow) IS a superset and must replace
    # the stored token — this is how re-linking heals a previously-clobbered credential.
    db = make_session()
    save_google_token(db, user_id=1, token={"access_token": "old", "scope": IDENTITY})

    save_google_token(db, user_id=1, token={"access_token": "new", "scope": READER,
                                            "refresh_token": "r2"})

    stored = get_google_token(db, user_id=1)
    assert stored is not None
    assert stored["access_token"] == "new"
    assert "drive.file" in stored["scope"]


def test_reconsent_preserves_existing_refresh_token_when_omitted() -> None:
    # Google omits refresh_token on re-consent; a same-or-broader update must carry the stored
    # one forward so durable server-side refresh keeps working.
    db = make_session()
    save_google_token(db, user_id=1, token={"access_token": "a", "scope": READER,
                                            "refresh_token": "keep-me"})

    save_google_token(db, user_id=1, token={"access_token": "b", "scope": READER})

    stored = get_google_token(db, user_id=1)
    assert stored is not None
    assert stored["access_token"] == "b"
    assert stored["refresh_token"] == "keep-me"


def test_first_token_is_stored() -> None:
    db = make_session()
    save_google_token(db, user_id=1, token={"access_token": "first", "scope": IDENTITY})

    stored = get_google_token(db, user_id=1)
    assert stored is not None
    assert stored["access_token"] == "first"
