from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Base
from app.services.google_credentials import (
    GOOGLE_HTTP_TIMEOUT_SECONDS,
    credentials_from_token,
    get_google_sheet_credentials,
    get_google_token,
    google_auth_request_with_timeout,
    save_google_token,
)

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


def test_save_google_token_converts_relative_expiry_to_absolute(monkeypatch) -> None:
    db = make_session()
    monkeypatch.setattr("app.services.google_credentials.time.time", lambda: 1_000.0)

    save_google_token(db, user_id=1, token={"access_token": "first", "expires_in": 3_600})

    stored = get_google_token(db, user_id=1)
    assert stored is not None
    assert stored["expires_at"] == 4_600.0


def test_credentials_from_token_honours_the_stored_expiry() -> None:
    credentials = credentials_from_token(
        {"access_token": "expired", "expires_at": 1, "refresh_token": "refresh"},
        Settings(google_client_id="client", google_client_secret="secret"),
    )

    assert credentials.expired is True


def test_get_google_sheet_credentials_refreshes_a_legacy_token(monkeypatch) -> None:
    class FakeCredentials:
        expiry = None
        expired = False
        refresh_token = "refresh"
        token = "old"

        def refresh(self, _request) -> None:
            self.token = "fresh"
            self.expiry = datetime.fromtimestamp(2_000_000_000, tz=UTC).replace(tzinfo=None)

    db = make_session()
    save_google_token(db, user_id=1, token={"access_token": "old", "refresh_token": "refresh"})
    monkeypatch.setattr("app.services.google_credentials.credentials_from_token", lambda *_: FakeCredentials())

    credentials = get_google_sheet_credentials(db, user_id=1, settings=Settings())

    assert credentials is not None
    stored = get_google_token(db, user_id=1)
    assert stored is not None
    assert stored["access_token"] == "fresh"
    assert stored["expires_at"] == 2_000_000_000.0


def test_google_auth_request_has_a_short_timeout(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class Request:
        def __call__(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            return "response"

    monkeypatch.setattr("app.services.google_credentials.GoogleAuthRequest", Request)

    assert google_auth_request_with_timeout("https://oauth.example", timeout=120) == "response"
    assert seen["kwargs"] == {"timeout": GOOGLE_HTTP_TIMEOUT_SECONDS}
