"""Business logic for the schema engine: entities and attributes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.attribute import Attribute
from app.models.entity import Entity
from app.models.enums import DataType
from app.models.record import Record
from app.schemas.attribute import AttributeCreate, AttributeUpdate
from app.schemas.entity import EntityCreate, EntityUpdate
from app.services.record_service import build_record_titles, list_records
from app.services.slugs import slugify, unique_slug
from app.services.validation import ValidationError, coerce_value


class SchemaError(ValueError):
    """Raised for invalid schema operations."""


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #


def list_entities(db: Session) -> list[Entity]:
    return list(
        db.execute(
            select(Entity).options(selectinload(Entity.attributes)).order_by(Entity.name)
        ).scalars()
    )


def get_entity(db: Session, entity_id: int) -> Entity | None:
    return db.get(Entity, entity_id)


def get_entity_with_attributes(db: Session, entity_id: int) -> Entity | None:
    return db.execute(
        select(Entity).options(selectinload(Entity.attributes)).where(Entity.id == entity_id)
    ).scalar_one_or_none()


def entity_record_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(Record.entity_id, func.count(Record.id))
        .where(Record.deleted_at.is_(None))
        .group_by(Record.entity_id)
    ).all()
    return {entity_id: count for entity_id, count in rows}


def create_entity(db: Session, data: EntityCreate, created_by: int | None = None) -> Entity:
    name = data.name.strip()
    if db.execute(select(Entity.id).where(Entity.name == name)).first() is not None:
        raise SchemaError(f"An entity named '{name}' already exists.")
    entity = Entity(
        name=name,
        slug=unique_slug(db, Entity, name),
        description=data.description.strip(),
        icon=data.icon.strip(),
        created_by=created_by,
    )
    db.add(entity)
    db.commit()
    return entity


def update_entity(db: Session, entity: Entity, data: EntityUpdate) -> Entity:
    name = data.name.strip()
    exists = db.execute(
        select(Entity.id).where(Entity.name == name, Entity.id != entity.id)
    ).first()
    if exists is not None:
        raise SchemaError(f"An entity named '{name}' already exists.")
    entity.name = name
    entity.description = data.description.strip()
    entity.icon = data.icon.strip()
    if data.slug:
        new_slug = slugify(data.slug)
        if new_slug != entity.slug:
            if entity_has_records(db, entity.id):
                raise SchemaError("The slug can only be changed while the entity has no records.")
            entity.slug = unique_slug(db, Entity, new_slug, exclude_id=entity.id)
    db.commit()
    return entity


def delete_entity(db: Session, entity: Entity) -> None:
    # Cascades to attributes and records via ondelete=CASCADE foreign keys.
    db.delete(entity)
    db.commit()


# --------------------------------------------------------------------------- #
# Attributes
# --------------------------------------------------------------------------- #


def _build_config(data: AttributeCreate) -> dict:
    config: dict = {}
    if data.data_type == DataType.ENUM:
        config["options"] = [o.strip() for o in (data.options or []) if o.strip()]
    elif data.data_type == DataType.REFERENCE:
        config["reference_entity_id"] = data.reference_entity_id
        config["cardinality"] = data.cardinality
    return config


def _validate_definition(data: AttributeCreate, db: Session) -> None:
    if data.data_type == DataType.ENUM:
        options = [o.strip() for o in (data.options or []) if o.strip()]
        if len(options) < 2:
            raise SchemaError("Enum attributes require at least two options.")
        if data.default_value not in (None, "") and data.default_value not in options:
            raise SchemaError("Default value must be one of the enum options.")

    if data.data_type == DataType.REFERENCE:
        if data.reference_entity_id is None:
            raise SchemaError("Reference attributes require a target entity.")
        if db.get(Entity, data.reference_entity_id) is None:
            raise SchemaError("Reference target entity does not exist.")

    if data.default_value not in (None, ""):
        try:
            coerce_value(data.data_type, data.default_value)
        except ValidationError as exc:
            raise SchemaError(f"Invalid default value: {exc}") from exc


def _next_sort_order(db: Session, entity_id: int) -> int:
    current = db.execute(
        select(func.coalesce(func.max(Attribute.sort_order), 0)).where(
            Attribute.entity_id == entity_id
        )
    ).scalar_one()
    return current + 1


def entity_has_records(db: Session, entity_id: int) -> bool:
    """True when the entity has at least one non-deleted record."""
    return (
        db.execute(
            select(Record.id)
            .where(Record.entity_id == entity_id, Record.deleted_at.is_(None))
            .limit(1)
        ).first()
        is not None
    )


# --------------------------------------------------------------------------- #
# Data-type changes
# --------------------------------------------------------------------------- #

# Conversions allowed while the entity already has records: text, textarea and
# link all persist plain strings, so these keep every stored value meaningful.
# Every other transition (integer -> boolean, text -> reference, ...) would
# silently reinterpret the JSON already in the rows and stays refused.
_PERMITTED_TYPE_CHANGES: frozenset[tuple[DataType, DataType]] = frozenset(
    {
        (DataType.TEXT, DataType.LINK),
        (DataType.LINK, DataType.TEXT),
        (DataType.TEXT, DataType.TEXTAREA),
        (DataType.TEXTAREA, DataType.TEXT),
    }
)

# Failures reported in full before the message switches to "+N more".
_MAX_REPORTED_VALUES = 3


def _conversion_targets(data_type: DataType) -> set[DataType]:
    """Types ``data_type`` may be converted to while the entity has records."""
    return {to for frm, to in _PERMITTED_TYPE_CHANGES if frm == data_type}


def permitted_data_types(db: Session, attribute: Attribute) -> set[DataType]:
    """Data types the edit form offers for ``attribute``.

    All of them while the entity has no records; otherwise the current type
    plus the conversions that keep every stored value valid. The form disables
    everything outside this set, and ``_validate_type_change`` rejects it
    server-side if the request is hand-crafted anyway.
    """
    current = attribute.data_type_enum
    if not entity_has_records(db, attribute.entity_id):
        return set(DataType)
    return {current} | _conversion_targets(current)


def _validate_type_change(db: Session, attribute: Attribute, new_type: DataType) -> None:
    """Guard a data-type change on an attribute whose entity already has records.

    All-or-nothing: every live record is checked *before* the definition is
    touched, so a rejected conversion leaves the attribute and its values
    exactly as they were.
    """
    current = attribute.data_type_enum
    targets = _conversion_targets(current)
    if new_type not in targets:
        if not targets:
            raise SchemaError(
                f"The data type of '{attribute.name}' ({current.value}) cannot be changed "
                "while the entity has records."
            )
        options = " or ".join(sorted(t.value for t in targets))
        raise SchemaError(
            f"The data type of '{attribute.name}' ({current.value}) can only be changed to "
            f"{options} while the entity has records."
        )
    if new_type == DataType.LINK:
        _require_link_values(db, attribute)
    else:
        _require_single_line_values(db, attribute)


def _reject_values(
    attribute: Attribute,
    target: DataType,
    failures: list[str],
    total: int,
    problem: str,
) -> None:
    """Raise ``SchemaError`` listing the records that block the conversion."""
    if not failures:
        return
    shown = ", ".join(failures[:_MAX_REPORTED_VALUES])
    if len(failures) > _MAX_REPORTED_VALUES:
        shown += f", +{len(failures) - _MAX_REPORTED_VALUES} more"
    raise SchemaError(
        f"Cannot change '{attribute.name}' to {target.value}: {len(failures)} of {total} "
        f"record(s) {problem} ({shown}). Nothing was changed."
    )


def _record_values(db: Session, attribute: Attribute) -> list[tuple[Record, str, Any]]:
    """Live records paired with their display title and this attribute's value."""
    titles = build_record_titles(db, attribute.entity_id)
    return [
        (record, titles.get(record.id, f"#{record.id}"), (record.data or {}).get(attribute.slug))
        for record in list_records(db, attribute.entity_id)
    ]


