"""Business logic for saved views: filtering, sorting, and CRUD."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.attribute import Attribute
from app.models.entity import Entity
from app.models.record import Record
from app.models.view import View
from app.services.slugs import unique_slug
from app.services.validation import ValidationError, coerce_value

FILTER_OPS = ["eq", "neq", "contains", "gt", "gte", "lt", "lte", "is_null", "not_null"]

_FILTER_OP_LABELS = {
    "eq": "equals",
    "neq": "does not equal",
    "contains": "contains",
    "gt": "greater than",
    "gte": "greater or equal",
    "lt": "less than",
    "lte": "less or equal",
    "is_null": "is empty",
    "not_null": "is not empty",
}


def filter_op_label(op: str) -> str:
    return _FILTER_OP_LABELS.get(op, op)


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


def list_views(db: Session) -> list[View]:
    return list(
        db.execute(select(View).options(selectinload(View.entity)).order_by(View.name)).scalars()
    )


def get_view(db: Session, view_id: int) -> View | None:
    return db.get(View, view_id)


def create_view(
    db: Session,
    entity: Entity,
    name: str,
    config: dict,
    user_id: int | None = None,
) -> View:
    view = View(
        entity_id=entity.id,
        name=name.strip(),
        slug=unique_slug(db, View, name.strip(), scope={"entity_id": entity.id}),
        config=config,
        created_by=user_id,
    )
    db.add(view)
    db.commit()
    return view


def update_view(db: Session, view: View, name: str, config: dict) -> View:
    view.name = name.strip()
    view.config = config
    db.commit()
    return view


def delete_view(db: Session, view: View) -> None:
    db.delete(view)
    db.commit()


# --------------------------------------------------------------------------- #
# Apply a view's config to a set of records
# --------------------------------------------------------------------------- #


def apply_config(
    entity: Entity,
    records: list[Record],
    config: dict,
) -> tuple[list[Record], list[Attribute]]:
    """Filter and sort records; return ``(records, visible_columns)``."""
    attrs_by_slug = {a.slug: a for a in entity.attributes}
    filtered = _apply_filters(records, attrs_by_slug, config.get("filters", []))
    filtered = _apply_sort(filtered, attrs_by_slug, config.get("sort"))
    columns = _resolve_columns(entity, config.get("columns"))
    return filtered, columns


def _apply_filters(
    records: list[Record],
    attrs_by_slug: dict[str, Attribute],
    filters: list[dict],
) -> list[Record]:
    result: list[Record] = []
    for record in records:
        if all(_match(record, attrs_by_slug, f) for f in filters):
            result.append(record)
    return result


def _match(record: Record, attrs_by_slug: dict[str, Attribute], spec: dict) -> bool:
    attr = attrs_by_slug.get(spec.get("slug") or "")
    if attr is None:
        return True  # unknown attribute -> no-op filter
    op = spec.get("op", "eq")
    raw_target = spec.get("value")
    value = record.data.get(attr.slug)

    if op == "is_null":
        return value is None
    if op == "not_null":
        return value is not None
    if value is None:
        return False

    if op == "contains" and isinstance(value, list):
        target = _coerce_filter_target(attr, raw_target)
        return target in value

    if op == "contains":
        return str(raw_target).lower() in str(value).lower()

    target = _coerce_filter_target(attr, raw_target)
    if op == "eq":
        return value == target
    if op == "neq":
        return value != target
    if op in ("gt", "gte", "lt", "lte"):
        try:
            if op == "gt":
                return value > target
            if op == "gte":
                return value >= target
            if op == "lt":
                return value < target
            if op == "lte":
                return value <= target
        except TypeError:
            return False
    return True


def _coerce_filter_target(attr: Attribute, raw_target: Any) -> Any:
    if raw_target is None:
        return None
    try:
        return coerce_value(attr.data_type_enum, raw_target)
    except ValidationError:
        return raw_target


def _apply_sort(
    records: list[Record],
    attrs_by_slug: dict[str, Attribute],
    sort_spec: dict | None,
) -> list[Record]:
    if not sort_spec:
        return records
    attr = attrs_by_slug.get(sort_spec.get("slug") or "")
    if attr is None:
        return records
    reverse = sort_spec.get("dir") == "desc"

    with_value = [r for r in records if r.data.get(attr.slug) is not None]
    without_value = [r for r in records if r.data.get(attr.slug) is None]
    with_value.sort(key=lambda r: _sortable(r.data[attr.slug]), reverse=reverse)
    return with_value + without_value


def _sortable(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, list):
        return str(value)
    return value


def _resolve_columns(entity: Entity, column_slugs: list[str] | None) -> list[Attribute]:
    if not column_slugs:
        return list(entity.attributes)
    by_slug = {a.slug: a for a in entity.attributes}
    columns = [by_slug[s] for s in column_slugs if s in by_slug]
    return columns or list(entity.attributes)
