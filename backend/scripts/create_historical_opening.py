"""Dry-run or create the one-time historical application-cycle opening."""

import argparse
from datetime import date

from app.db.session import SessionLocal
from app.services.historical_opening import (
    HistoricalOpeningDetails,
    HistoricalOpeningReport,
    create_historical_opening,
    inspect_historical_opening,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use an ISO date in YYYY-MM-DD format.") from error


def _print_report(report: HistoricalOpeningReport) -> None:
    details = report.details
    print("Historical opening preflight:")
    print(f"  unit size: {details.unit_size_bedrooms} bedroom(s)")
    print(f"  housing charge: {details.housing_charge_cents} cents")
    print(f"  application dates: {details.application_open_date} through {details.application_close_date}")
    print(f"  move-in date: {details.move_in_date}")
    print(f"  target applications: {report.target_application_count}")
    print(f"  existing target participations: {report.existing_target_participation_count}")
    print(f"  active vacancy subscriptions: {report.active_vacancy_subscription_count}")
    print(f"  consent receipts: {report.consent_receipt_count}")
    print(f"  queued emails: {report.queued_email_count}")
    print(f"  matching openings: {report.matching_opening_count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit-size-bedrooms", type=int, required=True, choices=(1, 2, 3))
    parser.add_argument("--housing-charge-cents", type=int, required=True)
    parser.add_argument("--application-open-date", type=_date, required=True)
    parser.add_argument("--application-close-date", type=_date, required=True)
    parser.add_argument("--move-in-date", type=_date, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--expected-application-count",
        type=int,
        help="Required with --apply; must exactly match the preflight target count.",
    )
    args = parser.parse_args()
    if args.apply and args.expected_application_count is None:
        parser.error("--apply requires --expected-application-count")
    if not args.apply and args.expected_application_count is not None:
        parser.error("--expected-application-count is valid only with --apply")

    details = HistoricalOpeningDetails(
        unit_size_bedrooms=args.unit_size_bedrooms,
        housing_charge_cents=args.housing_charge_cents,
        application_open_date=args.application_open_date,
        application_close_date=args.application_close_date,
        move_in_date=args.move_in_date,
    )
    with SessionLocal() as db:
        try:
            report = inspect_historical_opening(db, details)
        except ValueError as error:
            print(f"Preflight blocked: {error}")
            return 1
        _print_report(report)
        if not args.apply:
            print("Dry run only. Reconcile every count before applying.")
            return 0
        try:
            opening, after = create_historical_opening(
                db,
                details,
                expected_application_count=args.expected_application_count,
            )
            db.commit()
        except (ValueError, RuntimeError) as error:
            db.rollback()
            print(f"Apply blocked: {error}")
            return 1
        except Exception:
            db.rollback()
            raise
        print(
            f"Historical opening {opening.id} applied and verified: "
            f"{after.existing_target_participation_count} application(s) attached; "
            "notification counts unchanged."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
