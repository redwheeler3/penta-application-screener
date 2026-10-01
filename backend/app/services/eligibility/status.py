"""Application status resolution — the single home for the eligibility model.

Eligibility (`eligible` / `ineligible`) is a **pure derivation**, computed on read, never
stored on the applicant. The *machine verdict* comes from the shared findings (deterministic
rule reasons + cached AI flags); a *member's human override* of that verdict lives in a
``MemberEligibility`` row. Effective status for a member = their override if present, else the
machine verdict. Machine actors (rules, AI) only refresh the underlying findings — they never
overwrite a member's override.
"""

from __future__ import annotations

import hashlib
import json

from app.db.models import ApplicationStatus, MemberEligibility, StatusSource
from app.domain.hard_filters import PETS_OVER_LIMIT_CODE


def _reason_codes(reasons: list[dict] | None) -> set[str]:
    return {r.get("code") for r in (reasons or []) if r.get("code")}


def resolve_machine_status(
    *, reasons: list[dict] | None, has_ai_flags: bool
) -> tuple[ApplicationStatus, StatusSource]:
    """The status the machine assigns given the current findings — the shared baseline
    every member sees unless they override it.

    Attribution follows when a finding becomes knowable:

      - a NON-pet deterministic reason (income/age/children/real-estate) comes directly from
        submitted form fields and is high-trust → ``RULES``;
      - otherwise a pet reason OR an AI flag → ``AI``. A pet verdict is deterministic math, but
        it needs the screening AI to first extract pet counts from the free-text pets field, so
        it can only land at Screen alongside the AI flags — it attributes to AI, not Rules.
      - neither → clean and ``UNTOUCHED``.

    A mixed income+pet ineligibility stays ``RULES``: the income reason alone made it
    ineligible from submitted fields alone, so Rules is the honest, higher-trust source. Only
    a pet-ONLY deterministic verdict moves to AI. Eligibility OUTCOME is unaffected either
    way (any reason or flag = ineligible) — this only sets which source badge the member sees.
    """
    codes = _reason_codes(reasons)
    if codes - {PETS_OVER_LIMIT_CODE}:  # any non-pet reason
        return ApplicationStatus.INELIGIBLE, StatusSource.RULES
    if PETS_OVER_LIMIT_CODE in codes or has_ai_flags:
        return ApplicationStatus.INELIGIBLE, StatusSource.AI
    return ApplicationStatus.ELIGIBLE, StatusSource.UNTOUCHED


def effective_status(
    override: MemberEligibility | None,
    *,
    reasons: list[dict] | None,
    has_ai_flags: bool,
) -> tuple[ApplicationStatus, StatusSource]:
    """A member's effective (status, source) for an applicant: their human override if one
    exists, else the computed machine verdict. The single resolver every read path uses so
    "whose eligibility?" is answered one way."""
    if override is not None:
        return override.status, StatusSource.HUMAN
    return resolve_machine_status(reasons=reasons, has_ai_flags=has_ai_flags)


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
