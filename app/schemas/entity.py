"""Entity input schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="", max_length=64)


class EntityUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="", max_length=64)
    # Only editable while the entity has no records (record URLs are keyed by slug).
    slug: str | None = None
