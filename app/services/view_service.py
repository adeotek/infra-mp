"""Business logic for saved views: filtering, sorting, and CRUD."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.attribute import Attribute
from app.models.entity import Entity
from app.models.enums import DataType
from app.models.record import Record
from app.models.view import View
from app.services.aggregates import (
    TOTAL_OPS,
    aggregate,
    format_total,
    is_numeric_attribute,
    to_decimal,
)
from app.services.calculated import (
    CALC_KINDS,
    FormulaError,
    evaluate_formula,
    formula_references,
    parse_formula,
)
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

FILTER_OPS = [
    "eq",
    "neq",
    "contains",
    "not_contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "is_null",
    "not_null",
]

_FILTER_OP_LABELS = {
    "eq": "equals",
    "neq": "does not equal",
    "contains": "contains",
    "not_contains": "does not contain",
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
    db: Session | None = None,
    cache: dict | None = None,
) -> tuple[list[Record], list[ViewColumn]]:
    """Filter and sort records; return ``(records, visible_columns)``.

    ``entities`` (all entities with their attributes loaded) is required to
    resolve related-entity columns; without it those columns are skipped.
    ``db`` is required to filter/sort by a related column (its values live in
    other entities' records); without it related filters and sorts are skipped.
    ``cache`` is an optional per-request dict shared across render calls so
    referenced entities' records are loaded once, not per column.
    """
    attrs_by_slug = {a.slug: a for a in entity.attributes}
    columns = _resolve_columns(entity, config.get("columns"), entities)
    # Calculated columns are derived from the resolved columns, so they are
    # appended after them and share their keys/values.
    columns = _resolve_calculated_columns(columns, config.get("calculated"))
    filters = config.get("filters", [])
    entities_by_id = {e.id: e for e in entities or []}
    # The related context must cover filter columns too, not just the visible
    # view columns — otherwise filters on undisplayed related columns resolve
    # against an empty record set.
    context_columns = columns + _filter_columns(entity, filters, entities_by_id)
    context = (
        _related_context(db, entity, context_columns, records, cache) if db and filters else None
    )
    base_titles = resolve_reference_titles(db, entity, cache=cache) if db else {}
    filtered = _apply_filters(
        records,
        entity,
        attrs_by_slug,
        filters,
        columns,
        context,
        entities_by_id,
        base_titles,
        config.get("filter_op", "and"),
    )
    filtered = _apply_sort(filtered, entity, config.get("sort"), entities, db, cache)
    return filtered, columns


def _filter_columns(
    entity: Entity, filters: list[dict], entities_by_id: dict[int, Entity]
) -> list[ViewColumn]:
    """Resolved related columns referenced by filters (for the shared context)."""
    resolved = []
    for spec in filters:
        col = spec.get("col")
        if col is None:
            col = spec.get("slug")
        if isinstance(col, dict):
            column = _resolve_related_column(entity, col, entities_by_id)
            if column is not None:
                resolved.append(column)
    return resolved


def _apply_filters(
    records: list[Record],
    entity: Entity,
    attrs_by_slug: dict[str, Attribute],
    filters: list[dict],
    columns: list[ViewColumn],
    context: Any | None,
    entities_by_id: dict[int, Entity],
    base_titles: dict[int, dict[int, str]],
    filter_op: str = "and",
) -> list[Record]:
    """Apply filter specs; all rows are combined with the global ``filter_op``.

    Each spec is ``{"col": <"quick" | base slug | rel spec dict>, "op", "value"}``;
    legacy rows carry ``slug`` instead of ``col``. Unknown columns are no-ops.
    """
    if not filters:
        return records
    columns_by_key = {c.key: c for c in columns}
    resolved: list[tuple[dict, Any, ViewColumn | None]] = []
    for spec in filters:
        col = spec.get("col")
        if col is None:
            col = spec.get("slug")  # legacy: base attribute slug
        column = (
            _resolve_related_column(entity, col, entities_by_id) if isinstance(col, dict) else None
        )
        resolved.append((spec, col, column))

    def passes(record: Record) -> bool:
        outcomes = (
            _match(record, attrs_by_slug, spec, col, column, columns_by_key, context, base_titles)
            for spec, col, column in resolved
        )
        return all(outcomes) if filter_op != "or" else any(outcomes)

    return [record for record in records if passes(record)]


def _match(
    record: Record,
    attrs_by_slug: dict[str, Attribute],
    spec: dict,
    col: Any,
    column: ViewColumn | None,
    columns_by_key: dict[str, ViewColumn],
    context: Any | None,
    base_titles: dict[int, dict[int, str]],
) -> bool:
    op = spec.get("op", "eq")
    raw_target = spec.get("value")
    if raw_target is None:
        raw_target = ""
    if col == "quick":
        return _quick_match(
            record, attrs_by_slug, str(raw_target), columns_by_key, context, base_titles
        )
    if isinstance(col, str):
        attr = attrs_by_slug.get(col)
        if attr is None:
            return True  # unknown attribute -> no-op filter
        return _match_scalar(record.data.get(col), attr, raw_target, op, base_titles)
    if column is None or column.attr is None:
        return True  # unresolvable related column -> no-op filter
    if not context:
        return True  # no db context -> related filters are skipped
    values = _related_filter_values(record, column, context)
    if op == "is_null":
        return not values
    if op == "not_null":
        return bool(values)
    if not values:
        return False
    outcomes = [_match_scalar(v, column.attr, raw_target, op, base_titles) for v in values]
    # Positive ops match when ANY related value matches; negated ops (neq /
    # not_contains) require ALL values to fail so the row is excluded.
    if op in ("neq", "not_contains"):
        return all(outcomes)
    return any(outcomes)


def _match_scalar(
    value: Any,
    attr: Attribute,
    raw_target: Any,
    op: str,
    base_titles: dict[int, dict[int, str]],
) -> bool:
    if op == "is_null":
        return value is None
    if op == "not_null":
        return value is not None
    if value is None:
        return False

    # Reference values: match by numeric id or by record title.
    if attr.data_type == DataType.REFERENCE.value:
        return _match_reference(value, attr, raw_target, base_titles, op)

    if op in ("contains", "not_contains"):
        if isinstance(value, list):
            target = _coerce_filter_target(attr, raw_target)
            hit = any(_scalar_equal(attr, item, target) for item in value)
        else:
            hit = str(raw_target).casefold() in str(value).casefold()
        return hit if op == "contains" else not hit

    target = _coerce_filter_target(attr, raw_target)
    if op == "eq":
        return _scalar_equal(attr, value, target)
    if op == "neq":
        return not _scalar_equal(attr, value, target)
    if op in ("gt", "gte", "lt", "lte"):
        # Numeric attributes store canonical decimal *strings*, which must be
        # ordered by value ("4.50" is smaller than "10", not the reverse).
        if is_numeric_attribute(attr):
            left_decimal, right_decimal = to_decimal(value), to_decimal(target)
            if left_decimal is None or right_decimal is None:
                return False
            value, target = left_decimal, right_decimal
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


def _scalar_equal(attr: Attribute, left: Any, right: Any) -> bool:
    """Equality used by ``eq``/``neq`` filters and list membership.

    Text-like values compare case-insensitively — filters are typed by hand,
    so "Active" must match "active" (and enums accept any casing). Numeric
    attributes compare by value: decimals are stored as canonical strings, and
    "12.5" must match a filter target of "12.50".
    """
    if is_numeric_attribute(attr):
        left_decimal, right_decimal = to_decimal(left), to_decimal(right)
        if left_decimal is not None and right_decimal is not None:
            return left_decimal == right_decimal
    if isinstance(left, str) and isinstance(right, str):
        return left.casefold() == right.casefold()
    return left == right


def _related_filter_values(record: Record, column: ViewColumn, context: Any) -> list[Any]:
    """All terminal values of a related column (empty list when unresolved).

    Unlike the sort key (first value only), filters see every reached value,
    so a many-reference column matches when ANY of its values matches.
    """
    records_by_entity, reverse_index, terminal_titles = context
    current: list[Record] = [record]
    for hop in column.path or []:
        reached: list[Record] = []
        for rec in current:
            reached.extend(_follow_hop(rec, hop, records_by_entity, reverse_index))
        current = reached
        if not current:
            return []
    attr = column.attr
    if attr is None:
        return []
    values: list[Any] = []
    for rec in current:
        value = rec.data.get(attr.slug)
        if value is None:
            continue
        ids = value if isinstance(value, list) else [value]
        if attr.data_type == DataType.REFERENCE.value:
            titles = terminal_titles.get(attr.reference_entity_id or -1, {})
            values.extend(titles.get(i, f"#{i}") for i in ids)
        else:
            values.extend(ids)
    return values


def _match_reference(
    value: Any,
    attr: Attribute,
    raw_target: str,
    base_titles: dict[int, dict[int, str]],
    op: str,
) -> bool:
    """Match a reference value: numeric id comparison or (case-insensitive) title."""
    target = _coerce_filter_target(attr, raw_target)
    titles = base_titles.get(attr.config.get("reference_entity_id"), {})

    def title_of(item: Any) -> str:
        return titles.get(item, str(item))

    if op in ("eq", "neq"):
        if isinstance(target, int):
            hit = value == target
        else:
            hit = title_of(value).casefold() == str(raw_target).casefold()
        return hit if op == "eq" else not hit
    # contains / not_contains over the referenced title(s).
    if isinstance(value, list):
        hit = any(str(raw_target).casefold() in title_of(v).casefold() for v in value)
    else:
        hit = str(raw_target).casefold() in title_of(value).casefold()
    return hit if op == "contains" else not hit


def _quick_match(
    record: Record,
    attrs_by_slug: dict[str, Attribute],
    term: str,
    columns_by_key: dict[str, ViewColumn],
    context: Any | None,
    base_titles: dict[int, dict[int, str]],
) -> bool:
    """True when any cell (base attribute or related column) contains ``term``."""
    if not term:
        return True
    term = term.casefold()
    for slug, value in record.data.items():
        if value is None:
            continue
        attr = attrs_by_slug.get(slug)
        if attr is not None and attr.data_type == DataType.REFERENCE.value:
            titles = base_titles.get(attr.config.get("reference_entity_id"), {})
            if isinstance(value, list):
                hay = [titles.get(v, str(v)) for v in value]
            else:
                hay = [titles.get(value, str(value))]
        elif isinstance(value, list):
            hay = [str(v) for v in value]
        else:
            hay = [str(value)]
        if any(term in str(part).casefold() for part in hay):
            return True
    if context:
        for column in columns_by_key.values():
            if column.path is None:
                continue
            value = _resolve_related_sort_value(record, column, context)
            if value is None:
                continue
            hay = value if isinstance(value, list) else [value]
            if any(term in str(part).casefold() for part in hay):
                return True
    return False


def _coerce_filter_target(attr: Attribute, raw_target: Any) -> Any:
    if raw_target is None:
        return None
    try:
        return coerce_value(attr.data_type_enum, raw_target)
    except ValidationError:
        return raw_target


def _apply_sort(
    records: list[Record],
    entity: Entity,
    sort_spec: dict | None,
    entities: list[Entity] | None,
    db: Session | None,
    cache: dict | None = None,
) -> list[Record]:
    """Sort by any view column: base attribute (``sort.slug`` / ``sort.col``
    string, legacy compatible) or related column (``sort.col`` dict spec).
    Records without a value always go last, matching the legacy behaviour."""
    if not sort_spec:
        return records
    column_spec = sort_spec.get("col")
    if column_spec is None:
        column_spec = sort_spec.get("slug")  # legacy: base attribute slug
    if column_spec is None:
        return records

    if isinstance(column_spec, str):
        attr = {a.slug: a for a in entity.attributes}.get(column_spec)
        if attr is None:
            return records
        column = ViewColumn(key=attr.slug, label=attr.name, attr=attr)
    elif isinstance(column_spec, dict):
        column = _resolve_related_column(entity, column_spec, {e.id: e for e in entities or []})
        if column is None:
            return records
    else:
        return records

    reverse = sort_spec.get("dir") == "desc"
    if column.path is None:
        attr = column.attr
        if attr is None:
            return records
        with_value = [r for r in records if r.data.get(attr.slug) is not None]
        without_value = [r for r in records if r.data.get(attr.slug) is None]
        with_value.sort(key=lambda r: sort_value(r.data[attr.slug]), reverse=reverse)
        return with_value + without_value

    if db is None:
        return records  # related sort values live in other entities' records
    context = _related_context(db, entity, [column], records, cache)
    values = {r.id: _resolve_related_sort_value(r, column, context) for r in records}
    with_value = [r for r in records if values[r.id] is not None]
    without_value = [r for r in records if values[r.id] is None]
    with_value.sort(key=lambda r: sort_value(values[r.id]), reverse=reverse)
    return with_value + without_value


def sort_value(value: Any) -> tuple[int, Any, str]:
    """Type-tagged sort key: bools < numbers < text; mixed types never collide.

    Numeric strings compare numerically ("10" after "2"), and legacy float
    decimals sort against canonical decimal strings via ``Decimal``.
    Non-finite values (NaN, Infinity — reachable from pre-v0.7.1 rows and
    from plain text attributes) cannot be ordered, so they sort as text
    instead of crashing the comparison.
    """
    if isinstance(value, bool):
        return (0, int(value), "")
    if isinstance(value, (int, float)):
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite():
            return (2, 0, str(value).lower())
        return (1, decimal_value, "")
    if isinstance(value, list):
        return (2, 0, str(value).lower())
    if isinstance(value, str):
        try:
            decimal_value = Decimal(value)
        except InvalidOperation:
            return (2, 0, value.lower())
        if not decimal_value.is_finite():
            return (2, 0, value.lower())
        return (1, decimal_value, "")
    return (2, 0, str(value).lower())


@dataclass(frozen=True)
class ViewColumn:
    """A resolved view column: a base attribute or a related-entity attribute.

    Calculated columns (text joins, arithmetic formulas) carry ``attr=None``
    and their spec in ``calc`` — they are rendered from the other columns'
    values, never read from the record directly.
    """

    key: str
    label: str
    attr: Attribute | None
    # Resolved hops for related columns (dir/ref/to/many/name/to_name); None for base.
    path: list[dict[str, Any]] | None = None
    # Normalised calculated-column spec ({"kind": "concat"|"formula", ...}).
    calc: dict[str, Any] | None = None

    @property
    def slug(self) -> str:
        """Compatibility alias (base columns key by attribute slug)."""
        return self.key

    @property
    def with_copy_button(self) -> bool:
        """Copy icon flag; calculated columns never carry one."""
        return bool(self.attr and self.attr.with_copy_button)

    @property
    def is_calculated(self) -> bool:
        return self.calc is not None

    @property
    def is_numeric(self) -> bool:
        """Numeric columns align right in the grids (formulas count: they are
        arithmetic results; text joins are not)."""
        if self.attr is not None:
            return self.attr.is_numeric
        return bool(self.calc and self.calc.get("kind") == "formula")


def column_spec_string(column: ViewColumn) -> str:
    """Encode a resolved column as a form-style spec (``parse_column_spec``-compatible)."""
    if column.calc is not None:
        # Calculated columns are not addressable as filter/sort columns.
        return f"calc:{column.key}"
    if column.path is None:
        return f"base:{column.key}"
    hops = "/".join(f"{h['dir']}:{h['ref']}:{h['to']}:{h['many']}" for h in column.path)
    slug = column.attr.slug if column.attr else column.key
    return f"rel:{hops}→{slug}"


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


def _resolve_calculated_columns(columns: list[ViewColumn], specs: Any) -> list[ViewColumn]:
    """Append the view's calculated columns to ``columns``.

    Specs whose kind/label is missing or whose references cannot be resolved
    against the view's own columns are skipped (view configs are lenient by
    design — the same rule related-column specs follow).
    """
    if not isinstance(specs, list) or not specs:
        return list(columns)
    available = {column.key for column in columns}
    resolved: list[ViewColumn] = []
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            continue
        label = str(spec.get("label") or "").strip()
        kind = spec.get("kind")
        if not label or kind not in CALC_KINDS:
            continue
        if kind == "concat":
            parts = [
                part
                for part in spec.get("parts") or []
                if isinstance(part, str) and part in available
            ]
            if not parts:
                continue
            calc = {
                "kind": "concat",
                "label": label,
                "parts": parts,
                "separator": str(spec.get("separator") or ""),
            }
        else:
            try:
                node = parse_formula(str(spec.get("expr") or ""))
            except FormulaError:
                continue
            references = formula_references(node)
            if not references or not references <= available:
                continue
            calc = {
                "kind": "formula",
                "label": label,
                "expr": str(spec["expr"]).strip(),
                "node": node,
            }
        resolved.append(ViewColumn(key=f"calc:{index}", label=label, attr=None, calc=calc))
    return list(columns) + resolved


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
            attrs.append({"slug": attr.slug, "name": attr.name, "type": attr.data_type})
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
    cache: dict | None = None,
) -> list[dict[str, Any]]:
    """Build display rows for a view, resolving related-entity columns.

    Calculated columns are filled last: their inputs are the display cells of
    the other columns (concatenation) and the raw stored values (formulas).
    """
    base_titles = resolve_reference_titles(db, entity, cache=cache)
    display_columns = [c for c in columns if c.calc is None]
    calculated_columns = [c for c in columns if c.calc is not None]
    related = [c for c in display_columns if c.path is not None]
    records_by_entity, reverse_index, terminal_titles = _related_context(
        db, entity, related, records, cache
    )
    context = (records_by_entity, reverse_index, terminal_titles)
    columns_by_key = {c.key: c for c in display_columns}

    rows: list[dict[str, Any]] = []
    for record in records:
        cells: dict[str, str] = {}
        link_hrefs: dict[str, str] = {}
        for column in display_columns:
            attr = column.attr
            if attr is None:  # pragma: no cover - display columns always carry an attr
                continue
            if column.path is None:
                cells[column.key] = _display_cell(attr, record.data.get(attr.slug), base_titles)
                if attr.data_type == DataType.LINK.value and record.data.get(attr.slug):
                    link_hrefs[column.key] = record.data[attr.slug]
            else:
                cells[column.key], href = _resolve_related_cell(
                    record, column, records_by_entity, reverse_index, terminal_titles
                )
                if href:
                    link_hrefs[column.key] = href
        for column in calculated_columns:
            cells[column.key] = _calculated_cell(column, record, context, cells, columns_by_key)
        rows.append({"record": record, "cells": cells, "link_hrefs": link_hrefs})
    return rows


# --------------------------------------------------------------------------- #
# Calculated columns
# --------------------------------------------------------------------------- #

EMPTY_CELL = "—"


def _calculated_cell(
    column: ViewColumn,
    record: Record,
    context: tuple[
        dict[int, dict[int, Record]],
        dict[tuple[int, str], dict[int, list[int]]],
        dict[int, dict[int, str]],
    ],
    cells: dict[str, str],
    columns_by_key: dict[str, ViewColumn],
) -> str:
    """Render one calculated cell: a text join or an arithmetic formula."""
    spec = column.calc or {}
    if spec.get("kind") == "concat":
        parts = [str(cells.get(key, "")).strip() for key in spec.get("parts", [])]
        present = [part for part in parts if part and part != EMPTY_CELL]
        if not present:
            return EMPTY_CELL
        return str(spec.get("separator") or "").join(present)

    node = spec.get("node")
    if node is None:  # pragma: no cover - resolver only stores parsed formulas
        return EMPTY_CELL
    values = {
        key: _raw_column_value(record, columns_by_key[key], context)
        for key in formula_references(node)
        if key in columns_by_key
    }
    value = evaluate_formula(node, values)
    return EMPTY_CELL if value is None else format_total(value)


def _raw_column_value(
    record: Record,
    column: ViewColumn,
    context: tuple[
        dict[int, dict[int, Record]],
        dict[tuple[int, str], dict[int, list[int]]],
        dict[int, dict[int, str]],
    ]
    | None,
) -> Any:
    """The raw stored value a column reads for one record.

    Base columns use the record's own value; related columns use their first
    terminal value — the same value they sort by. ``None`` when unavailable.
    """
    if column.attr is None:
        return None
    if column.path is None:
        return record.data.get(column.attr.slug)
    if context is None:
        return None
    return _resolve_related_sort_value(record, column, context)


# --------------------------------------------------------------------------- #
# Grand totals (custom views)
# --------------------------------------------------------------------------- #


def build_totals(
    db: Session,
    entity: Entity,
    records: list[Record],
    columns: list[ViewColumn],
    config: dict,
    cache: dict | None = None,
) -> dict[str, dict[str, str]]:
    """Grand totals for the view's numeric columns, as the template consumes them.

    ``config["totals"]`` maps a column key (base slug or ``rel:…`` key) to one
    of :data:`TOTAL_OPS`; entries whose column is missing or not numeric are
    ignored (view configs are lenient by design, same as column specs).
    """
    totals_spec = config.get("totals")
    if not isinstance(totals_spec, dict) or not totals_spec:
        return {}
    wanted = [
        column
        for column in columns
        if column.attr is not None
        and totals_spec.get(column.key) in TOTAL_OPS
        and is_numeric_attribute(column.attr)
    ]
    if not wanted:
        return {}
    # Related columns need the hop-resolution context; base columns do not.
    context = (
        _related_context(db, entity, wanted, records, cache)
        if any(column.path is not None for column in wanted)
        else None
    )
    totals: dict[str, dict[str, str]] = {}
    for column in wanted:
        op = totals_spec[column.key]
        values = []
        for record in records:
            value = _column_numeric_value(record, column, context)
            if value is not None:
                values.append(value)
        if not values:
            continue
        totals[column.key] = {"op": op, "value": format_total(aggregate(values, op))}
    return totals


def _column_numeric_value(
    record: Record,
    column: ViewColumn,
    context: tuple[
        dict[int, dict[int, Record]],
        dict[tuple[int, str], dict[int, list[int]]],
        dict[int, dict[int, str]],
    ]
    | None,
) -> Any:
    """The column's numeric value for one record (None when not numeric)."""
    return to_decimal(_raw_column_value(record, column, context))


