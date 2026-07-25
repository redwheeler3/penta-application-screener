from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


if _is_sqlite:
    # Multi-member concurrency hardening (M16). SQLite serializes writers; without these,
    # two members' runs committing at once can raise "database is locked" immediately. Set
    # per connection (the pool opens several), on connect:
    #   - WAL: readers don't block the writer and vice versa, so a member browsing while
    #     another's run commits doesn't contend. Persists on the DB file once set.
    #   - busy_timeout: a writer that finds the lock held WAITS up to 5s (retrying) instead
    #     of failing instantly — turning almost every real collision into a brief wait. Runs
    #     commit per item (short locks), so 5s is ample headroom.
    # This makes concurrent writes SAFE on SQLite; a true hosted-grade concurrency story
    # (atomic shared budget, DB advisory locks) rides with the M17 hosting move.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

