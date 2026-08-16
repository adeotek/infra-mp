"""Shared model mixins and helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """Return the current time as a timezone-naive UTC datetime.

    SQLite has no native timezone support, so the app standardises on naive
    UTC everywhere to avoid aware/naive comparison bugs.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns managed by the ORM."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
