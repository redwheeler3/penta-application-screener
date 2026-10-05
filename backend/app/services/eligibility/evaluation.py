"""Per-member eligibility, computed on read.

Eligibility is never stored on the applicant. The *machine verdict* is derived from the
applicant's findings under each member's rules and enabled checks; a member's human
override lives in a ``MemberEligibility`` row. This module is the read side of that model: it loads a member's override, resolves
their effective status via ``app.services.eligibility.status``, and computes the two eligible sets the
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
    ApplicationStatus,
    MemberEligibility,
    MemberRules,
    User,
)
from app.domain.hard_filters import RulesConfig
from app.schemas.settings import EligibilityRules
from app.services.applications.scope import opening_ai_applications
from app.services.applications.screening_results import screening_findings_by_app
from app.services.eligibility.rules import (
    committee_default_rules_config,
    hard_filter_reasons_for,
    rules_config_for,
    rules_config_from,
)
from app.services.eligibility.status import effective_status


def active_flags(
    flags: list[dict[str, Any]] | None, disabled_checks: tuple[str, ...]
) -> list[dict[str, Any]] | None:
    """The flags that still count for a member — those whose category is not in the member's
    ``disabled_checks``. The flag analogue of how ``evaluate_hard_filters``
    drops disabled reason codes: a member can mute a screening check (fake_contact, …) so it
    neither shows nor gates for them. Callers pass a member's ``RulesConfig.disabled_checks``
    (the flat set spanning both reason codes and flag categories; the reason codes here are
    simply absent from any flag's category, so they no-op). Order preserved.

    ``None`` (no screening result yet — "unknown") passes through as ``None``, distinct from
    ``[]`` (screened, no active flags), so callers can still tell unscreened from clean."""
    if flags is None:
        return None
    if not disabled_checks:
        return list(flags)
    muted = set(disabled_checks)
    return [f for f in flags if f.get("category") not in muted]


def overrides_by_app(
    db: Session, user_id: int, opening_id: int, application_ids: list[int]
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
                MemberEligibility.opening_id == opening_id,
                MemberEligibility.application_id.in_(application_ids),
            )
        )
    }


def eligible_application_ids_for(db: Session, user_id: int, opening_id: int) -> set[int]:
    """The applications eligible in this member's OWN view — their overrides applied over
    the machine verdict computed under THIS member's rules. Drives the member's ranked list.
    One ruleset for the member, so one hard-filter evaluation per application."""
    applications = opening_ai_applications(db, opening_id)
    ids = [app.id for app in applications]
    flags_by_app, facts_by_app = screening_findings_by_app(db, ids)
    rules_config = rules_config_for(db, user_id, opening_id)
    overrides = overrides_by_app(db, user_id, opening_id, ids)
    eligible: set[int] = set()
    for app in applications:
        reasons = hard_filter_reasons_for(
            rules_config,
            app,
            pet_facts=facts_by_app.get(app.id),
        )
        status, _ = effective_status(
            overrides.get(app.id),
            reasons=reasons,
            has_ai_flags=bool(active_flags(flags_by_app.get(app.id), rules_config.disabled_checks)),
        )
        if status == ApplicationStatus.ELIGIBLE:
            eligible.add(app.id)
    return eligible


def _ruleset_by_user(
    db: Session, opening_id: int
) -> tuple[dict[int, RulesConfig], RulesConfig]:
    """Each member's effective ``RulesConfig`` plus the shared committee default.

    Most members share the default (no ``MemberRules`` row); only diverged members carry
    their own. Because ``RulesConfig`` is a frozen dataclass, distinct rulesets collapse to
    the same key, so the union pass evaluates the hard filters once per distinct ruleset —
    not once per member.
    """
    default_config = committee_default_rules_config(db, opening_id)
    ruleset_by_user: dict[int, RulesConfig] = {}
    diverged = {
        row.user_id: EligibilityRules.model_validate(row.rules)
        for row in db.scalars(
            select(MemberRules).where(MemberRules.opening_id == opening_id)
        )
    }
    for user_id in db.scalars(select(User.id).where(User.is_active.is_(True))):
        rules = diverged.get(user_id)
        ruleset_by_user[user_id] = (
            rules_config_from(rules) if rules is not None else default_config
        )
    return ruleset_by_user, default_config


def rules_eligible_application_ids(db: Session, opening_id: int) -> set[int]:
    """Every application that is RULES-clean under at least one member's ruleset — the
    deterministic hard filters only, ignoring AI flags and pet facts.

    This is the pre-screen scope for the shared screening pass: it must be computable BEFORE
    any screening result exists, so (unlike ``union_eligible_application_ids``) it cannot fold
    in flags/pet-facts — those are what screening produces. It uses the union of every
    member's rules, so an applicant a diverged member finds
    rules-eligible still gets screened even if the committee default would exclude them.

    A slight superset of the post-screen union: it screens a few applicants who will later be
    flagged out — correct, since screening is exactly how those flags are discovered. Evaluates
    the hard filters once per distinct ruleset (rules diverge rarely), so non-quadratic.

    It ALSO includes any applicant a member forced ELIGIBLE via an override, even one the rules
    reject: overriding pulls an applicant into a member's active review pool, and that's exactly
    where the AI's flags/pet inventory/reasoning matter most. The override fixes their VERDICT,
    but the reviewer still wants the AI's evidence for fidelity on the application — so we screen
    them too, rather than leaving a forced-eligible applicant with no AI result behind them.
    """
    applications = opening_ai_applications(db, opening_id)
    ruleset_by_user, default_config = _ruleset_by_user(db, opening_id)
    # Always include the committee default: it's the shared baseline every member reads
    # unless they diverge, and it keeps the scope well-defined when there are no members
    # yet (an empty member set must not collapse the scope to nothing).
    distinct_rulesets = set(ruleset_by_user.values()) | {default_config}
    eligible: set[int] = set()
    for app in applications:
        # Rules-clean under ANY ruleset → in scope. No pet_facts passed: pets can't gate
        # pre-screen (their facts don't exist yet), same as the per-app screening gate.
        if any(
            not hard_filter_reasons_for(
                rules_config,
                app,
            )
            for rules_config in distinct_rulesets
        ):
            eligible.add(app.id)
    # Forced-eligible overrides: screen them for evidence even if the rules reject them.
    eligible |= set(
        db.scalars(
            select(MemberEligibility.application_id).where(
                MemberEligibility.status == ApplicationStatus.ELIGIBLE,
                MemberEligibility.user_id.in_(ruleset_by_user),
                MemberEligibility.opening_id == opening_id,
                MemberEligibility.application_id.in_([app.id for app in applications]),
            )
        )
    )
    return eligible


def union_eligible_application_ids(db: Session, opening_id: int) -> set[int]:
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
    applications = opening_ai_applications(db, opening_id)
    ids = [app.id for app in applications]
    flags_by_app, facts_by_app = screening_findings_by_app(db, ids)

    ruleset_by_user, _ = _ruleset_by_user(db, opening_id)
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
        select(MemberEligibility).where(
            MemberEligibility.opening_id == opening_id,
            MemberEligibility.user_id.in_(ruleset_by_user),
            MemberEligibility.application_id.in_(ids),
        )
    ):
        override_users_by_app[override.application_id].add(override.user_id)
        if override.status == ApplicationStatus.ELIGIBLE:
            has_eligible_override.add(override.application_id)

    union: set[int] = set()
    for app in applications:
        if app.id in has_eligible_override:
            union.add(app.id)
            continue
        # The app is machine-eligible for a member iff, under that member's ruleset, it has no
        # hard-filter reason AND no ACTIVE AI flag (a flag whose category the member hasn't
        # muted). Both halves are per-ruleset: disabled_checks is part of
        # RulesConfig, so members with different mutes are already distinct rulesets. The app
        # enters the union if any member without an override uses such a ruleset.
        override_users = override_users_by_app.get(app.id, set())
        override_counts_by_ruleset: dict[RulesConfig, int] = defaultdict(int)
        for user_id in override_users:
            override_counts_by_ruleset[ruleset_by_user[user_id]] += 1
        for rules_config in distinct_rulesets:
            if hard_filter_reasons_for(
                rules_config,
                app,
                pet_facts=facts_by_app.get(app.id),
            ):
                continue  # rules-ineligible under this ruleset
            if active_flags(flags_by_app.get(app.id), rules_config.disabled_checks):
                continue  # an un-muted AI flag makes it ineligible under this ruleset
            available = (
                users_per_ruleset[rules_config]
                - override_counts_by_ruleset.get(rules_config, 0)
            )
            if available > 0:
                union.add(app.id)
                break
    return union


def union_eligible_applications(db: Session, opening_id: int) -> list[Application]:
    """The UNION-eligible applications themselves (ordered by id) — the shared pool both
    pattern discovery and dimension scoring range over. Wraps
    ``union_eligible_application_ids`` so that "same scope" is one query, not a copy."""
    eligible_ids = union_eligible_application_ids(db, opening_id)
    return list(
        db.scalars(
            select(Application).where(Application.id.in_(eligible_ids)).order_by(Application.id)
        ).all()
    )
