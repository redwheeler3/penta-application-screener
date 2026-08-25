from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Application,
    ApplicationParticipation,
    ApplicationVersion,
    Base,
    EmailDelivery,
    Opening,
)
from scripts import load_synthetic_applications as loader


def _database(tmp_path):
    database = tmp_path / "synthetic-loader.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session(engine) as db:
        openings = [
            Opening(
                unit_size_bedrooms=bedrooms,
                housing_charge_cents=100_000 + bedrooms,
                application_open_date=date(2026, 1, 1),
                application_close_date=date(2026, 12, 1),
                move_in_date=date(2027, 1, 1),
                published_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for bedrooms in (2, 3)
        ]
        db.add_all(openings)
        db.commit()
        return database, session_factory, [opening.id for opening in openings]


def test_loader_publishes_synthetic_applications_and_is_idempotent(
    tmp_path, monkeypatch
) -> None:
    database, session_factory, opening_ids = _database(tmp_path)
    monkeypatch.setattr(loader, "SessionLocal", session_factory)
    monkeypatch.setattr(
        loader,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=f"sqlite:///{database}",
            application_data_is_synthetic=True,
        ),
    )

    assert loader.load_fixture(opening_ids=opening_ids) == (100, 0)
    assert loader.load_fixture(opening_ids=opening_ids) == (0, 0)

    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Application)) == 100
        assert db.scalar(select(func.count()).select_from(ApplicationVersion)) == 100
        assert db.scalar(select(func.count()).select_from(ApplicationParticipation)) == 200
        assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 0
        assert all(db.scalars(select(Application.synthetic_data)))


def test_loader_fails_closed_without_synthetic_runtime(tmp_path, monkeypatch) -> None:
    database, session_factory, opening_ids = _database(tmp_path)
    monkeypatch.setattr(loader, "SessionLocal", session_factory)
    monkeypatch.setattr(
        loader,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=f"sqlite:///{database}",
            application_data_is_synthetic=False,
        ),
    )

    with pytest.raises(RuntimeError, match="APPLICATION_DATA_IS_SYNTHETIC=true"):
        loader.load_fixture(opening_ids=opening_ids)


def test_loader_refuses_to_replace_non_synthetic_application(tmp_path, monkeypatch) -> None:
    database, session_factory, opening_ids = _database(tmp_path)
    monkeypatch.setattr(loader, "SessionLocal", session_factory)
    monkeypatch.setattr(
        loader,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=f"sqlite:///{database}",
            application_data_is_synthetic=True,
        ),
    )

    first_record = next(loader.read_synthetic_fixture(loader.DEFAULT_FIXTURE))
    protected_email = str(first_record.answers.applicant.email).lower()
    with session_factory() as db:
        db.add(
            Application(
                primary_email=protected_email,
                applicant_name="Protected applicant",
                raw_row={"protected": True},
                raw_row_hash="protected-hash",
                normalized={},
                submitted_at=datetime(2026, 1, 2, tzinfo=UTC),
                synthetic_data=False,
            )
        )
        db.commit()

    with pytest.raises(RuntimeError, match="not stamped synthetic"):
        loader.load_fixture(opening_ids=opening_ids)

    with session_factory() as db:
        application = db.scalar(
            select(Application).where(Application.primary_email == protected_email)
        )
        assert application is not None
        assert application.raw_row == {"protected": True}
        assert db.scalar(select(func.count()).select_from(Application)) == 1
        assert db.scalar(select(func.count()).select_from(ApplicationVersion)) == 0
