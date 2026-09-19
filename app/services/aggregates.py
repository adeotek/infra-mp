"""Numeric aggregation helpers shared by view grand totals and sum widgets."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.attribute import Attribute
from app.models.enums import DataType

# Attribute types that can be aggregated (sum/min/max/avg).
NUMERIC_DATA_TYPES = (DataType.INTEGER.value, DataType.DECIMAL.value)

# Grand-total operations offered per numeric view column.
TOTAL_OPS = ["sum", "avg", "min", "max"]

_TOTAL_OP_TITLES = {
    "sum": "Sum",
    "avg": "Average",
    "min": "Min",
    "max": "Max",
}


def total_op_title(op: str) -> str:
    return _TOTAL_OP_TITLES.get(op, op)


def is_numeric_attribute(attr: Attribute) -> bool:
    """True when the attribute's values can be aggregated."""
    return attr.data_type in NUMERIC_DATA_TYPES


def to_decimal(value: Any) -> Decimal | None:
    """Decimal view of a stored numeric value; ``None`` when it is not one.

    Booleans are not numbers here (``True`` would count as 1), and non-finite
    legacy values (NaN/Infinity) cannot be aggregated — both are skipped.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return decimal_value if decimal_value.is_finite() else None


def aggregate(values: list[Decimal], op: str) -> Decimal:
    """Aggregate a non-empty list of Decimals (``sum``/``avg``/``min``/``max``)."""
    if op == "sum":
        return sum(values, Decimal(0))
    if op == "avg":
        return sum(values, Decimal(0)) / Decimal(len(values))
    if op == "min":
        return min(values)
    if op == "max":
        return max(values)
    raise ValueError(f"Unknown total operation {op!r}")


def format_total(value: Decimal) -> str:
    """Format an aggregated value for display.

    Thousands separators, plain (never scientific) notation, and no trailing
    zeros: ``Decimal('1234.500') -> '1,234.5'``.
    """
    if value == value.to_integral_value():
        return f"{value.to_integral_value():,}"
    return format(value.normalize(), ",f")
