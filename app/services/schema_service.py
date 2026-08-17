"""Business logic for the schema engine: entities and attributes."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.attribute import Attribute
from app.models.entity import Entity
from app.models.enums import DataType
from app.models.record import Record
from app.schemas.attribute import AttributeCreate, AttributeUpdate
from app.schemas.entity import EntityCreate, EntityUpdate
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


def add_attribute(db: Session, entity: Entity, data: AttributeCreate) -> Attribute:
    _validate_definition(data, db)
    attribute = Attribute(
        entity_id=entity.id,
        name=data.name.strip(),
        slug=unique_slug(db, Attribute, data.name.strip(), scope={"entity_id": entity.id}),
        data_type=data.data_type.value,
        is_required=data.is_required,
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

    attribute.name = data.name.strip()
    attribute.data_type = data.data_type.value
    attribute.is_required = data.is_required
    attribute.default_value = coerce_value(data.data_type, data.default_value)
    attribute.hint = data.hint.strip() if data.hint else None
    attribute.config = _build_config(data)

    if has_records:
        if data.slug and slugify(data.slug) != attribute.slug:
            raise SchemaError("The slug can only be changed while the entity has no records.")
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

    db.commit()
    return attribute


def delete_attribute(db: Session, attribute: Attribute) -> None:
    if entity_has_records(db, attribute.entity_id):
        raise SchemaError("Cannot delete an attribute while the entity has records.")
    db.delete(attribute)
    db.commit()
