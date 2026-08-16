"""Value coercion and validation for attribute data types."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.enums import DataType


class ValidationError(ValueError):
    """Raised when a value is invalid for its declared attribute type."""


def coerce_value(data_type: DataType, value: Any) -> Any:
    """Coerce ``value`` into the canonical form for ``data_type``.

    Returns ``None`` for empty values. Raises :class:`ValidationError` for
    values that cannot be represented as ``data_type``.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None

    if data_type in (DataType.TEXT, DataType.TEXTAREA):
        return str(value)

    if data_type == DataType.INTEGER:
        if isinstance(value, bool):
            raise ValidationError(f"Expected an integer, got {value!r}")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Expected an integer, got {value!r}") from exc

    if data_type == DataType.DECIMAL:
        try:
            return float(Decimal(str(value)))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"Expected a decimal number, got {value!r}") from exc

    if data_type == DataType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
        raise ValidationError(f"Expected a boolean, got {value!r}")

    if data_type == DataType.DATE:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValidationError(f"Expected a date (YYYY-MM-DD), got {value!r}") from exc

    if data_type == DataType.DATETIME:
        if isinstance(value, datetime):
            return value.isoformat()
        try:
            return datetime.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValidationError(f"Expected an ISO datetime, got {value!r}") from exc

    if data_type == DataType.ENUM:
        return str(value)

    if data_type == DataType.REFERENCE:
        # Validated against the attribute's config (cardinality, target entity)
        # by the caller.
        return value

    raise ValidationError(f"Unknown data type {data_type!r}")
