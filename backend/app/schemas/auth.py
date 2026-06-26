"""Response shapes for the auth router."""

from app.schemas.base import ResponseModel


class CurrentUser(ResponseModel):
    id: int
    email: str
    display_name: str
    avatar_url: str | None = None
    role: str


class MeResponse(ResponseModel):
    """GET /auth/me — the signed-in user, or null when there is no session.

    Not an error: an unauthenticated caller gets 200 with ``user: null`` (the SPA
    bootstraps on it), so this is a normal response, not problem+json.
    """

    user: CurrentUser | None = None


class LogoutResponse(ResponseModel):
    ok: bool = True
