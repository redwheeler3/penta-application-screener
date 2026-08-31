"""RFC 9457 (problem+json) error contract — one machine-readable error shape.

Every error the API raises is a ``Problem``: a stable ``code`` (the registry key),
an HTTP ``status``, a human ``title``, an optional per-instance ``detail``, and
optional extension members (e.g. ``capUsd``). The handlers in ``app.main`` render
it as ``application/problem+json``:

    {"type": "/problems/cap-exceeded", "title": "Spending cap exceeded",
     "status": 402, "detail": "...", "instance": "/ranking/run",
     "capUsd": 1.0, "estimatedUsd": 1.35}

``type`` is a relative slug derived from ``code`` — a stable identifier, not a live
URL (no doc to host for a first-party SPA). The frontend branches on ``code``.

The single contract keeps error handling consistent across the API surface.
"""

from __future__ import annotations

from typing import Any

# Stable error catalogue: code → (HTTP status, human title). Codes are the wire
# contract the frontend switches on; titles are the default human summary.
PROBLEM_TITLES: dict[str, tuple[int, str]] = {
    "unauthorized": (401, "Authentication required"),
    "invalid_magic_link": (401, "Sign-in link unavailable"),
    "email_delivery_failed": (503, "Email could not be sent"),
    "database_unavailable": (503, "Database unavailable"),
    "verified_email_required": (409, "Email verification required"),
    "email_unchanged": (400, "Email address unchanged"),
    "pending_draft_unavailable": (409, "Pending draft unavailable"),
    "application_already_exists": (409, "Application already exists"),
    "stale_application": (409, "Application changed elsewhere"),
    "declaration_required": (422, "Declaration acceptance required"),
    "applications_closed": (409, "Applications are closed"),
    "opening_selection_required": (409, "Choose an opening"),
    "opening_required": (409, "Choose an opening"),
    "opening_finalized": (409, "Opening outcome finalized"),
    "opening_archived": (409, "Opening is archived"),
    "opening_audience_changed": (409, "Notification audience changed"),
    "session_switch_required": (409, "Choose a committee account"),
    "forbidden": (403, "Admin access required"),
    "not_found": (404, "Resource not found"),
    "validation_error": (422, "Request validation failed"),
    "rate_limited": (429, "Too many requests"),
    "invalid_settings": (422, "Invalid settings"),
    "ai_provider_not_configured": (409, "AI provider not configured"),
    # Screening / ranking preconditions and gates.
    "no_eligible_applications": (409, "No eligible applications"),
    "run_required": (409, "Screening run required"),
    "stale_analysis": (409, "Ranking was refreshed"),
    "unchanged_pool": (409, "Screening already up to date"),
    "run_in_progress": (409, "Another run is in progress"),
    "cap_exceeded": (402, "Spending cap exceeded"),
    "unknown_dimension_key": (400, "Unknown dimension key"),
    "invalid_case": (422, "Invalid eval case"),
}


class Problem(Exception):
    """An API error, rendered to the client as problem+json by the app handlers.

    ``code`` must be a key in ``PROBLEM_TITLES``; the status and title default from
    the registry but ``status``/``title`` can override per raise. ``detail`` is the
    per-instance human message; ``extensions`` are extra top-level members
    (camelCase keys, e.g. ``cap_usd`` → pass as ``capUsd``).
    """

    def __init__(
        self,
        code: str,
        *,
        detail: str | None = None,
        status: int | None = None,
        title: str | None = None,
        **extensions: Any,
    ) -> None:
        default_status, default_title = PROBLEM_TITLES.get(
            code, (400, "Request failed")
        )
        self.code = code
        self.status = status if status is not None else default_status
        self.title = title if title is not None else default_title
        self.detail = detail
        self.extensions = extensions
        super().__init__(detail or self.title)

    def to_dict(self, *, instance: str) -> dict[str, Any]:
        """The problem+json body. ``instance`` is the request path that raised it."""
        body: dict[str, Any] = {
            "type": f"/problems/{self.code.replace('_', '-')}",
            "title": self.title,
            "status": self.status,
            "code": self.code,
            "instance": instance,
        }
        if self.detail is not None:
            body["detail"] = self.detail
        # Extension members sit at the top level alongside the standard fields.
        body.update(self.extensions)
        return body
