"""Value coercion and validation for attribute data types."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from app.models.enums import DataType

# Global cap on text-ish values: the schema-as-data design stores record
# values in JSON, and unbounded strings from the form/CSV/MCP would bloat
# rows. 64k characters is far beyond any realistic inventory field.
MAX_TEXT_LENGTH = 65536


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

    if data_type in (DataType.TEXT, DataType.TEXTAREA, DataType.ENUM):
        text = str(value)
        if len(text) > MAX_TEXT_LENGTH:
            raise ValidationError(f"Value is too long (max {MAX_TEXT_LENGTH} characters).")
        return text

    if data_type == DataType.LINK:
        text = str(value)
        if len(text) > MAX_TEXT_LENGTH:
            raise ValidationError(f"Value is too long (max {MAX_TEXT_LENGTH} characters).")
        # Only absolute http(s) URLs are accepted: they are rendered as
        # target=_blank anchors, and scheme/netloc checks also block
        # javascript: URLs from ever reaching an href.
        parsed = urlparse(text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValidationError(f"Expected a valid http(s) URL, got {value!r}")
        return text

    if data_type == DataType.INTEGER:
        if isinstance(value, bool):
            raise ValidationError(f"Expected an integer, got {value!r}")
        if isinstance(value, float) and not float(value).is_integer():
            # JSON floats (MCP create/update) must not silently truncate:
            # int(2.7) == 2 corrupts the value without any error.
            raise ValidationError(f"Expected an integer, got {value!r}")
        try:
            if isinstance(value, Decimal) and value != value.to_integral_value():
                raise ValidationError(f"Expected an integer, got {value!r}")
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Expected an integer, got {value!r}") from exc

    if data_type == DataType.DECIMAL:
        try:
            # Store the canonical decimal *string*: round-tripping through
            # float introduces representation noise (0.1 + 0.2 == 0.3000...4).
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"Expected a decimal number, got {value!r}") from exc
        # NaN / Infinity serialise fine into JSON but cannot be ordered or
        # compared, so a single legacy row would crash every sorted view.
        # Reject non-finite values at the boundary.
        if not decimal_value.is_finite():
            raise ValidationError(f"Expected a finite decimal number, got {value!r}")
        return str(decimal_value)

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
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError as exc:
                raise ValidationError(f"Expected an ISO datetime, got {value!r}") from exc
        # The app convention is naive UTC (see AGENTS.md); aware input is
        # accepted but normalized by dropping the offset (wall-clock time).
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed.isoformat()

    if data_type == DataType.REFERENCE:
        # Validated against the attribute's config (cardinality, target entity)
        # by the caller.
        return value

    raise ValidationError(f"Unknown data type {data_type!r}")
