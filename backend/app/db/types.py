"""Custom column types.

SQLite has no native timezone support, so a ``DateTime(timezone=True)`` column
round-trips as a naive value. Comparing those with ``datetime.now(UTC)`` raises
``TypeError``. ``UTCDateTime`` normalises reads back to aware UTC datetimes so
application code can always use timezone-aware values, on SQLite and PostgreSQL
alike.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """``DateTime`` that always returns timezone-aware UTC datetimes."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # Treat naive input as UTC rather than guessing a local offset.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = ["UTCDateTime"]
