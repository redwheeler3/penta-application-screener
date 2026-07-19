"""Timestamp serialization helpers.

Timestamps are written by ``func.now()`` (TimestampMixin) and, under SQLite, come back
NAIVE even though the column is ``DateTime(timezone=True)`` — the driver drops the zone. A
naive ``.isoformat()`` has no offset suffix, so a browser's ``new Date(iso)`` reads it as
LOCAL time and a UTC row lands in the future ("just now" forever). Stamp it UTC before
serializing so the wire string carries ``+00:00`` and the client parses it correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_isoformat(dt: datetime | None) -> str | None:
    """ISO-8601 for a DB timestamp, always zone-qualified. A naive value is assumed UTC (it
    came from ``func.now()``); an aware value is preserved. ``None`` in → ``None`` out."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()
