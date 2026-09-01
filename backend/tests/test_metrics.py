from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.pricing import PassCost
from app.db.models import Base, Opening, User, UserRole
from app.services.cost_report import record_run_cost
from app.services.metrics import metrics_report


def make_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_metrics_report_includes_the_member_who_triggered_a_run() -> None:
    db = make_session()
    db.add(User(email="member@example.com", display_name="Committee Member", role=UserRole.MEMBER))
    db.commit()
    user = db.scalar(select(User))
    assert user is not None

    record_run_cost(
        db,
        kind="screen",
        passes={"Screening": PassCost(calls=1, cost_usd=0.01)},
        triggered_by_user_id=user.id,
    )

    report = metrics_report(db)

    assert report.runs[0].triggered_by == "member@example.com"


def test_metrics_report_uses_compact_opening_label() -> None:
    db = make_session()
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=100_000,
        application_open_date=date(2026, 8, 1),
        application_close_date=date(2026, 8, 31),
        move_in_date=date(2026, 9, 30),
    )
    db.add(opening)
    db.commit()

    record_run_cost(
        db,
        kind="screen",
        opening_id=opening.id,
        passes={"Screening": PassCost(calls=1, cost_usd=0.01)},
    )

    assert metrics_report(db).runs[0].opening == "2BR · Sep 30, 2026"
