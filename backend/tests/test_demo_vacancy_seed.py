import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.time import as_utc
from app.db.models import Base, VacancySubscription
from scripts import seed_demo_vacancy_subscriptions as seed


def _configure(monkeypatch, tmp_path, *, synthetic: bool = True):
    database = tmp_path / "demo-vacancy.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    monkeypatch.setattr(
        seed,
        "get_settings",
        lambda: Settings(
            database_url=f"sqlite:///{database}",
            application_data_is_synthetic=synthetic,
        ),
    )
    return session_factory


def test_seed_is_repeatable_and_preserves_distinct_first_consent(monkeypatch, tmp_path) -> None:
    session_factory = _configure(monkeypatch, tmp_path)

    assert seed.seed_demo_subscriptions() == 4
    assert seed.seed_demo_subscriptions() == 4

    with session_factory() as db:
        rows = list(db.scalars(select(VacancySubscription).order_by(VacancySubscription.email)))
    assert len(rows) == 4
    jeff = next(row for row in rows if row.email == "jeffo@jeffo.net")
    assert as_utc(jeff.first_consented_at) == seed.DEMO_SUBSCRIPTIONS[0].first_consented_at
    assert as_utc(jeff.consented_at) == seed.DEMO_SUBSCRIPTIONS[0].consented_at
    assert jeff.first_consented_at != jeff.consented_at
    assert all(row.source == seed.DEMO_SOURCE for row in rows)


def test_seed_refuses_a_non_demo_collision(monkeypatch, tmp_path) -> None:
    session_factory = _configure(monkeypatch, tmp_path)
    with session_factory() as db:
        db.add(
            VacancySubscription(
                email="jeffo@jeffo.net",
                wants_one_bedroom=True,
                wants_two_bedroom=False,
                wants_three_bedroom=False,
                first_consented_at=seed.DEMO_SUBSCRIPTIONS[0].first_consented_at,
                consented_at=seed.DEMO_SUBSCRIPTIONS[0].consented_at,
                source="Existing local record",
            )
        )
        db.commit()

    with pytest.raises(RuntimeError, match="non-demo"):
        seed.seed_demo_subscriptions()


def test_seed_requires_a_synthetic_database(monkeypatch, tmp_path) -> None:
    _configure(monkeypatch, tmp_path, synthetic=False)

    with pytest.raises(RuntimeError, match="APPLICATION_DATA_IS_SYNTHETIC=true"):
        seed.seed_demo_subscriptions()
