"""Business logic for records: dynamic validation, CRUD, and display."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.attribute import Attribute
from app.models.entity import Entity
from app.models.enums import DataType
from app.models.mixins import utcnow
from app.models.record import Record
from app.models.user import User
from app.services.validation import ValidationError, coerce_value


class RecordError(ValueError):
    """Raised for invalid record data."""


def active_attributes(attributes: list[Attribute]) -> list[Attribute]:
    """Return the attributes shown on (and validated for) record forms."""
    return [a for a in attributes if a.is_active]


def username_map(db: Session) -> dict[int, str]:
    """Map user id -> username for attribution display."""
    return {u.id: u.username for u in db.execute(select(User)).scalars()}


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


def list_records(db: Session, entity_id: int) -> list[Record]:
    return list(
        db.execute(
            select(Record)
            .where(Record.entity_id == entity_id, Record.deleted_at.is_(None))
            .order_by(Record.id.desc())
        ).scalars()
    )


def get_record(db: Session, record_id: int) -> Record | None:
    return db.get(Record, record_id)


def create_record(
    db: Session,
    entity: Entity,
    attributes: list[Attribute],
    raw: dict[str, Any],
    user_id: int | None = None,
) -> Record:
    data, errors = validate_record_data(db, active_attributes(attributes), raw)
    if errors:
        raise RecordError("; ".join(errors))
    record = Record(entity_id=entity.id, data=data, created_by=user_id, updated_by=user_id)
    db.add(record)
    db.commit()
    return record


def update_record(
    db: Session,
    record: Record,
    attributes: list[Attribute],
    raw: dict[str, Any],
    user_id: int | None = None,
) -> Record:
    data, errors = validate_record_data(
        db, active_attributes(attributes), raw, exclude_record_id=record.id
    )
    if errors:
        raise RecordError("; ".join(errors))
    # Preserve values for inactive attributes (not submitted from the form).
    inactive_slugs = {a.slug for a in attributes if not a.is_active}
    merged = {slug: record.data[slug] for slug in inactive_slugs if slug in record.data}
    merged.update(data)
    record.data = merged
    record.updated_by = user_id
    db.commit()
    return record


def soft_delete_record(db: Session, record: Record) -> None:
    record.deleted_at = utcnow()
    db.commit()


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def validate_record_data(
    db: Session,
    attributes: list[Attribute],
    raw: dict[str, Any],
    exclude_record_id: int | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate raw form data against ``attributes``.

    Returns ``(canonical_data, errors)`` where ``canonical_data`` maps attribute
    slug -> canonical value. ``exclude_record_id`` skips one record in the
    uniqueness check (the record being edited).
    """
    unique_attrs = [a for a in attributes if a.is_unique]
    existing: list[Record] = []
    if unique_attrs:
        existing = list(
            db.execute(
                select(Record).where(
                    Record.entity_id == unique_attrs[0].entity_id,
                    Record.deleted_at.is_(None),
                )
            ).scalars()
        )

    data: dict[str, Any] = {}
    errors: list[str] = []
    for attr in attributes:
        raw_value = raw.get(attr.slug)
        try:
            value = coerce_attribute_value(attr, raw_value)
        except (ValidationError, ValueError) as exc:
            errors.append(f"{attr.name}: {exc}")
            continue

        if value is None or value == []:
            if attr.is_required:
                errors.append(f"{attr.name} is required.")
                continue
            if attr.default_value is not None:
                data[attr.slug] = attr.default_value
            continue

        if attr.is_unique and _duplicate_value(existing, attr, value, exclude_record_id):
            errors.append(f"{attr.name} must be unique.")
            continue

        data[attr.slug] = value
    return data, errors


def _duplicate_value(
    existing: list[Record],
    attr: Attribute,
    value: Any,
    exclude_record_id: int | None,
) -> bool:
    """True when another (non-excluded) record already holds this attribute value."""
    for other in existing:
        if exclude_record_id is not None and other.id == exclude_record_id:
            continue
        if other.data.get(attr.slug) == value:
            return True
    return False


def coerce_attribute_value(attr: Attribute, raw_value: Any) -> Any:
    """Coerce a raw value into canonical form for a single attribute."""
    if attr.data_type_enum == DataType.BOOLEAN and raw_value is None:
        # An unchecked checkbox submits nothing; treat it as False so a boolean
        # attribute always resolves to True or False, never "unset".
        return False
    if attr.data_type_enum == DataType.REFERENCE:
        return _coerce_reference(attr, raw_value)
    value = coerce_value(attr.data_type_enum, raw_value)
    if attr.data_type_enum == DataType.ENUM and value is not None:
        options = attr.config.get("options", [])
        if value not in options:
            raise ValidationError(f"'{value}' is not one of the allowed options.")
    return value


