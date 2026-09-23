"""Small, explicit database constructors shared by unit and integration tests."""

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base


def memory_engine(*, foreign_keys: bool = False) -> Engine:
    """Return an in-memory SQLite engine whose connections share one database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    if foreign_keys:
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine


def memory_session(*, foreign_keys: bool = False) -> Session:
    engine = memory_engine(foreign_keys=foreign_keys)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()
