"""Enums shared across the domain model."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Access levels for users."""

    ADMIN = "admin"
    MAINTAINER = "maintainer"
    VIEWER = "viewer"


class DataType(StrEnum):
    """Attribute data types supported by the schema engine."""

    TEXT = "text"
    TEXTAREA = "textarea"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    ENUM = "enum"
    REFERENCE = "reference"
