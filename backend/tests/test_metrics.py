from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.pricing import PassCost
from app.db.models import Base, User, UserRole
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
