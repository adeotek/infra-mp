"""Tests for value coercion."""

import pytest

from app.models.enums import DataType
from app.services.validation import ValidationError, coerce_value


def test_text_coercion():
    assert coerce_value(DataType.TEXT, "hello") == "hello"
    assert coerce_value(DataType.TEXT, 123) == "123"


def test_empty_values_are_none():
    assert coerce_value(DataType.TEXT, "") is None
    assert coerce_value(DataType.TEXT, "   ") is None
    assert coerce_value(DataType.INTEGER, "") is None


def test_integer_coercion():
    assert coerce_value(DataType.INTEGER, "42") == 42
    assert coerce_value(DataType.INTEGER, 42) == 42
    with pytest.raises(ValidationError):
        coerce_value(DataType.INTEGER, "abc")


def test_integer_rejects_bool():
    with pytest.raises(ValidationError):
        coerce_value(DataType.INTEGER, True)


def test_decimal_coercion():
    # Canonical decimal storage is the exact string, never a float (no
    # binary-floating-point representation noise).
    assert coerce_value(DataType.DECIMAL, "3.14") == "3.14"
    assert coerce_value(DataType.DECIMAL, "0.1") == "0.1"
    assert coerce_value(DataType.DECIMAL, 2) == "2"
    with pytest.raises(ValidationError):
        coerce_value(DataType.DECIMAL, "not-a-number")


def test_boolean_coercion():
    assert coerce_value(DataType.BOOLEAN, "on") is True
    assert coerce_value(DataType.BOOLEAN, "false") is False
    assert coerce_value(DataType.BOOLEAN, True) is True
    assert coerce_value(DataType.BOOLEAN, "yes") is True
    assert coerce_value(DataType.BOOLEAN, "no") is False
    with pytest.raises(ValidationError):
        coerce_value(DataType.BOOLEAN, "maybe")


def test_date_coercion():
    assert coerce_value(DataType.DATE, "2024-01-15") == "2024-01-15"
    with pytest.raises(ValidationError):
        coerce_value(DataType.DATE, "15/01/2024")


def test_datetime_coercion():
    assert coerce_value(DataType.DATETIME, "2024-01-15T10:30:00") == "2024-01-15T10:30:00"
    with pytest.raises(ValidationError):
        coerce_value(DataType.DATETIME, "nope")


def test_enum_passthrough():
    assert coerce_value(DataType.ENUM, "active") == "active"


def test_decimal_accepts_finite_values():
    assert coerce_value(DataType.DECIMAL, "1.5") == "1.5"
    assert coerce_value(DataType.DECIMAL, "-0.25") == "-0.25"
    # Scientific notation stays finite and canonicalises through Decimal.
    assert coerce_value(DataType.DECIMAL, "1e3") == "1E+3"


@pytest.mark.parametrize("value", ["NaN", "nan", "Infinity", "-Infinity", "inf"])
def test_decimal_rejects_non_finite(value):
    # NaN/Infinity would store fine but crash every sorted view comparison.
    with pytest.raises(ValidationError):
        coerce_value(DataType.DECIMAL, value)
