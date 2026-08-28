from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.ai.strands_provider import StrandsProvider
from app.api.session_cookie import clear_session_cookie, session_token
from app.core.config import get_settings
from app.core.problems import Problem
from app.db.models import PasswordlessIdentityKind, User, UserRole
from app.db.session import get_db
from app.services.committee_auth import authenticate_committee_user
from app.services.settings import get_app_settings


def optional_current_user(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User | None:
    committee_token = session_token(request, PasswordlessIdentityKind.COMMITTEE)
    if committee_token is not None:
        authentication = authenticate_committee_user(db, committee_token)
        if authentication is not None:
            request.state.browser_session = authentication.browser_session
            return authentication.user
        clear_session_cookie(response, PasswordlessIdentityKind.COMMITTEE)

    return None


def require_current_user(user: User | None = Depends(optional_current_user)) -> User:
    if user is None:
        raise Problem("unauthorized", detail="Authentication required.")
    return user


def require_admin(user: User = Depends(require_current_user)) -> User:
    """Gate shared infrastructure and user-administration changes."""
    if user.role != UserRole.ADMIN:
        raise Problem("forbidden", detail="This action requires an admin.")
    return user


def get_ai_provider(db: Session = Depends(get_db)) -> AIProvider:
    """Real multi-provider adapter for every AI pass.

    Model choices come from persisted app settings; provider credentials come from
    deployment secrets. Tests override this one construction point with MockProvider.
    """
    settings = get_app_settings(db)
    runtime = get_settings()
    # Size the connection pool to the worker count so concurrent screening calls
    # don't queue on sockets.
    return StrandsProvider(
        region=settings.ai.region,
        max_pool_connections=settings.ai.max_workers,
        openai_api_key=runtime.openai_api_key,
        anthropic_api_key=runtime.anthropic_api_key,
    )

