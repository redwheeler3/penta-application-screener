"""Per-member eligibility, computed on read (M15 1c).

Eligibility is never stored on the applicant. The *machine verdict* is derived from the
applicant's shared findings (deterministic rule reasons + cached AI flags) and is the same
for everyone; a member's *human override* of that verdict lives in a ``MemberEligibility``
row. This module is the read side of that model: it loads a member's override, resolves
their effective status via ``app.domain.status``, and computes the two eligible sets the
ranking/discovery/scoring passes work over:

  - the UNION pool — every applicant eligible for at least one member (what the shared AI
    passes discover, score, and fingerprint over);
  - one member's own eligible view — the ranked list they see.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    MemberEligibility,
    StatusSource,
    User,
)
from app.domain.status import effective_status, resolve_machine_status


def machine_flags_by_app(
    db: Session, application_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """The latest screening flags per application, as ``{application_id: flag_list}``.

    Applications with no screening result are absent (so ``.get`` yields None). The flags
    are the AI half of the machine findings: an app "has AI flags" iff its flag list is
    non-empty. Batch-loaded in one query to keep the pool filters off the N+1 path.
    """
    if not application_ids:
        return {}
    latest: dict[int, list[dict[str, Any]]] = {}
    for result in db.scalars(
        select(ApplicationAIResult)
        .where(
            ApplicationAIResult.kind == "screening",
            ApplicationAIResult.application_id.in_(application_ids),
        )
        .order_by(ApplicationAIResult.created_at)
    ):
        latest[result.application_id] = (result.output or {}).get("flags", [])
    return latest


def overrides_by_app(
    db: Session, user_id: int, application_ids: list[int]
) -> dict[int, MemberEligibility]:
    """This member's overrides among ``application_ids``, as ``{application_id: override}``.
    Batch-loaded for a page of rows (one query), mirroring ``starred_ids``. Applications the
    member hasn't overridden are absent."""
    if not application_ids:
        return {}
    return {
        override.application_id: override
        for override in db.scalars(
            select(MemberEligibility).where(
                MemberEligibility.user_id == user_id,
                MemberEligibility.application_id.in_(application_ids),
            )
        )
    }


def _member_override(
    db: Session, user_id: int, application_id: int
) -> MemberEligibility | None:
    return db.scalar(
        select(MemberEligibility).where(
            MemberEligibility.application_id == application_id,
            MemberEligibility.user_id == user_id,
        )
    )


def effective_status_for(
    db: Session, user_id: int, application: Application
) -> tuple[ApplicationStatus, StatusSource]:
    """One member's effective (status, source) for an applicant: their override if any,
    else the computed machine verdict over the current findings."""
    override = _member_override(db, user_id, application.id)
    flags = machine_flags_by_app(db, [application.id]).get(application.id)
    return effective_status(
        override,
        has_reasons=bool(application.hard_filter_reasons),
        has_ai_flags=bool(flags),
    )


def eligible_application_ids_for(db: Session, user_id: int) -> set[int]:
    """The applications eligible in this member's OWN view — their overrides applied over
    the shared machine verdict. Drives the member's ranked list."""
    applications = db.scalars(select(Application)).all()
    ids = [app.id for app in applications]
    flags_by_app = machine_flags_by_app(db, ids)
    overrides = {
        override.application_id: override
        for override in db.scalars(
            select(MemberEligibility).where(
                MemberEligibility.user_id == user_id,
                MemberEligibility.application_id.in_(ids),
            )
        )
    }
    eligible: set[int] = set()
    for app in applications:
        status, _ = effective_status(
            overrides.get(app.id),
            has_reasons=bool(app.hard_filter_reasons),
            has_ai_flags=bool(flags_by_app.get(app.id)),
        )
        if status == ApplicationStatus.ELIGIBLE:
            eligible.add(app.id)
    return eligible


def union_eligible_application_ids(db: Session) -> set[int]:
    """The UNION pool: every application eligible for AT LEAST ONE member.

    An application is eligible for member M iff M overrode it to ELIGIBLE, or M has no
    override and the (shared) machine verdict is ELIGIBLE. Because the machine verdict is
    shared, an application is in the union iff:

      - any member overrode it to ELIGIBLE, OR
      - it is machine-eligible AND not *every* member overrode it to INELIGIBLE (someone
        without an ineligible override still sees the machine verdict).

    Written for N members though today there is one; the single-member case reduces to
    "machine-eligible, flipped by that member's override." One pass over the apps plus the
    overrides — no per-member re-query.
    """
    applications = db.scalars(select(Application)).all()
    ids = [app.id for app in applications]
    flags_by_app = machine_flags_by_app(db, ids)

    has_eligible_override: set[int] = set()
    ineligible_override_count: dict[int, int] = defaultdict(int)
    for override in db.scalars(
        select(MemberEligibility).where(MemberEligibility.application_id.in_(ids))
    ):
        if override.status == ApplicationStatus.ELIGIBLE:
            has_eligible_override.add(override.application_id)
        else:
            ineligible_override_count[override.application_id] += 1

    member_count = db.scalar(select(func.count()).select_from(User)) or 0

    union: set[int] = set()
    for app in applications:
        if app.id in has_eligible_override:
            union.add(app.id)
            continue
        machine_status, _ = resolve_machine_status(
            has_reasons=bool(app.hard_filter_reasons),
            has_ai_flags=bool(flags_by_app.get(app.id)),
        )
        if machine_status != ApplicationStatus.ELIGIBLE:
            continue
        # Machine-eligible: in the union unless every member overrode it to ineligible.
        all_members_rejected = (
            member_count > 0 and ineligible_override_count[app.id] >= member_count
        )
        if not all_members_rejected:
            union.add(app.id)
    return union