def _related_context(
    db: Session,
    entity: Entity,
    columns: list[ViewColumn],
    records: list[Record],
    cache: dict | None = None,
) -> tuple[
    dict[int, dict[int, Record]],
    dict[tuple[int, str], dict[int, list[int]]],
    dict[int, dict[int, str]],
]:
    """Load the shared resolution context for related columns.

    Returns ``(records_by_entity, reverse_index, terminal_titles)`` — the
    three maps needed to walk reference hops and format terminal values.
    ``cache`` (per-request) memoises per-entity record loads.
    """
    entity_ids = {entity.id}
    for column in columns:
        for hop in column.path or []:
            entity_ids.add(hop["to"])
    records_by_entity = {eid: _cached_entity_records(db, eid, cache) for eid in entity_ids}

    reverse_index: dict[tuple[int, str], dict[int, list[int]]] = {}
    for column in columns:
        for hop in column.path or []:
            if hop["dir"] == "down":
                key = (hop["to"], hop["ref"])
                if key not in reverse_index:
                    reverse_index[key] = _build_reverse_index(
                        records_by_entity.get(hop["to"], {}), hop["ref"]
                    )

    terminal_titles: dict[int, dict[int, str]] = {}
    for column in columns:
        attr = column.attr
        if attr is None:
            continue
        if attr.data_type == DataType.REFERENCE.value and attr.reference_entity_id is not None:
            target_id = attr.reference_entity_id
            if target_id not in terminal_titles:
                terminal_titles[target_id] = build_record_titles(db, target_id, cache=cache)

    return records_by_entity, reverse_index, terminal_titles


