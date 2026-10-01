"""Vacancy-notification subscription ownership and reporting."""

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.text import normalize_email
from app.core.time import PACIFIC, as_utc
from app.db.models import VacancySubscription

VALID_UNIT_SIZES = frozenset({1, 2, 3})


def save_subscription(
    db: Session,
    *,
    email: str,
    unit_sizes: set[int],
    source: str,
    consented_at: datetime | None = None,
    commit: bool = True,
) -> VacancySubscription:
    if not unit_sizes or not unit_sizes <= VALID_UNIT_SIZES:
        raise ValueError("Unit sizes must contain one or more of 1, 2, and 3.")
    normalized = normalize_email(email)
    now = consented_at or datetime.now(UTC)
    subscription = db.scalar(
        select(VacancySubscription).where(VacancySubscription.email == normalized)
    )
    if subscription is None:
        subscription = VacancySubscription(email=normalized, first_consented_at=now)
        db.add(subscription)
    subscription.wants_one_bedroom = 1 in unit_sizes
    subscription.wants_two_bedroom = 2 in unit_sizes
    subscription.wants_three_bedroom = 3 in unit_sizes
    subscription.consented_at = now
    subscription.source = source
    db.flush()
    if commit:
        db.commit()
        db.refresh(subscription)
    return subscription


def delete_subscription(db: Session, *, email: str) -> bool:
    subscription = find_subscription(db, email)
    if subscription is None:
        return False
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
    return list(
        db.scalars(
            select(VacancySubscription)
            .where(column.is_(True))
            .order_by(VacancySubscription.id)
        )
    )


def consume_subscription(db: Session, subscription_id: int) -> None:
    subscription = db.get(VacancySubscription, subscription_id)
    if subscription is None:
        return
    db.delete(subscription)


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
    public_signups = [row for row in rows if row.source == "public website"]
    months = Counter(
        as_utc(row.consented_at).astimezone(PACIFIC).strftime("%Y-%m") for row in rows
    )
    return {
        "total": len(rows),
        "one_bedroom": sum(row.wants_one_bedroom for row in rows),
        "two_bedroom": sum(row.wants_two_bedroom for row in rows),
        "three_bedroom": sum(row.wants_three_bedroom for row in rows),
        "latest_signup_at": max(
            (as_utc(row.consented_at) for row in public_signups),
            default=None,
        ),
        "months": [
            {"month": month, "count": months[month]} for month in sorted(months)
        ],
    }