def best_effort_coerce(attributes: list[Attribute], raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce raw values for form re-rendering, preserving invalid input as-is."""
    current: dict[str, Any] = {}
    for attr in attributes:
        raw_value = raw.get(attr.slug)
        try:
            current[attr.slug] = coerce_attribute_value(attr, raw_value)
        except (ValidationError, ValueError):
            current[attr.slug] = raw_value
    return current


def _coerce_reference(attr: Attribute, raw_value: Any) -> Any:
    cardinality = attr.config.get("cardinality", "one")
    if cardinality == "many":
        if raw_value is None:
            return []
        items = raw_value if isinstance(raw_value, list) else [raw_value]
        result: list[int] = []
        for item in items:
            if item in (None, ""):
                continue
            try:
                result.append(int(item))
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"Invalid reference id {item!r}") from exc
        return result
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Invalid reference id {raw_value!r}") from exc


# --------------------------------------------------------------------------- #
# Display
# --------------------------------------------------------------------------- #


def title_attribute(attributes: list[Attribute]) -> Attribute | None:
    """Return the first text attribute, used as a record's display title."""
    for attr in attributes:
        if attr.data_type in (DataType.TEXT.value, DataType.TEXTAREA.value):
            return attr
    return None


def build_record_titles(db: Session, entity_id: int) -> dict[int, str]:
    """Map record_id -> display title for every non-deleted record of an entity."""
    entity = db.execute(
        select(Entity).options(selectinload(Entity.attributes)).where(Entity.id == entity_id)
    ).scalar_one_or_none()
    if entity is None:
        return {}
    title_attr = title_attribute(entity.attributes)
    titles: dict[int, str] = {}
    for record in list_records(db, entity_id):
        if title_attr is not None and record.data.get(title_attr.slug):
            titles[record.id] = str(record.data[title_attr.slug])
        else:
            titles[record.id] = f"#{record.id}"
    return titles


def format_value(value: Any) -> str:
    """Format a canonical value for display."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def resolve_reference_titles(db: Session, entity: Entity) -> dict[int, dict[int, str]]:
    """Map target_entity_id -> {record_id: title} for every reference attribute."""
    titles: dict[int, dict[int, str]] = {}
    for attr in entity.attributes:
        if attr.data_type == DataType.REFERENCE.value:
            target_id = attr.config.get("reference_entity_id")
            if target_id is not None and target_id not in titles:
                titles[target_id] = build_record_titles(db, target_id)
    return titles


def build_rows(
    entity: Entity,
    records: list[Record],
    titles: dict[int, dict[int, str]],
) -> list[dict[str, Any]]:
    """Build display rows: one dict per record with a ``cells`` slug->string map."""
    rows: list[dict[str, Any]] = []
    for record in records:
        cells: dict[str, str] = {}
        for attr in entity.attributes:
            cells[attr.slug] = _display_cell(attr, record.data.get(attr.slug), titles)
        rows.append({"record": record, "cells": cells})
    return rows


def _display_cell(attr: Attribute, value: Any, titles: dict[int, dict[int, str]]) -> str:
    if attr.data_type == DataType.REFERENCE.value:
        target_id = attr.config.get("reference_entity_id")
        cardinality = attr.config.get("cardinality", "one")
        target_titles = titles.get(target_id, {})
        if value is None:
            return "—"
        if cardinality == "many":
            ids = value if isinstance(value, list) else []
            return ", ".join(target_titles.get(i, f"#{i}") for i in ids) or "—"
        return target_titles.get(value, f"#{value}")
    return format_value(value)


def reference_options(db: Session, entity: Entity) -> dict[str, list[tuple[int, str]]]:
    """Return reference attribute slugs mapped to their target records as options."""
    options: dict[str, list[tuple[int, str]]] = {}
    for attr in entity.attributes:
        if attr.data_type == DataType.REFERENCE.value:
            target_id = attr.config.get("reference_entity_id")
            if target_id is not None:
                titles = build_record_titles(db, target_id)
                options[attr.slug] = sorted(titles.items(), key=lambda kv: str(kv[1]).lower())
    return options
