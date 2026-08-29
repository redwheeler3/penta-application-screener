"""Public signup and narrow administrator operations for vacancy notifications."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.problems import Problem
from app.core.time import as_utc
from app.db.models import User
from app.db.session import get_db
from app.legal import VACANCY_CONSENT_VERSION
from app.schemas.vacancy_subscriptions import (
    VacancySubscriptionAdminWrite,
    VacancySubscriptionDelete,
    VacancySubscriptionLookup,
    VacancySubscriptionLookupOut,
    VacancySubscriptionOut,
    VacancySubscriptionPublicOut,
    VacancySubscriptionPublicWrite,
    VacancySubscriptionReportOut,
)
from app.services.public_rate_limit import PublicRateLimiter
from app.services.vacancy_subscriptions import (
    VALID_UNIT_SIZES,
    delete_subscription,
    find_subscription,
    save_subscription,
    subscription_report,
    unit_sizes,
)

router = APIRouter(prefix="/vacancy-subscriptions", tags=["vacancy subscriptions"])
signup_limiter = PublicRateLimiter(limit=10, window=timedelta(minutes=15))


def _validate_unit_sizes(values: set[int]) -> None:
    if not values or not values <= VALID_UNIT_SIZES:
        raise Problem(
            "validation_error",
            detail="Choose one or more of the available unit sizes.",
        )


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("cf-connecting-ip")
    if forwarded:
        return forwarded.strip()
    return request.client.host if request.client is not None else "unknown"


def _out(subscription) -> VacancySubscriptionOut:
    return VacancySubscriptionOut(
        email=subscription.email,
        unit_sizes=unit_sizes(subscription),
        first_consented_at=as_utc(subscription.first_consented_at),
        consented_at=as_utc(subscription.consented_at),
        source=subscription.source,
    )


@router.post("", response_model=VacancySubscriptionPublicOut)
def subscribe(
    body: VacancySubscriptionPublicWrite,
    request: Request,
    db: Session = Depends(get_db),
) -> VacancySubscriptionPublicOut:
    _validate_unit_sizes(body.unit_sizes)
    if body.consent_version != VACANCY_CONSENT_VERSION:
        raise Problem(
            "validation_error",
            detail="Refresh the page before submitting this vacancy request.",
        )
    if not signup_limiter.allow(_client_key(request)):
        raise Problem(
            "rate_limited",
            detail="Too many signup attempts. Please wait a few minutes and try again.",
        )
    save_subscription(
        db,
        email=str(body.email),
        unit_sizes=body.unit_sizes,
        source="public website",
        consent_version=body.consent_version,
    )
    return VacancySubscriptionPublicOut()


@router.get("/report", response_model=VacancySubscriptionReportOut)
def report(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VacancySubscriptionReportOut:
    return VacancySubscriptionReportOut(**subscription_report(db))


@router.post("/admin/lookup", response_model=VacancySubscriptionLookupOut)
def lookup(
    body: VacancySubscriptionLookup,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VacancySubscriptionLookupOut:
    subscription = find_subscription(db, str(body.email))
    return VacancySubscriptionLookupOut(
        subscription=_out(subscription) if subscription is not None else None
    )


@router.put("/admin", response_model=VacancySubscriptionLookupOut)
def save_for_support(
    body: VacancySubscriptionAdminWrite,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VacancySubscriptionLookupOut:
    _validate_unit_sizes(body.unit_sizes)
    subscription = save_subscription(
        db,
        email=str(body.email),
        unit_sizes=body.unit_sizes,
        source=body.source,
        actor=admin,
    )
    return VacancySubscriptionLookupOut(subscription=_out(subscription))


@router.post("/admin/delete", response_model=VacancySubscriptionLookupOut)
def delete_for_support(
    body: VacancySubscriptionDelete,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VacancySubscriptionLookupOut:
    delete_subscription(
        db,
        email=str(body.email),
        source=body.source,
        actor=admin,
    )
    return VacancySubscriptionLookupOut(subscription=None)
