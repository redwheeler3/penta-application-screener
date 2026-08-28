"""Validate and optionally import a Google response-sheet CSV export."""

import argparse
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import VacancySubscription
from app.db.session import SessionLocal
from app.services.vacancy_import import parse_vacancy_csv
from app.services.vacancy_subscriptions import save_subscription


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-upsert", action="store_true")
    parser.add_argument("--email-column", default="Email Address")
    parser.add_argument(
        "--preferences-column",
        default="Please notify me when a unit of the following size is available",
    )
    parser.add_argument("--timestamp-column", default="Timestamp")
    args = parser.parse_args()

    result = parse_vacancy_csv(
        args.csv,
        email_column=args.email_column,
        preferences_column=args.preferences_column,
        timestamp_column=args.timestamp_column,
    )
    if result.errors:
        for error in result.errors:
            print(error)
        print(f"Import blocked with {len(result.errors)} error(s).")
        return 1

    counts = {
        size: sum(size in item.unit_sizes for item in result.subscriptions)
        for size in (1, 2, 3)
    }
    print(
        f"Validated {len(result.subscriptions)} unique subscriptions: "
        f"1BR={counts[1]}, 2BR={counts[2]}, 3BR={counts[3]}."
    )
    if not args.apply:
        print("Dry run only. Pass --apply to write the validated subscriptions.")
        return 0

    with SessionLocal() as db:
        existing = db.scalar(select(func.count()).select_from(VacancySubscription)) or 0
        if existing and not args.allow_upsert:
            print(
                f"Import blocked because {existing} active subscription(s) already exist. "
                "Reconcile them first or pass --allow-upsert deliberately."
            )
            return 1
        for item in result.subscriptions:
            save_subscription(
                db,
                email=item.email,
                unit_sizes=set(item.unit_sizes),
                source="Google response sheet import",
                consented_at=item.consented_at,
                commit=False,
            )
        db.commit()
    print("Import applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
