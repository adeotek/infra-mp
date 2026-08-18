"""Service-level tests for schema engine edge cases."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate, AttributeUpdate
from app.schemas.entity import EntityCreate, EntityUpdate
from app.services.record_service import create_record
from app.services.schema_service import (
    SchemaError,
    add_attribute,
    create_entity,
    delete_attribute,
    entity_record_counts,
    get_entity_with_attributes,
    reorder_attributes,
    update_attribute,
    update_entity,
)


def test_update_entity_renames_but_keeps_slug(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    update_entity(db_session, entity, EntityUpdate(name="Server Renamed"))
    assert entity.name == "Server Renamed"
    assert entity.slug == "server"


def test_update_entity_duplicate_name_rejected(db_session):
    create_entity(db_session, EntityCreate(name="A"))
    b = create_entity(db_session, EntityCreate(name="B"))
    with pytest.raises(SchemaError):
        update_entity(db_session, b, EntityUpdate(name="A"))


def test_entity_record_counts(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    entity = get_entity_with_attributes(db_session, entity.id)
    create_record(db_session, entity, entity.attributes, {"name": "web01"})
    assert entity_record_counts(db_session) == {entity.id: 1}


def test_add_attribute_coerces_default(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Cores", data_type=DataType.INTEGER, default_value="4"),
    )
    assert attr.default_value == 4


def test_add_attribute_invalid_default_rejected(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    with pytest.raises(SchemaError):
        add_attribute(
            db_session,
            entity,
            AttributeCreate(name="Cores", data_type=DataType.INTEGER, default_value="abc"),
        )


def test_enum_default_must_be_an_option(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    with pytest.raises(SchemaError):
        add_attribute(
            db_session,
            entity,
            AttributeCreate(
                name="Status", data_type=DataType.ENUM, options=["a", "b"], default_value="c"
            ),
        )


def test_update_attribute_keeps_slug(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    update_attribute(db_session, attr, AttributeUpdate(name="Host", data_type=DataType.TEXT))
    assert attr.name == "Host"
    assert attr.slug == "hostname"


def test_delete_attribute_removes_values_from_records(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER))
    entity = get_entity_with_attributes(db_session, entity.id)
    assert entity is not None
    record = create_record(db_session, entity, entity.attributes, {"name": "web01", "cores": "8"})
    assert record.data == {"name": "web01", "cores": 8}

    cores = next(a for a in entity.attributes if a.slug == "cores")
    delete_attribute(db_session, cores)

    db_session.expire_all()
    db_session.refresh(record)
    refreshed = get_entity_with_attributes(db_session, entity.id)
    assert refreshed is not None
    assert [a.slug for a in refreshed.attributes] == ["name"]
    assert record.data == {"name": "web01"}


def test_delete_attribute_ok_when_no_records(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    delete_attribute(db_session, attr)
    assert get_entity_with_attributes(db_session, entity.id).attributes == []


def test_update_attribute_slug_when_no_records(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    update_attribute(
        db_session,
        attr,
        AttributeUpdate(name="Hostname", data_type=DataType.TEXT, slug="fqdn"),
    )
    assert attr.slug == "fqdn"


def test_update_attribute_slug_blocked_when_records_exist(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    entity = get_entity_with_attributes(db_session, entity.id)
    create_record(db_session, entity, entity.attributes, {"name": "web01"})
    with pytest.raises(SchemaError):
        update_attribute(
            db_session,
            entity.attributes[0],
            AttributeUpdate(name="Name", data_type=DataType.TEXT, slug="changed"),
        )


def test_required_attribute_cannot_be_inactivated(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Name", data_type=DataType.TEXT, is_required=True, is_active=False),
    )
    assert attr.is_active is True


def test_optional_attribute_can_be_inactivated(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Note", data_type=DataType.TEXT, is_active=False)
    )
    assert attr.is_active is False


def test_add_attribute_stores_hint(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Hostname", data_type=DataType.TEXT, hint="FQDN of the server."),
    )
    assert attr.hint == "FQDN of the server."


def test_update_attribute_updates_hint(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    update_attribute(
        db_session,
        attr,
        AttributeUpdate(name="Hostname", data_type=DataType.TEXT, hint="Updated hint"),
    )
    assert attr.hint == "Updated hint"


def test_add_attribute_stores_unique(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Hostname", data_type=DataType.TEXT, is_unique=True),
    )
    assert attr.is_unique is True


def test_update_attribute_updates_unique(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    assert attr.is_unique is False
    update_attribute(
        db_session,
        attr,
        AttributeUpdate(name="Hostname", data_type=DataType.TEXT, is_unique=True),
    )
    assert attr.is_unique is True


def test_update_entity_slug_when_no_records(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    update_entity(db_session, entity, EntityUpdate(name="Server", slug="server-renamed"))
    assert entity.slug == "server-renamed"


def test_update_entity_slug_blocked_when_records_exist(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    entity = get_entity_with_attributes(db_session, entity.id)
    create_record(db_session, entity, entity.attributes, {"name": "web01"})
    with pytest.raises(SchemaError):
        update_entity(db_session, entity, EntityUpdate(name="Server", slug="changed"))


def test_update_attribute_cannot_change_active_when_records_exist(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Note", data_type=DataType.TEXT))
    entity = get_entity_with_attributes(db_session, entity.id)
    create_record(db_session, entity, entity.attributes, {"note": "x"})
    update_attribute(
        db_session,
        entity.attributes[0],
        AttributeUpdate(name="Note", data_type=DataType.TEXT, is_active=False),
    )
    assert entity.attributes[0].is_active is True  # frozen while records exist


def test_reorder_attributes_persists_new_order(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    a = add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    b = add_attribute(db_session, entity, AttributeCreate(name="IP", data_type=DataType.TEXT))
    c = add_attribute(db_session, entity, AttributeCreate(name="Role", data_type=DataType.TEXT))
    reorder_attributes(db_session, entity.id, [c.id, a.id, b.id])
    refreshed = get_entity_with_attributes(db_session, entity.id)
    assert refreshed is not None
    assert [x.slug for x in refreshed.attributes] == ["role", "name", "ip"]


def test_reorder_attributes_rejects_mismatched_ids(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, entity, AttributeCreate(name="IP", data_type=DataType.TEXT))
    with pytest.raises(SchemaError):
        reorder_attributes(db_session, entity.id, [999])


def test_reorder_attributes_rejects_duplicate_ids(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    a = add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, entity, AttributeCreate(name="IP", data_type=DataType.TEXT))
    with pytest.raises(SchemaError):
        reorder_attributes(db_session, entity.id, [a.id, a.id])
