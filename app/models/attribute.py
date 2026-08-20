"""Attribute (field definition) model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import DataType
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.entity import Entity


class Attribute(TimestampMixin, Base):
    __tablename__ = "attributes"
    __table_args__ = (UniqueConstraint("entity_id", "slug", name="uq_attribute_entity_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(128))
    data_type: Mapped[str] = mapped_column(String(32))
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    # Record values for this attribute must be unique across the entity's records.
    is_unique: Mapped[bool] = mapped_column(Boolean, default=False)
    # Part of the entity's key (single or composite, ordered by sort_order).
    # The key identifies records in reference selects and must be unique.
    is_key: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    hint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    entity: Mapped[Entity] = relationship(back_populates="attributes")

    @property
    def data_type_enum(self) -> DataType:
        return DataType(self.data_type)

    @property
    def options(self) -> list[str]:
        """Enum options, stored in ``config``."""
        return list(self.config.get("options", []))

    @property
    def reference_entity_id(self) -> int | None:
        """Reference target entity id, stored in ``config``."""
        return self.config.get("reference_entity_id")

    @property
    def cardinality(self) -> str:
        """Reference cardinality, stored in ``config``."""
        return self.config.get("cardinality", "one")
