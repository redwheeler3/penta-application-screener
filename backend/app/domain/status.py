"""Application status resolution — the single home for the eligibility model.

Eligibility (`eligible` / `ineligible`) is a **pure derivation**, computed on read, never
stored on the applicant. The *machine verdict* comes from the shared findings (deterministic
rule reasons + cached AI flags); a *member's human override* of that verdict lives in a
``MemberEligibility`` row. Effective status for a member = their override if present, else the
machine verdict. Machine actors (rules, AI) only refresh the underlying findings — they never
overwrite a member's override. See SPEC "Application Status Model" + M15 1c.
"""

from __future__ import annotations

import hashlib
import json

from app.db.models import ApplicationStatus, MemberEligibility, StatusSource


def resolve_machine_status(
    *, has_reasons: bool, has_ai_flags: bool
) -> tuple[ApplicationStatus, StatusSource]:
    """The status the machine assigns given the current findings — the shared baseline
    every member sees unless they override it.

    Rules take precedence over AI (high trust first); with neither, the application is
    clean and untouched.
    """
    if has_reasons:
        return ApplicationStatus.INELIGIBLE, StatusSource.RULES
    if has_ai_flags:
        return ApplicationStatus.INELIGIBLE, StatusSource.AI
    return ApplicationStatus.ELIGIBLE, StatusSource.UNTOUCHED


def effective_status(
    override: MemberEligibility | None, *, has_reasons: bool, has_ai_flags: bool
) -> tuple[ApplicationStatus, StatusSource]:
    """A member's effective (status, source) for an applicant: their human override if one
    exists, else the computed machine verdict. The single resolver every read path uses so
    "whose eligibility?" is answered one way."""
    if override is not None:
        return override.status, StatusSource.HUMAN
    return resolve_machine_status(has_reasons=has_reasons, has_ai_flags=has_ai_flags)


def findings_fingerprint(
    reasons: list[dict] | None, flags: list[dict] | None
) -> str:
    """Stable hash of the machine findings (reason codes + AI flag categories).

    Snapshotted when a member sets an override; a later mismatch means new findings
    have appeared since their review (staleness).
    """
    reason_codes = sorted((r.get("code") or "") for r in (reasons or []))
    flag_categories = sorted((f.get("category") or "") for f in (flags or []))
    basis = json.dumps(
        {"reasons": reason_codes, "flags": flag_categories}, sort_keys=True
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def override_is_stale(
    override: MemberEligibility | None,
    reasons: list[dict] | None,
    flags: list[dict] | None,
) -> bool:
    """True if machine findings changed since this member set their override. Only an
    override can be stale; a computed machine status always reflects the current findings.
    """
    if override is None:
        return False
    return findings_fingerprint(reasons, flags) != override.reviewed_fingerprint
