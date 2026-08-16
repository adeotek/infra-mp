"""User input schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import Role


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    display_name: str = Field(default="", max_length=128)
    role: Role = Role.VIEWER
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    display_name: str = Field(default="", max_length=128)
    role: Role = Role.VIEWER
    is_active: bool = True
    password: str | None = None
