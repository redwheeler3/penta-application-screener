from datetime import date

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.pricing import PassCost
from app.db.models import (
    Analysis,
    Base,
    Opening,
    RunCostLedger,
    RunPassCost,
    User,
    UserRole,
)
from app.services.cost_report import record_run_cost
from app.services.metrics import metrics_report
from tests.ranking_support import a_pattern_report


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


def test_dimensions_are_captured_run_facts_not_analysis_positions():
    db = make_session()
    report = a_pattern_report().model_dump(mode="json")
    failed = Analysis(dimension_report={**report, "dimensions": report["dimensions"][:1]})
    completed = Analysis(dimension_report=report)
    db.add_all([failed, completed])
    db.commit()
    record_run_cost(db, kind="rank", passes={}, dimension_count=2)
    # Later changes to the live analysis cannot rewrite historical run measurements.
    completed.dimension_report = {**report, "dimensions": []}
    db.commit()
    assert metrics_report(db).runs[0].dimensions == 2
    record_run_cost(db, kind="rank", passes={})
    assert metrics_report(db).runs[1].dimensions is None


def test_metrics_relationship_query_count_does_not_grow_per_run():
    db = make_session()
    user = User(email="synthetic@example.com", display_name="Synthetic Member", role=UserRole.MEMBER)
    opening = Opening(unit_size_bedrooms=2, housing_charge_cents=100000,
        application_open_date=date(2026, 8, 1), application_close_date=date(2026, 8, 31),
        move_in_date=date(2026, 9, 30))
    db.add_all([user, opening])
    db.flush()
    for _number in range(30):
        db.add(RunCostLedger(kind="rank", opening_id=opening.id, triggered_by_user_id=user.id,
            dimension_count=2, passes=[RunPassCost(label="Dimension scoring", calls=1, cost_usd=0.01)]))
    db.commit()
    engine = db.get_bind()
    queries = []

    def capture_sql(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)

    with Session(engine) as reader:
        event.listen(engine, "before_cursor_execute", capture_sql)
        try:
            report = metrics_report(reader)
        finally:
            event.remove(engine, "before_cursor_execute", capture_sql)
    assert len(queries) == 2
    assert len(report.runs) == 30
    assert all(run.dimensions == 2 and run.cost_usd == 0.01 for run in report.runs)
