"""Dashboard widget model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.view import View


class DashboardWidget(TimestampMixin, Base):
    __tablename__ = "dashboard_widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    # "table" renders a view's records; "count" renders a numeric stat.
    widget_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    view_id: Mapped[int | None] = mapped_column(
        ForeignKey("views.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Dashboard grid width: "1/4", "1/2", "3/4", or "full".
    width: Mapped[str] = mapped_column(String(16), default="1/2")
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    entity: Mapped[Entity | None] = relationship()
    view: Mapped[View | None] = relationship()