def _cached_entity_records(db: Session, entity_id: int, cache: dict | None) -> dict[int, Record]:
    key = ("records", entity_id)
    if cache is not None and key in cache:
        return cache[key]
    by_id = {r.id: r for r in list_records(db, entity_id)}
    if cache is not None:
        cache[key] = by_id
    return by_id


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
) -> tuple[str, str | None]:
    """Walk the column's hop path from ``record`` and format the terminal value.

    Returns ``(display_text, href)``; ``href`` is set only when the terminal
    attribute is a ``link`` and the path resolves to exactly one URL (a
    ``many=all`` fan-out has no single link target).
    """
    current: list[Record] = [record]
    for hop in column.path or []:
        reached: list[Record] = []
        for rec in current:
            reached.extend(_follow_hop(rec, hop, records_by_entity, reverse_index))
        current = reached
        if not current:
            return "—", None

    attr = column.attr
    if attr is None:
        return "—", None
    if attr.data_type == DataType.REFERENCE.value:
        titles = terminal_titles.get(attr.reference_entity_id or -1, {})
        parts: list[str] = []
        for rec in current:
            value = rec.data.get(attr.slug)
            if value is None:
                continue
            ids = value if isinstance(value, list) else [value]
            parts.extend(titles.get(i, f"#{i}") for i in ids)
        return ", ".join(parts) or "—", None

    parts = []
    for rec in current:
        value = rec.data.get(attr.slug)
        if value is not None:
            parts.append(format_value(value))
    text = ", ".join(parts) or "—"
    href = parts[0] if attr.data_type == DataType.LINK.value and len(parts) == 1 else None
    return text, href


def _resolve_related_sort_value(
    record: Record,
    column: ViewColumn,
    context: tuple[
        dict[int, dict[int, Record]],
        dict[tuple[int, str], dict[int, list[int]]],
        dict[int, dict[int, str]],
    ],
) -> Any:
    """First terminal value of a related column, used as the sort key.

    Reference terminals sort by their display title; scalars sort by their
    raw (typed) value so numbers order numerically. ``None`` when the path
    is broken or the value is missing — such records sort last.
    """
    records_by_entity, reverse_index, terminal_titles = context
    current: list[Record] = [record]
    for hop in column.path or []:
        reached: list[Record] = []
        for rec in current:
            reached.extend(_follow_hop(rec, hop, records_by_entity, reverse_index))
        current = reached
        if not current:
            return None

    attr = column.attr
    if attr is None:
        return None
    for rec in current:
        value = rec.data.get(attr.slug)
        if value is None:
            continue
        ids = value if isinstance(value, list) else [value]
        if not ids:
            continue
        if attr.data_type == DataType.REFERENCE.value:
            titles = terminal_titles.get(attr.reference_entity_id or -1, {})
            return titles.get(ids[0], f"#{ids[0]}")
        return ids[0]
    return None


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
