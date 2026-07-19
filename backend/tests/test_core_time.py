"""utc_isoformat: DB timestamps must serialize with a zone suffix.

Regression net for the "just now" bug — a naive UTC timestamp (what SQLite hands back from
``func.now()``) serialized without an offset is read as LOCAL by the browser, shifting a UTC
row into the future. The suffix is what stops that."""

from datetime import UTC, datetime, timedelta, timezone

from app.core.time import utc_isoformat


def test_none_passes_through():
    assert utc_isoformat(None) is None


def test_naive_is_stamped_utc():
    # A naive value (the SQLite case) gains a +00:00 suffix so the client parses it as UTC.
    out = utc_isoformat(datetime(2026, 7, 19, 7, 25, 34))
    assert out == "2026-07-19T07:25:34+00:00"


def test_aware_zone_is_preserved():
    aware = datetime(2026, 7, 19, 7, 25, 34, tzinfo=timezone(timedelta(hours=-5)))
    assert utc_isoformat(aware) == "2026-07-19T07:25:34-05:00"


def test_utc_aware_stays_utc():
    assert utc_isoformat(datetime(2026, 7, 19, 7, 25, 34, tzinfo=UTC)) == "2026-07-19T07:25:34+00:00"
