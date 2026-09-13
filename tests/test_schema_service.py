"""Service-level tests for schema engine edge cases."""

import pytest

from app.models.attribute import Attribute
from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate, AttributeUpdate
from app.schemas.entity import EntityCreate, EntityUpdate
from app.services.record_service import create_record, list_records, soft_delete_record
from app.services.schema_service import (
    SchemaError,
    add_attribute,
    create_entity,
    delete_attribute,
    entity_record_counts,
    get_entity_with_attributes,
    permitted_data_types,
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


def test_add_attribute_stores_copy_button(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Panel", data_type=DataType.LINK, with_copy_button=True),
    )
    assert attr.with_copy_button is True
    assert attr.data_type == "link"


def test_add_attribute_defaults_copy_button_off(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    assert attr.with_copy_button is False


def test_update_attribute_flips_copy_button(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    update_attribute(
        db_session,
        attr,
        AttributeUpdate(name="Hostname", data_type=DataType.TEXT, with_copy_button=True),
    )
    assert attr.with_copy_button is True


def test_link_default_value_must_be_valid_url(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Panel", data_type=DataType.LINK, default_value="https://example.com"),
    )
    assert attr.default_value == "https://example.com"
    with pytest.raises(SchemaError):
        add_attribute(
            db_session,
            entity,
            AttributeCreate(name="Docs", data_type=DataType.LINK, default_value="nope"),
        )


def test_add_attribute_stores_key(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Hostname", data_type=DataType.TEXT, is_key=True),
    )
    assert attr.is_key is True


def test_update_attribute_flips_key(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    update_attribute(
        db_session,
        attr,
        AttributeUpdate(name="Hostname", data_type=DataType.TEXT, is_key=True),
    )
    assert attr.is_key is True
    update_attribute(
        db_session,
        attr,
        AttributeUpdate(name="Hostname", data_type=DataType.TEXT, is_key=False),
    )
    assert attr.is_key is False


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


def test_reference_target_change_rejected_with_records(db_session):
    site = create_entity(db_session, EntityCreate(name="Site"))
    add_attribute(db_session, site, AttributeCreate(name="Name", data_type=DataType.TEXT))
    rack = create_entity(db_session, EntityCreate(name="Rack"))
    add_attribute(db_session, rack, AttributeCreate(name="Name", data_type=DataType.TEXT))
    server = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, server, AttributeCreate(name="Name", data_type=DataType.TEXT))
    attr = add_attribute(
        db_session,
        server,
        AttributeCreate(name="Site", data_type=DataType.REFERENCE, reference_entity_id=site.id),
    )
    server = get_entity_with_attributes(db_session, server.id)
    site = get_entity_with_attributes(db_session, site.id)
    site_record = create_record(db_session, site, site.attributes, {"name": "S1"})
    create_record(db_session, server, server.attributes, {"name": "srv", "site": site_record.id})

    with pytest.raises(SchemaError, match="reference target"):
        update_attribute(
            db_session,
            attr,
            AttributeUpdate(name="Site", data_type=DataType.REFERENCE, reference_entity_id=rack.id),
        )
    with pytest.raises(SchemaError, match="cardinality"):
        update_attribute(
            db_session,
            attr,
            AttributeUpdate(
                name="Site",
                data_type=DataType.REFERENCE,
                reference_entity_id=site.id,
                cardinality="many",
            ),
        )


def test_reference_target_change_allowed_without_records(db_session):
    site = create_entity(db_session, EntityCreate(name="Site"))
    rack = create_entity(db_session, EntityCreate(name="Rack"))
    server = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        server,
        AttributeCreate(name="Site", data_type=DataType.REFERENCE, reference_entity_id=site.id),
    )
    updated = update_attribute(
        db_session,
        attr,
        AttributeUpdate(name="Site", data_type=DataType.REFERENCE, reference_entity_id=rack.id),
    )
    assert updated.reference_entity_id == rack.id


# --------------------------------------------------------------------------- #
# Data-type conversions with records present
# --------------------------------------------------------------------------- #


def _attribute_with_records(db_session, data_type: DataType, values: list[str]):
    """An entity with one 'Note' attribute of ``data_type`` holding ``values``."""
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(db_session, entity, AttributeCreate(name="Note", data_type=data_type))
    entity = get_entity_with_attributes(db_session, entity.id)
    for value in values:
        create_record(db_session, entity, entity.attributes, {"note": value})
    return entity, attr


def _stored_type(db_session, attribute_id: int) -> str:
    """Re-read the attribute from the database (proves nothing was persisted)."""
    db_session.expire_all()
    stored = db_session.get(Attribute, attribute_id)
    assert stored is not None
    return stored.data_type


def _update_type(db_session, attr, data_type: DataType):
    return update_attribute(db_session, attr, AttributeUpdate(name="Note", data_type=data_type))


def test_type_change_allowed_without_records(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(db_session, entity, AttributeCreate(name="Note", data_type=DataType.TEXT))
    assert _update_type(db_session, attr, DataType.INTEGER).data_type == "integer"


def test_text_to_link_allowed_when_every_value_is_a_url(db_session):
    _entity, attr = _attribute_with_records(
        db_session, DataType.TEXT, ["https://a.example", "http://b.example", ""]
    )
    assert _update_type(db_session, attr, DataType.LINK).data_type == "link"


def test_text_to_link_rejected_when_a_value_is_not_a_url(db_session):
    _entity, attr = _attribute_with_records(
        db_session, DataType.TEXT, ["https://a.example", "see the docs"]
    )
    with pytest.raises(SchemaError) as exc:
        _update_type(db_session, attr, DataType.LINK)
    message = str(exc.value)
    assert "see the docs" in message
    assert "1 of 2 record(s)" in message
    assert "Nothing was changed" in message
    assert _stored_type(db_session, attr.id) == "text"  # rolled back


def test_text_to_link_reports_at_most_three_values(db_session):
    values = ["https://ok.example"] + [f"nope {i}" for i in range(5)]
    _entity, attr = _attribute_with_records(db_session, DataType.TEXT, values)
    with pytest.raises(SchemaError) as exc:
        _update_type(db_session, attr, DataType.LINK)
    message = str(exc.value)
    assert "5 of 6 record(s)" in message
    assert "+2 more" in message


def test_soft_deleted_records_do_not_block_a_type_change(db_session):
    entity, attr = _attribute_with_records(
        db_session, DataType.TEXT, ["https://ok.example", "not a url"]
    )
    bad = next(r for r in list_records(db_session, entity.id) if r.data["note"] == "not a url")
    soft_delete_record(db_session, bad)
    assert _update_type(db_session, attr, DataType.LINK).data_type == "link"


def test_link_to_text_allowed_with_records(db_session):
    _entity, attr = _attribute_with_records(db_session, DataType.LINK, ["https://a.example"])
    assert _update_type(db_session, attr, DataType.TEXT).data_type == "text"


def test_text_to_textarea_allowed_with_records(db_session):
    _entity, attr = _attribute_with_records(db_session, DataType.TEXT, ["one line"])
    assert _update_type(db_session, attr, DataType.TEXTAREA).data_type == "textarea"


def test_textarea_to_text_allowed_when_values_are_single_line(db_session):
    _entity, attr = _attribute_with_records(
        db_session, DataType.TEXTAREA, ["one line", "another line"]
    )
    assert _update_type(db_session, attr, DataType.TEXT).data_type == "text"


def test_textarea_to_text_rejected_on_a_multiline_value(db_session):
    _entity, attr = _attribute_with_records(
        db_session, DataType.TEXTAREA, ["fine", "line one\nline two\nline three"]
    )
    with pytest.raises(SchemaError) as exc:
        _update_type(db_session, attr, DataType.TEXT)
    message = str(exc.value)
    assert "would truncate" in message
    assert "3 lines" in message
    assert "line one" in message
    assert _stored_type(db_session, attr.id) == "textarea"  # rolled back


def test_other_conversions_still_rejected_with_records(db_session):
    _entity, attr = _attribute_with_records(db_session, DataType.TEXT, ["https://a.example"])
    with pytest.raises(SchemaError) as exc:
        _update_type(db_session, attr, DataType.INTEGER)
    # text has permitted targets, so the message names them.
    assert "link or textarea" in str(exc.value)
    assert _stored_type(db_session, attr.id) == "text"


def test_type_without_conversions_cannot_be_retyped_with_records(db_session):
    _entity, attr = _attribute_with_records(db_session, DataType.INTEGER, ["8"])
    with pytest.raises(SchemaError, match="data type"):
        _update_type(db_session, attr, DataType.TEXT)
    assert _stored_type(db_session, attr.id) == "integer"


def test_permitted_data_types_with_records(db_session):
    _entity, attr = _attribute_with_records(db_session, DataType.TEXT, ["x"])
    assert permitted_data_types(db_session, attr) == {
        DataType.TEXT,
        DataType.LINK,
        DataType.TEXTAREA,
    }


def test_permitted_data_types_without_records_is_unrestricted(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER)
    )
    assert permitted_data_types(db_session, attr) == set(DataType)
