"""Saved view model."""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin


class View(TimestampMixin, Base):
    __tablename__ = "views"
    __table_args__ = (UniqueConstraint("entity_id", "slug", name="uq_view_entity_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(128))
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    # {"columns": ["slug", ...], "filters": [{"slug", "op", "value"}], "sort": {"slug", "dir"}}
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    entity: Mapped["Entity"] = relationship()
