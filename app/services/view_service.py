"""Business logic for saved views: filtering, sorting, and CRUD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.attribute import Attribute
from app.models.entity import Entity
from app.models.enums import DataType
from app.models.record import Record
from app.models.view import View
from app.services.record_service import (
    _display_cell,
    build_record_titles,
    format_value,
    list_records,
    resolve_reference_titles,
)
from app.services.schema_service import list_entities
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
    icon: str = "",
    user_id: int | None = None,
) -> View:
    view = View(
        entity_id=entity.id,
        name=name.strip(),
        slug=unique_slug(db, View, name.strip(), scope={"entity_id": entity.id}),
        config=config,
        icon=icon,
        created_by=user_id,
    )
    db.add(view)
    db.commit()
    return view


def update_view(db: Session, view: View, name: str, config: dict, icon: str = "") -> View:
    view.name = name.strip()
    view.config = config
    view.icon = icon
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
    entities: list[Entity] | None = None,
) -> tuple[list[Record], list[ViewColumn]]:
    """Filter and sort records; return ``(records, visible_columns)``.

    ``entities`` (all entities with their attributes loaded) is required to
    resolve related-entity columns; without it those columns are skipped.
    """
    attrs_by_slug = {a.slug: a for a in entity.attributes}
    filtered = _apply_filters(records, attrs_by_slug, config.get("filters", []))
    filtered = _apply_sort(filtered, attrs_by_slug, config.get("sort"))
    columns = _resolve_columns(entity, config.get("columns"), entities)
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


@dataclass(frozen=True)
class ViewColumn:
    """A resolved view column: a base attribute or a related-entity attribute."""

    key: str
    label: str
    attr: Attribute
    # Resolved hops for related columns (dir/ref/to/many/name/to_name); None for base.
    path: list[dict[str, Any]] | None = None

    @property
    def slug(self) -> str:
        """Compatibility alias (base columns key by attribute slug)."""
        return self.key


def parse_column_spec(value: str) -> str | dict | None:
    """Parse one encoded column value from the view form.

    ``base:<slug>`` -> the slug string; ``rel:<hops>→<attr>`` -> a related
    column spec where each hop is ``dir:ref:target_entity_id:many_choice``.
    Returns ``None`` for malformed values (the caller skips them).
    """
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith("base:"):
        slug = value[5:].strip()
        return slug or None
    if value.startswith("rel:"):
        try:
            path_str, attr = value[4:].split("→", 1)
        except ValueError:
            return None
        attr = attr.strip()
        hops: list[dict[str, Any]] = []
        for token in path_str.split("/"):
            parts = token.strip().split(":")
            if len(parts) != 4:
                return None
            direction, ref, target, many = parts
            if direction not in ("up", "down") or many not in ("first", "all"):
                return None
            try:
                target_id = int(target)
            except ValueError:
                return None
            if not ref:
                return None
            hops.append({"dir": direction, "ref": ref, "to": target_id, "many": many})
        if not hops or not attr:
            return None
        return {"path": hops, "attr": attr}
    return None


def _resolve_columns(
    entity: Entity,
    column_specs: list[Any] | None,
    entities: list[Entity] | None,
) -> list[ViewColumn]:
    by_slug = {a.slug: a for a in entity.attributes}
    if not column_specs:
        return _base_columns(entity)
    entities_by_id = {e.id: e for e in entities or []}
    resolved: list[ViewColumn] = []
    for spec in column_specs:
        if isinstance(spec, str):
            attr = by_slug.get(spec)
            if attr is not None:
                resolved.append(ViewColumn(key=attr.slug, label=attr.name, attr=attr))
        elif isinstance(spec, dict):
            column = _resolve_related_column(entity, spec, entities_by_id)
            if column is not None:
                resolved.append(column)
    return resolved or _base_columns(entity)


def _base_columns(entity: Entity) -> list[ViewColumn]:
    return [ViewColumn(key=a.slug, label=a.name, attr=a) for a in entity.attributes]


def _resolve_related_column(
    entity: Entity,
    spec: dict,
    entities_by_id: dict[int, Entity],
) -> ViewColumn | None:
    """Resolve a related-column spec against the reference graph; None if invalid."""
    hops_spec = spec.get("path")
    if not isinstance(hops_spec, list) or not hops_spec:
        return None
    current = entity
    resolved_hops: list[dict[str, Any]] = []
    for hop in hops_spec:
        if not isinstance(hop, dict):
            return None
        direction = hop.get("dir")
        ref = hop.get("ref")
        to_id = hop.get("to")
        many = hop.get("many")
        if direction not in ("up", "down") or many not in ("first", "all"):
            return None
        if not isinstance(ref, str) or not isinstance(to_id, int):
            return None
        if direction == "up":
            attr = {a.slug: a for a in current.attributes}.get(ref)
            if attr is None or attr.data_type != DataType.REFERENCE.value:
                return None
            if attr.reference_entity_id != to_id:
                return None
            target = entities_by_id.get(to_id)
            if target is None:
                return None
            resolved_hops.append(
                {
                    "dir": "up",
                    "ref": ref,
                    "to": to_id,
                    "many": many,
                    "name": attr.name,
                    "to_name": target.name,
                }
            )
            current = target
        else:
            child = entities_by_id.get(to_id)
            if child is None:
                return None
            attr = {a.slug: a for a in child.attributes}.get(ref)
            if attr is None or attr.data_type != DataType.REFERENCE.value:
                return None
            if attr.reference_entity_id != current.id:
                return None
            resolved_hops.append(
                {
                    "dir": "down",
                    "ref": ref,
                    "to": to_id,
                    "many": many,
                    "name": attr.name,
                    "to_name": child.name,
                }
            )
            current = child
    terminal = spec.get("attr")
    if not isinstance(terminal, str):
        return None
    attr = {a.slug: a for a in current.attributes}.get(terminal)
    if attr is None:
        return None
    key = (
        "rel:"
        + "/".join(f"{h['dir']}:{h['ref']}:{h['to']}:{h['many']}" for h in resolved_hops)
        + "→"
        + attr.slug
    )
    label = " › ".join([h["name"] for h in resolved_hops] + [attr.name])
    return ViewColumn(key=key, label=label, attr=attr, path=resolved_hops)


# --------------------------------------------------------------------------- #
# Reference graph (for the view form) and related-column rendering
# --------------------------------------------------------------------------- #


def build_view_graph(db: Session, base_entity_id: int) -> dict:
    """Build a JSON-ready map of entities and their reference hops for the form."""
    entities = list_entities(db)
    nodes: dict[int, dict[str, Any]] = {}
    refs_by_target: dict[int, list[tuple[Entity, Attribute]]] = {}
    for entity in entities:
        attrs = []
        up = []
        for attr in entity.attributes:
            attrs.append({"slug": attr.slug, "name": attr.name})
            if attr.data_type == DataType.REFERENCE.value and attr.reference_entity_id is not None:
                up.append(
                    {
                        "ref": attr.slug,
                        "name": attr.name,
                        "to": attr.reference_entity_id,
                        "many": attr.cardinality == "many",
                    }
                )
                refs_by_target.setdefault(attr.reference_entity_id, []).append((entity, attr))
        nodes[entity.id] = {"name": entity.name, "attrs": attrs, "up": up, "down": []}
    for target_id, pairs in refs_by_target.items():
        node = nodes.get(target_id)
        if node is None:
            continue
        node["down"] = [
            {"ref": a.slug, "name": a.name, "from": e.id, "many": a.cardinality == "many"}
            for e, a in pairs
        ]
    return {"base": base_entity_id, "entities": {str(eid): n for eid, n in nodes.items()}}


def build_view_rows(
    db: Session,
    entity: Entity,
    records: list[Record],
    columns: list[ViewColumn],
) -> list[dict[str, Any]]:
    """Build display rows for a view, resolving related-entity columns."""
    base_titles = resolve_reference_titles(db, entity)
    related = [c for c in columns if c.path is not None]

    entity_ids = {entity.id}
    for column in related:
        for hop in column.path or []:
            entity_ids.add(hop["to"])
    records_by_entity = {eid: {r.id: r for r in list_records(db, eid)} for eid in entity_ids}

    reverse_index: dict[tuple[int, str], dict[int, list[int]]] = {}
    for column in related:
        for hop in column.path or []:
            if hop["dir"] == "down":
                key = (hop["to"], hop["ref"])
                if key not in reverse_index:
                    reverse_index[key] = _build_reverse_index(
                        records_by_entity.get(hop["to"], {}), hop["ref"]
                    )

    terminal_titles: dict[int, dict[int, str]] = {}
    for column in related:
        attr = column.attr
        if attr.data_type == DataType.REFERENCE.value and attr.reference_entity_id is not None:
            target_id = attr.reference_entity_id
            if target_id not in terminal_titles:
                terminal_titles[target_id] = build_record_titles(db, target_id)

    rows: list[dict[str, Any]] = []
    for record in records:
        cells: dict[str, str] = {}
        for column in columns:
            if column.path is None:
                cells[column.key] = _display_cell(
                    column.attr, record.data.get(column.attr.slug), base_titles
                )
            else:
                cells[column.key] = _resolve_related_cell(
                    record, column, records_by_entity, reverse_index, terminal_titles
                )
        rows.append({"record": record, "cells": cells})
    return rows


def _build_reverse_index(records_by_id: dict[int, Record], ref: str) -> dict[int, list[int]]:
    """Map parent record id -> child record ids (ascending id = insertion order)."""
    index: dict[int, list[int]] = {}
    for record_id in sorted(records_by_id):
        value = records_by_id[record_id].data.get(ref)
        if value is None:
            continue
        ids = value if isinstance(value, list) else [value]
        for parent_id in ids:
            index.setdefault(parent_id, []).append(record_id)
    return index


def _resolve_related_cell(
    record: Record,
    column: ViewColumn,
    records_by_entity: dict[int, dict[int, Record]],
    reverse_index: dict[tuple[int, str], dict[int, list[int]]],
    terminal_titles: dict[int, dict[int, str]],
) -> str:
    """Walk the column's hop path from ``record`` and format the terminal value."""
    current: list[Record] = [record]
    for hop in column.path or []:
        reached: list[Record] = []
        for rec in current:
            reached.extend(_follow_hop(rec, hop, records_by_entity, reverse_index))
        current = reached
        if not current:
            return "—"

    attr = column.attr
    if attr.data_type == DataType.REFERENCE.value:
        titles = terminal_titles.get(attr.reference_entity_id or -1, {})
        parts: list[str] = []
        for rec in current:
            value = rec.data.get(attr.slug)
            if value is None:
                continue
            ids = value if isinstance(value, list) else [value]
            parts.extend(titles.get(i, f"#{i}") for i in ids)
        return ", ".join(parts) or "—"

    parts = []
    for rec in current:
        value = rec.data.get(attr.slug)
        if value is not None:
            parts.append(format_value(value))
    return ", ".join(parts) or "—"


def _follow_hop(
    record: Record,
    hop: dict[str, Any],
    records_by_entity: dict[int, dict[int, Record]],
    reverse_index: dict[tuple[int, str], dict[int, list[int]]],
) -> list[Record]:
    """Return the records reached by one hop (empty when the reference is missing)."""
    if hop["dir"] == "up":
        value = record.data.get(hop["ref"])
        if value is None:
            return []
        ids = value if isinstance(value, list) else [value]
    else:
        ids = reverse_index.get((hop["to"], hop["ref"]), {}).get(record.id, [])

    target_records = records_by_entity.get(hop["to"], {})
    if hop["many"] == "first":
        for record_id in ids:
            target = target_records.get(record_id)
            if target is not None:
                return [target]
        return []
    return [target_records[i] for i in ids if i in target_records]
