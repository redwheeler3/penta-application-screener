"""Seed four fictional vacancy subscriptions into a synthetic local database.

Run from ``backend/``:

    python -m scripts.seed_demo_vacancy_subscriptions

The fixed dates make the monthly chart and first-versus-latest consent timestamps
repeatable. The seed sends no email and refuses non-synthetic or non-SQLite runtimes.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import VacancySubscription
from app.db.session import SessionLocal
from app.legal import VACANCY_CONSENT_VERSION
from app.services.vacancy_subscriptions import save_subscription

DEMO_SOURCE = "Local synthetic demo"


@dataclass(frozen=True)
class DemoSubscription:
    email: str
    unit_sizes: frozenset[int]
    first_consented_at: datetime
    consented_at: datetime


DEMO_SUBSCRIPTIONS = (
    DemoSubscription(
        email="jeffo@jeffo.net",
        unit_sizes=frozenset({1, 2, 3}),
        first_consented_at=datetime(2026, 5, 12, 18, tzinfo=UTC),
        consented_at=datetime(2026, 8, 29, 22, tzinfo=UTC),
    ),
    DemoSubscription(
        email="vacancy-one@jeffo.net",
        unit_sizes=frozenset({1}),
        first_consented_at=datetime(2026, 6, 8, 18, tzinfo=UTC),
        consented_at=datetime(2026, 6, 8, 18, tzinfo=UTC),
    ),
    DemoSubscription(
        email="vacancy-two@jeffo.net",
        unit_sizes=frozenset({2}),
        first_consented_at=datetime(2026, 7, 17, 18, tzinfo=UTC),
        consented_at=datetime(2026, 7, 17, 18, tzinfo=UTC),
    ),
    DemoSubscription(
        email="vacancy-family@jeffo.net",
        unit_sizes=frozenset({2, 3}),
        first_consented_at=datetime(2026, 8, 21, 18, tzinfo=UTC),
        consented_at=datetime(2026, 8, 21, 18, tzinfo=UTC),
    ),
)


def seed_demo_subscriptions() -> int:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        raise RuntimeError("Demo vacancy subscriptions may be seeded only into SQLite.")
    if not settings.application_data_is_synthetic:
        raise RuntimeError(
            "Set APPLICATION_DATA_IS_SYNTHETIC=true only for a wholly fictional local database."
        )

    target_emails = [item.email for item in DEMO_SUBSCRIPTIONS]
    with SessionLocal() as db:
        existing = {
            item.email: item
            for item in db.scalars(
                select(VacancySubscription).where(
                    VacancySubscription.email.in_(target_emails)
                )
            )
        }
        protected = [
            email
            for email, subscription in existing.items()
            if subscription.source != DEMO_SOURCE
        ]
        if protected:
            raise RuntimeError(
                "Refusing to replace non-demo vacancy subscription(s): "
                + ", ".join(sorted(protected))
            )

        for item in DEMO_SUBSCRIPTIONS:
            subscription = save_subscription(
                db,
                email=item.email,
                unit_sizes=set(item.unit_sizes),
                source=DEMO_SOURCE,
                consent_version=VACANCY_CONSENT_VERSION,
                consented_at=item.consented_at,
                commit=False,
            )
            subscription.first_consented_at = item.first_consented_at
        db.commit()
    return len(DEMO_SUBSCRIPTIONS)


def main() -> None:
    count = seed_demo_subscriptions()
    print(f"Seeded {count} local demo vacancy subscriptions. No email was sent.")


if __name__ == "__main__":
    main()
