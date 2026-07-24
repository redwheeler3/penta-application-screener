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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationStatus,
    MemberEligibility,
    MemberRules,
    StatusSource,
    User,
)
from app.domain.hard_filters import RulesConfig
from app.domain.status import effective_status
from app.schemas.settings import EligibilityRules
from app.services.rules import (
    committee_default_rules_config,
    hard_filter_reasons_for,
    rules_config_for,
    rules_config_from,
)


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
    else the computed machine verdict over the current findings (rule reasons evaluated
    under THIS member's rules)."""
    override = _member_override(db, user_id, application.id)
    flags = machine_flags_by_app(db, [application.id]).get(application.id)
    reasons = hard_filter_reasons_for(rules_config_for(db, user_id), application)
    return effective_status(
        override,
        has_reasons=bool(reasons),
        has_ai_flags=bool(flags),
    )


def eligible_application_ids_for(db: Session, user_id: int) -> set[int]:
    """The applications eligible in this member's OWN view — their overrides applied over
    the machine verdict computed under THIS member's rules. Drives the member's ranked list.
    One ruleset for the member, so one hard-filter evaluation per application."""
    applications = db.scalars(select(Application)).all()
    ids = [app.id for app in applications]
    flags_by_app = machine_flags_by_app(db, ids)
    rules_config = rules_config_for(db, user_id)
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
        reasons = hard_filter_reasons_for(rules_config, app)
        status, _ = effective_status(
            overrides.get(app.id),
            has_reasons=bool(reasons),
            has_ai_flags=bool(flags_by_app.get(app.id)),
        )
        if status == ApplicationStatus.ELIGIBLE:
            eligible.add(app.id)
    return eligible


def _ruleset_by_user(db: Session) -> tuple[dict[int, RulesConfig], RulesConfig]:
    """Each member's effective ``RulesConfig`` plus the shared committee default.

    Most members share the default (no ``MemberRules`` row); only diverged members carry
    their own. Because ``RulesConfig`` is a frozen dataclass, distinct rulesets collapse to
    the same key, so the union pass evaluates the hard filters once per distinct ruleset —
    not once per member.
    """
    default_config = committee_default_rules_config(db)
    ruleset_by_user: dict[int, RulesConfig] = {}
    diverged = {
        row.user_id: EligibilityRules.model_validate(row.rules)
        for row in db.scalars(select(MemberRules))
    }
    for user_id in db.scalars(select(User.id)):
        rules = diverged.get(user_id)
        ruleset_by_user[user_id] = (
            rules_config_from(rules) if rules is not None else default_config
        )
    return ruleset_by_user, default_config


def union_eligible_application_ids(db: Session) -> set[int]:
    """The UNION pool: every application eligible for AT LEAST ONE member.

    An application is eligible for member M iff M overrode it to ELIGIBLE, or M has no
    override and the machine verdict under M's OWN rules is ELIGIBLE (no rule reasons under
    M's thresholds AND no shared AI flags). So an application is in the union iff:

      - any member overrode it to ELIGIBLE, OR
      - it has no AI flags AND some member without an override finds it rules-clean under
        their ruleset (a machine-eligible view no one has overridden away).

    Rules diverge rarely, so this stays non-quadratic: it evaluates the hard filters once
    per (distinct ruleset × application) — for most members that is the single shared
    committee-default ruleset, computed once and reused. Overrides are sparse, so the
    per-app override bookkeeping is cheap set/counter work.
    """
    applications = db.scalars(select(Application)).all()
    ids = [app.id for app in applications]
    flags_by_app = machine_flags_by_app(db, ids)

    ruleset_by_user, _ = _ruleset_by_user(db)
    users_per_ruleset: dict[RulesConfig, int] = defaultdict(int)
    for rules_config in ruleset_by_user.values():
        users_per_ruleset[rules_config] += 1
    distinct_rulesets = list(users_per_ruleset)

    # Sparse per-app override bookkeeping: which apps some member flipped to ELIGIBLE, and
    # (per app) which members hold ANY override — those members don't fall through to the
    # machine-eligible path.
    has_eligible_override: set[int] = set()
    override_users_by_app: dict[int, set[int]] = defaultdict(set)
    for override in db.scalars(
        select(MemberEligibility).where(MemberEligibility.application_id.in_(ids))
    ):
        override_users_by_app[override.application_id].add(override.user_id)
        if override.status == ApplicationStatus.ELIGIBLE:
            has_eligible_override.add(override.application_id)

    union: set[int] = set()
    for app in applications:
        if app.id in has_eligible_override:
            union.add(app.id)
            continue
        # An AI flag makes the machine verdict INELIGIBLE for everyone regardless of rules,
        # so only an ELIGIBLE override (handled above) could put a flagged app in the union.
        if flags_by_app.get(app.id):
            continue
        # No flags: the app is machine-eligible for a member iff it is rules-clean under
        # that member's ruleset. It enters the union if any member WITHOUT an override on it
        # uses a ruleset that finds it clean.
        override_users = override_users_by_app.get(app.id, set())
        override_counts_by_ruleset: dict[RulesConfig, int] = defaultdict(int)
        for user_id in override_users:
            override_counts_by_ruleset[ruleset_by_user[user_id]] += 1
        for rules_config in distinct_rulesets:
            if hard_filter_reasons_for(rules_config, app):
                continue  # rules-ineligible under this ruleset
            available = (
                users_per_ruleset[rules_config]
                - override_counts_by_ruleset.get(rules_config, 0)
            )
            if available > 0:
                union.add(app.id)
                break
    return union
