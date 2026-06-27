from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.ai.strands_provider import StrandsProvider
from app.api.problems import Problem
from app.db.models import User
from app.db.session import get_db
from app.services.settings import get_app_settings


def require_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise Problem("unauthorized", detail="Authentication required.")

    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        request.session.clear()
        raise Problem("unauthorized", detail="Authentication required.")

    return user


# Note: there is intentionally no role gate here. Every committee member is a
# trusted screener, so all routes use require_current_user. Re-add a
# require_admin dependency if a genuinely admin-only surface ever appears.


def get_ai_provider(db: Session = Depends(get_db)) -> AIProvider:
    """Real Bedrock-backed provider for the AI screening passes. Overridden in
    tests with a MockProvider. Shared by the screening and ranking routes so they
    have one provider construction and one test override point.
    """
    settings = get_app_settings(db)
    # Size the connection pool to the worker count so concurrent screening calls
    # don't queue on sockets.
    return StrandsProvider(
        region=settings.ai.region,
        max_pool_connections=settings.ai.max_workers,
    )

