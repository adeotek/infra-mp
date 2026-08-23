"""Record (instance data) model.

Each record stores its attribute values as a JSON document, validated against
its entity's attribute schema at write time.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.entity import Entity


class Record(TimestampMixin, Base):
    __tablename__ = "records"
    # The hot path filters on (entity_id, deleted_at); cover both together.
    __table_args__ = (Index("ix_records_entity_deleted", "entity_id", "deleted_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    entity: Mapped[Entity] = relationship(back_populates="records")
