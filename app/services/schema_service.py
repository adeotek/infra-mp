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
from app.services.slugs import unique_slug
from app.services.validation import ValidationError, coerce_value


class SchemaError(ValueError):
    """Raised for invalid schema operations."""


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #

def list_entities(db: Session) -> list[Entity]:
    return list(
        db.execute(
            select(Entity)
            .options(selectinload(Entity.attributes))
            .order_by(Entity.name)
        ).scalars()
    )


def get_entity(db: Session, entity_id: int) -> Entity | None:
    return db.get(Entity, entity_id)


def get_entity_with_attributes(db: Session, entity_id: int) -> Entity | None:
    return db.execute(
        select(Entity)
        .options(selectinload(Entity.attributes))
        .where(Entity.id == entity_id)
    ).scalar_one_or_none()


def entity_record_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(Record.entity_id, func.count(Record.id))
        .where(Record.deleted_at.is_(None))
        .group_by(Record.entity_id)
    ).all()
    return {entity_id: count for entity_id, count in rows}


def create_entity(db: Session, data: EntityCreate, created_by: int | None = None) -> Entity:
    entity = Entity(
        name=data.name.strip(),
        slug=unique_slug(db, Entity, data.name.strip()),
        description=data.description.strip(),
        icon=data.icon.strip(),
        created_by=created_by,
    )
    db.add(entity)
    db.commit()
    return entity


def update_entity(db: Session, entity: Entity, data: EntityUpdate) -> Entity:
    # The slug is an immutable identifier: it is generated once at creation and
    # intentionally not changed on rename so existing URLs stay valid.
    entity.name = data.name.strip()
    entity.description = data.description.strip()
    entity.icon = data.icon.strip()
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


def add_attribute(db: Session, entity: Entity, data: AttributeCreate) -> Attribute:
    _validate_definition(data, db)
    attribute = Attribute(
        entity_id=entity.id,
        name=data.name.strip(),
        slug=unique_slug(db, Attribute, data.name.strip(), scope={"entity_id": entity.id}),
        data_type=data.data_type.value,
        is_required=data.is_required,
        default_value=coerce_value(data.data_type, data.default_value),
        config=_build_config(data),
        sort_order=_next_sort_order(db, entity.id),
    )
    db.add(attribute)
    db.commit()
    return attribute


def update_attribute(db: Session, attribute: Attribute, data: AttributeUpdate) -> Attribute:
    _validate_definition(data, db)
    attribute.name = data.name.strip()
    attribute.data_type = data.data_type.value
    attribute.is_required = data.is_required
    attribute.default_value = coerce_value(data.data_type, data.default_value)
    attribute.config = _build_config(data)
    db.commit()
    return attribute


def delete_attribute(db: Session, attribute: Attribute) -> None:
    entity_id = attribute.entity_id
    slug = attribute.slug
    db.delete(attribute)
    # Remove this attribute's value from every record's JSON document.
    records = db.execute(select(Record).where(Record.entity_id == entity_id)).scalars().all()
    for record in records:
        if slug in record.data:
            data = dict(record.data)
            data.pop(slug, None)
            record.data = data
    db.commit()
