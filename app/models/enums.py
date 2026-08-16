"""Enums shared across the domain model."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Access levels for users."""

    ADMIN = "admin"
    MAINTAINER = "maintainer"
    VIEWER = "viewer"


class DataType(str, Enum):
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
