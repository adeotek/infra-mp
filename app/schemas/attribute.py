"""Attribute input schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import DataType


class AttributeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    data_type: DataType
    is_required: bool = False
    default_value: Any | None = None
    # Enum-specific: the list of allowed values.
    options: list[str] | None = None
    # Reference-specific: the target entity and relationship cardinality.
    reference_entity_id: int | None = None
    cardinality: Literal["one", "many"] = "one"


class AttributeUpdate(AttributeCreate):
    pass