def _require_link_values(db: Session, attribute: Attribute) -> None:
    """text -> link: every stored value must already be a valid http(s) URL."""
    entries = _record_values(db, attribute)
    failures: list[str] = []
    for _record, label, value in entries:
        if value in (None, ""):
            continue
        try:
            coerce_value(DataType.LINK, value)
        except ValidationError:
            failures.append(f"{label}: {value!r}")
    _reject_values(
        attribute,
        DataType.LINK,
        failures,
        len(entries),
        "hold a value that is not a valid http(s) URL",
    )


def _require_single_line_values(db: Session, attribute: Attribute) -> None:
    """textarea -> text: no stored value may contain a line break.

    A ``text`` attribute is edited in a single-line ``<input>``, and the HTML
    value-sanitisation algorithm strips CR/LF from those — so a multi-line
    value would be silently truncated the next time the record is saved.
    """
    entries = _record_values(db, attribute)
    failures: list[str] = []
    for _record, label, value in entries:
        if not isinstance(value, str) or not ("\n" in value or "\r" in value):
            continue
        lines = value.splitlines()
        first_line = lines[0][:40] if lines else ""
        failures.append(f"{label}: {len(lines)} lines, starts with {first_line!r}")
    _reject_values(
        attribute,
        DataType.TEXT,
        failures,
        len(entries),
        "hold a multi-line value that a single-line field would truncate",
    )


