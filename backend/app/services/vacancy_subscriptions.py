"""Vacancy-notification subscription ownership and reporting."""

from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.text import normalize_email
from app.db.models import User, VacancySubscription, VacancySubscriptionAudit

VALID_UNIT_SIZES = frozenset({1, 2, 3})


def save_subscription(
    db: Session,
    *,
    email: str,
    unit_sizes: set[int],
    source: str,
    actor: User | None = None,
    consented_at: datetime | None = None,
) -> VacancySubscription:
    if not unit_sizes or not unit_sizes <= VALID_UNIT_SIZES:
        raise ValueError("Unit sizes must contain one or more of 1, 2, and 3.")
    normalized = normalize_email(email)
    now = consented_at or datetime.now(UTC)
    subscription = db.scalar(
        select(VacancySubscription).where(VacancySubscription.email == normalized)
    )
    action = "replace" if subscription is not None else "add"
    if subscription is None:
        subscription = VacancySubscription(email=normalized)
        db.add(subscription)
    subscription.wants_one_bedroom = 1 in unit_sizes
    subscription.wants_two_bedroom = 2 in unit_sizes
    subscription.wants_three_bedroom = 3 in unit_sizes
    subscription.consented_at = now
    subscription.source = source
    subscription.managed_by_user_id = actor.id if actor is not None else None
    db.flush()
    if actor is not None:
        _audit(db, subscription, action=action, source=source, actor=actor, now=now)
    db.commit()
    db.refresh(subscription)
    return subscription


def delete_subscription(
    db: Session, *, email: str, source: str, actor: User, now: datetime | None = None
) -> bool:
    subscription = find_subscription(db, email)
    if subscription is None:
        return False
    acted_at = now or datetime.now(UTC)
    _audit(db, subscription, action="delete", source=source, actor=actor, now=acted_at)
    db.delete(subscription)
    db.commit()
    return True


def find_subscription(db: Session, email: str) -> VacancySubscription | None:
    return db.scalar(
        select(VacancySubscription).where(
            VacancySubscription.email == normalize_email(email)
        )
    )


def matching_subscriptions(db: Session, unit_size: int) -> list[VacancySubscription]:
    column = {
        1: VacancySubscription.wants_one_bedroom,
        2: VacancySubscription.wants_two_bedroom,
        3: VacancySubscription.wants_three_bedroom,
    }[unit_size]
    return list(db.scalars(select(VacancySubscription).where(column.is_(True)).order_by(VacancySubscription.id)))


def consume_subscription(db: Session, subscription_id: int) -> None:
    db.execute(delete(VacancySubscription).where(VacancySubscription.id == subscription_id))
    db.commit()


def unit_sizes(subscription: VacancySubscription) -> list[int]:
    return [
        size
        for size, selected in (
            (1, subscription.wants_one_bedroom),
            (2, subscription.wants_two_bedroom),
            (3, subscription.wants_three_bedroom),
        )
        if selected
    ]


def subscription_report(db: Session) -> dict[str, object]:
    rows = list(db.scalars(select(VacancySubscription)))
    months = db.execute(
        select(
            func.strftime("%Y-%m", VacancySubscription.consented_at).label("month"),
            func.count(VacancySubscription.id),
        )
        .group_by("month")
        .order_by("month")
    ).all()
    return {
        "total": len(rows),
        "one_bedroom": sum(row.wants_one_bedroom for row in rows),
        "two_bedroom": sum(row.wants_two_bedroom for row in rows),
        "three_bedroom": sum(row.wants_three_bedroom for row in rows),
        "months": [{"month": month, "count": count} for month, count in months],
    }


def _audit(
    db: Session,
    subscription: VacancySubscription,
    *,
    action: str,
    source: str,
    actor: User,
    now: datetime,
) -> None:
    db.add(
        VacancySubscriptionAudit(
            subscription_id=subscription.id,
            email_hash=sha256(subscription.email.encode()).hexdigest(),
            action=action,
            source=source,
            acted_by_user_id=actor.id,
            acted_at=now,
        )
    )
