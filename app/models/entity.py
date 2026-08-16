"""Entity (schema definition) model."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin


class Entity(TimestampMixin, Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    icon: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    attributes: Mapped[list[Attribute]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
        order_by="Attribute.sort_order",
    )
    records: Mapped[list[Record]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


from app.models.attribute import Attribute  # noqa: E402  (resolves forward reference)
from app.models.record import Record  # noqa: E402  (resolves forward reference)