def add_attribute(db: Session, entity: Entity, data: AttributeCreate) -> Attribute:
    _validate_definition(data, db)
    attribute = Attribute(
        entity_id=entity.id,
        name=data.name.strip(),
        slug=unique_slug(db, Attribute, data.name.strip(), scope={"entity_id": entity.id}),
        data_type=data.data_type.value,
        is_required=data.is_required,
        is_unique=data.is_unique,
        with_copy_button=data.with_copy_button,
        is_key=data.is_key,
        is_active=(True if data.is_required else data.is_active),
        default_value=coerce_value(data.data_type, data.default_value),
        hint=(data.hint.strip() if data.hint else None),
        config=_build_config(data),
        sort_order=_next_sort_order(db, entity.id),
    )
    db.add(attribute)
    db.commit()
    return attribute


def reorder_attributes(db: Session, entity_id: int, ordered_ids: list[int]) -> None:
    """Persist a new display order for an entity's attributes.

    ``ordered_ids`` must be exactly the entity's attribute ids (a permutation).
    Each attribute's ``sort_order`` is rewritten to its index in ``ordered_ids``.
    """
    attributes = (
        db.execute(select(Attribute).where(Attribute.entity_id == entity_id)).scalars().all()
    )
    by_id = {a.id: a for a in attributes}
    if len(ordered_ids) != len(by_id) or set(ordered_ids) != set(by_id):
        raise SchemaError("The ordering does not match the entity's attributes.")
    for index, attribute_id in enumerate(ordered_ids):
        by_id[attribute_id].sort_order = index
    db.commit()


def update_attribute(db: Session, attribute: Attribute, data: AttributeUpdate) -> Attribute:
    _validate_definition(data, db)
    has_records = entity_has_records(db, attribute.entity_id)

    if has_records:
        # Structural changes would leave existing values un-revalidated
        # (e.g. INTEGER->BOOLEAN leaves 8 in the JSON); refuse them while the
        # entity has data, except the string-to-string conversions in
        # _PERMITTED_TYPE_CHANGES (validated against every record first).
        # Display-only and default-value edits stay allowed.
        if data.data_type != attribute.data_type_enum:
            _validate_type_change(db, attribute, data.data_type)
        if data.is_unique != attribute.is_unique:
            raise SchemaError(
                "The unique flag can only be changed while the entity has no records."
            )
        if data.is_key != attribute.is_key:
            raise SchemaError("The key flag can only be changed while the entity has no records.")
        if data.slug and slugify(data.slug) != attribute.slug:
            raise SchemaError("The slug can only be changed while the entity has no records.")
        if attribute.data_type_enum == DataType.REFERENCE:
            # Existing records store ids into the current target entity;
            # repointing (or flipping one<->many) would silently reinterpret
            # every stored value against a different record set.
            if data.reference_entity_id != attribute.reference_entity_id:
                raise SchemaError(
                    "The reference target can only be changed while the entity has no records."
                )
            if data.cardinality != attribute.cardinality:
                raise SchemaError(
                    "The reference cardinality can only be changed while the entity has no records."
                )
        # is_active is locked while the entity has records.
    else:
        if data.slug:
            new_slug = slugify(data.slug)
            if new_slug != attribute.slug:
                attribute.slug = unique_slug(
                    db,
                    Attribute,
                    new_slug,
                    scope={"entity_id": attribute.entity_id},
                    exclude_id=attribute.id,
                )
        attribute.is_active = True if data.is_required else data.is_active

    attribute.name = data.name.strip()
    attribute.data_type = data.data_type.value
    attribute.is_required = data.is_required
    attribute.is_unique = data.is_unique
    attribute.with_copy_button = data.with_copy_button
    attribute.is_key = data.is_key
    attribute.default_value = coerce_value(data.data_type, data.default_value)
    attribute.hint = data.hint.strip() if data.hint else None
    attribute.config = _build_config(data)

    db.commit()
    return attribute


def delete_attribute(db: Session, attribute: Attribute) -> None:
    """Delete an attribute, removing its value from every record first.

    Record values are keyed by attribute slug, so the slug must be stripped from
    each of the entity's records (soft-deleted included) before the attribute is
    deleted.
    """
    records = (
        db.execute(select(Record).where(Record.entity_id == attribute.entity_id)).scalars().all()
    )
    for record in records:
        if record.data and attribute.slug in record.data:
            record.data = {k: v for k, v in record.data.items() if k != attribute.slug}
    db.delete(attribute)
    db.commit()
