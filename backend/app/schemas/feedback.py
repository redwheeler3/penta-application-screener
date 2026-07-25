"""Request/response shapes for the feedback router.

The member submits body + the context they were in; identity, app version, and time
are stamped server-side (never trusted from the wire). Admins read the enriched list.
"""

from datetime import datetime

from pydantic import Field

from app.schemas.base import RequestModel, ResponseModel


class FeedbackCreate(RequestModel):
    # The only required field. Bounded so a runaway paste can't store unbounded text;
    # generous enough for a member to describe friction (and paste a little context).
    body: str = Field(min_length=1, max_length=5000)
    # Context the client reports — where the member was. Optional: feedback can come
    # from a page with no active tab, or before any ranking exists.
    route: str | None = Field(default=None, max_length=500)
    active_tab: str | None = Field(default=None, max_length=100)
    analysis_id: int | None = None


class FeedbackOut(ResponseModel):
    id: int
    body: str
    # Who submitted it — email + name so the admin can follow up without a lookup.
    user_email: str
    user_name: str
    route: str | None
    active_tab: str | None
    analysis_id: int | None
    app_version: str
    created_at: datetime
    resolved_at: datetime | None


class FeedbackListResponse(ResponseModel):
    items: list[FeedbackOut]
