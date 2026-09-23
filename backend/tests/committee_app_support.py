"""Shared committee-app wiring for application and screening API tests."""

from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.ai.mock_provider import MockProvider
from app.api.dependencies import require_current_user
from app.api.screening import get_ai_provider
from app.db.models import Application, User, UserRole
from app.db.session import get_db
from app.services.run_lock import ensure_lock_row
from tests.app_support import shared_test_app
from tests.application_support import activate_application
from tests.db_support import memory_session


def setup_committee_app(
    role: UserRole | None,
) -> tuple[FastAPI, Session, MockProvider]:
    """Wire the shared route graph to an isolated DB and optional committee user."""
    db = memory_session()
    ensure_lock_row(db)

    user = None
    if role is not None:
        user = User(
            email="admin@x.com",
            display_name="Admin",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()

    app = shared_test_app()
    app.dependency_overrides[get_db] = lambda: db
    if user is not None:
        app.dependency_overrides[require_current_user] = lambda: user

    provider = MockProvider()
    app.dependency_overrides[get_ai_provider] = lambda: provider
    return app, db, provider


def add_eligible_application(
    db: Session,
    *,
    email: str,
    raw_hash: str,
    name: str = "Test",
    active: bool = True,
) -> Application:
    application = Application(
        primary_email=email,
        applicant_name=name,
        raw_row={},
        raw_row_hash=raw_hash,
        # The name is surfaced in the prompt, so tests can route a verdict to one
        # application regardless of concurrent screening completion order.
        normalized={"applicant_name": name},
        submitted_at=datetime.now(UTC),
    )
    if active:
        return activate_application(db, application)
    db.add(application)
    db.commit()
    return application
