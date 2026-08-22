from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.ai.strands_provider import StrandsProvider
from app.api.problems import Problem
from app.core.config import get_settings
from app.db.models import User, UserRole
from app.db.session import get_db
from app.services.settings import get_app_settings
from app.services.users import record_user_activity


def require_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise Problem("unauthorized", detail="Authentication required.")

    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        request.session.clear()
        raise Problem("unauthorized", detail="Authentication required.")

    record_user_activity(db, user=user)
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

