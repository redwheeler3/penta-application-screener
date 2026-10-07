"""Reserve one-time subscription consent independently of provider attempt leases."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.text import normalize_email
from app.core.time import as_utc, pacific_today
from app.db.models import (
    EmailDelivery,
    EmailDeliveryState,
    Opening,
    OpeningPhase,
    VacancySubscription,
)
from app.services.email.delivery import ATTEMPT_LEASE
from app.services.openings.catalog import opening_phase
from app.services.openings.subscriptions import unit_sizes
from app.services.openings.vacancy_notifications import notifiable_application


def reserve_subscription_consent(
    db: Session, delivery: EmailDelivery, subscription: VacancySubscription, *, now: datetime,
) -> bool:
    """The caller holds its attempt transaction until this reservation is committed.

    Retryable owners keep consent between attempts. A competing notice may claim it
    only when the existing owner is terminal, unavailable, or from another generation.
    No database writer is retained while the provider sends the prepared message.
    """
    generation = as_utc(subscription.consented_at).isoformat()
    owners = db.scalars(select(EmailDelivery).where(
        EmailDelivery.id != delivery.id,
        EmailDelivery.state == EmailDeliveryState.QUEUED,
        EmailDelivery.retry_intent["subscription_id"].as_integer() == subscription.id,
        EmailDelivery.retry_intent["subscription_consented_at"].as_string() == generation,
    ).execution_options(populate_existing=True)).all()
    for owner in owners:
        # The prepared message may already be in the provider's hands. A lifecycle
        # change cannot recall it or transfer its consent while that attempt is live.
        if (owner.last_error_code is None and owner.last_attempt_at is not None
            and as_utc(owner.last_attempt_at) > as_utc(now) - ATTEMPT_LEASE):
            return False
        intent = owner.retry_intent or {}
        opening = db.get(Opening, intent.get("opening_id"), populate_existing=True)
        available = (opening is not None and opening.published_at is not None
            and opening_phase(opening, today=pacific_today(now=now)) == OpeningPhase.OPEN
            and opening.unit_size_bedrooms in unit_sizes(subscription))
        if available and intent.get("type") == "application_opening":
            application = notifiable_application(db, owner.application_id, today=pacific_today(now=now))
            available = application is not None and normalize_email(application.primary_email) == subscription.email
        elif available:
            available = intent.get("type") == "vacancy_opening" and owner.recipient_email == subscription.email
        if available:
            return False
        # Release unavailable owners while acquiring the successor so a later
        # opening edit cannot revive two reservations for the same generation.
        owner.retry_intent = {key: value for key, value in intent.items() if key != "subscription_consented_at"}
    delivery.retry_intent = {**delivery.retry_intent, "subscription_consented_at": generation}
    return True
