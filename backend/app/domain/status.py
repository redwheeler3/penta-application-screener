"""Application status resolution — the single home for the status model rules.

Status (`eligible` / `ineligible`) is owned by whichever actor last acted, tracked
in `status_source`. Machine actors (rules, AI) never overwrite a human-set status;
they only refresh the underlying records. See SPEC "Application Status Model".
"""

from __future__ import annotations

import hashlib
import json

from app.db.models import Application, ApplicationStatus, StatusSource


def resolve_machine_status(
    *, has_reasons: bool, has_ai_flags: bool
) -> tuple[ApplicationStatus, StatusSource]:
    """The status a machine actor would assign, given the current findings.

    Rules take precedence over AI (high trust first); with neither, the
    application is clean and untouched.
    """
    if has_reasons:
        return ApplicationStatus.INELIGIBLE, StatusSource.RULES
    if has_ai_flags:
        return ApplicationStatus.INELIGIBLE, StatusSource.AI
    return ApplicationStatus.ELIGIBLE, StatusSource.UNTOUCHED


def apply_machine_status(
    application: Application, *, has_reasons: bool, has_ai_flags: bool
) -> None:
    """Set status from the machine findings, unless a human owns the decision.

    A human-set status is sticky: the caller still refreshes the reason/flag
    records, but the status itself is left untouched.
    """
    if application.status_source == StatusSource.HUMAN:
        return
    status, source = resolve_machine_status(
        has_reasons=has_reasons, has_ai_flags=has_ai_flags
    )
    application.status = status
    application.status_source = source


def findings_fingerprint(
    reasons: list[dict] | None, flags: list[dict] | None
) -> str:
    """Stable hash of the machine findings (reason codes + AI flag categories).

    Snapshotted when a human sets the status; a later mismatch means new findings
    have appeared since their review (staleness).
    """
    reason_codes = sorted((r.get("code") or "") for r in (reasons or []))
    flag_categories = sorted((f.get("category") or "") for f in (flags or []))
    basis = json.dumps(
        {"reasons": reason_codes, "flags": flag_categories}, sort_keys=True
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def is_stale(application: Application, flags: list[dict] | None) -> bool:
    """True if machine findings changed since a human last reviewed.

    Only human-set statuses can be stale; machine-owned statuses always reflect
    the current findings.
    """
    if application.status_source != StatusSource.HUMAN:
        return False
    current = findings_fingerprint(application.hard_filter_reasons, flags)
    return current != application.reviewed_fingerprint
