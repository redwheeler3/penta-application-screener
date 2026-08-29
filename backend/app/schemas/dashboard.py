"""Response shape for the dashboard router.

The status/source maps and the coverage map are keyed by enum *values* (data, e.g.
``"untouched"``, ``"eligible"``) — those stay as plain dicts, untouched by the
alias generator, which only renames declared field names.
"""

from datetime import date, datetime

from app.db.models import EmailDeliveryState
from app.schemas.base import ResponseModel


class WorkflowState(ResponseModel):
    applications_available: bool
    screened: bool
    patterns_discovered: bool
    candidates_scored: bool
    ranking_current: bool


class CoverageEntry(ResponseModel):
    cached: int
    in_scope: int


class OpeningSelectionAction(ResponseModel):
    opening_id: int
    unit_size_bedrooms: int
    move_in_date: date


class AdminActions(ResponseModel):
    archived_openings_needing_selection: list[OpeningSelectionAction]
    queued_email_count: int
    quota_blocked_email_count: int
    recent_failed_email_count: int
    oldest_queued_email_at: datetime | None
    newest_queued_email_at: datetime | None
    last_email_attempt_at: datetime | None


class EmailDeliveryIssueOut(ResponseModel):
    id: int
    recipient_email: str
    message_kind: str
    state: EmailDeliveryState
    attempted_at: datetime
    attempt_count: int
    error_code: str | None
    quota_blocked: bool


class EmailDeliveryIssuesResponse(ResponseModel):
    items: list[EmailDeliveryIssueOut]


class DashboardResponse(ResponseModel):
    workflow: WorkflowState
    # Per-AI-step coverage; keys absent for steps not yet computable.
    coverage: dict[str, CoverageEntry]
    admin_actions: AdminActions | None = None
