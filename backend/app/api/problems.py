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

This replaced ad-hoc ``HTTPException(detail="string")`` so there is exactly one
error format across the surface — the consistency the API redesign exists to land.
"""

from __future__ import annotations

from typing import Any

# Stable error catalogue: code → (HTTP status, human title). Codes are the wire
# contract the frontend switches on; titles are the default human summary.
PROBLEM_TITLES: dict[str, tuple[int, str]] = {
    "unauthorized": (401, "Authentication required"),
    "forbidden": (403, "Admin access required"),
    "not_found": (404, "Resource not found"),
    "validation_error": (422, "Request validation failed"),
    "invalid_settings": (422, "Invalid settings"),
    # Screening / ranking preconditions and gates.
    "no_eligible_applications": (409, "No eligible applications"),
    "run_required": (409, "Screening run required"),
    "unchanged_pool": (409, "Screening already up to date"),
    "cap_exceeded": (402, "Spending cap exceeded"),
    "unknown_dimension_key": (400, "Unknown dimension key"),
    "invalid_case": (422, "Invalid eval case"),
    # Sync / Google Sheets.
    "google_sheet_not_configured": (400, "No Google Sheet configured"),
    "google_credentials_expired": (401, "Google credentials expired"),
    "google_sheet_empty": (400, "Google Sheet returned no data"),
    "google_sheet_read_failed": (502, "Failed to read Google Sheet"),
    "import_failed": (500, "Application import failed"),
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
