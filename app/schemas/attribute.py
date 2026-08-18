"""Attribute input schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import DataType


class AttributeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    data_type: DataType
    is_required: bool = False
    # Record values must be unique across the entity's records.
    is_unique: bool = False
    default_value: Any | None = None
    # Help text shown under the field on record add/edit forms.
    hint: str | None = None
    # Inactive attributes are hidden from the record add/edit forms.
    is_active: bool = True
    # Enum-specific: the list of allowed values.
    options: list[str] | None = None
    # Reference-specific: the target entity and relationship cardinality.
    reference_entity_id: int | None = None
    cardinality: Literal["one", "many"] = "one"


class AttributeUpdate(AttributeCreate):
    # Only editable while the entity has no records (values are keyed by slug).
    slug: str | None = None
