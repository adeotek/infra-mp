"""Service-level tests for CSV import/export."""

import csv
import io

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.csv_service import (
    _safe_cell,
    export_records_csv,
    import_record_rows,
    parse_csv_upload,
)
from app.services.record_service import create_record, list_records, resolve_reference_titles
from app.services.schema_service import (
    add_attribute,
    create_entity,
    get_entity_with_attributes,
)


@pytest.fixture
def csv_graph(db_session):
    """Site entity + Server with scalar, reference and many-reference attributes."""
    site = create_entity(db_session, EntityCreate(name="Site"))
    add_attribute(db_session, site, AttributeCreate(name="Name", data_type=DataType.TEXT))

    nic = create_entity(db_session, EntityCreate(name="NIC"))
    add_attribute(db_session, nic, AttributeCreate(name="IP", data_type=DataType.TEXT))

    server = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(
        db_session, server, AttributeCreate(name="Name", data_type=DataType.TEXT, is_required=True)
    )
    add_attribute(db_session, server, AttributeCreate(name="Cores", data_type=DataType.INTEGER))
    add_attribute(db_session, server, AttributeCreate(name="Online", data_type=DataType.BOOLEAN))
    add_attribute(
        db_session,
        server,
        AttributeCreate(name="Status", data_type=DataType.ENUM, options=["active", "retired"]),
    )
    add_attribute(
        db_session,
        server,
        AttributeCreate(
            name="Site",
            data_type=DataType.REFERENCE,
            reference_entity_id=site.id,
            cardinality="one",
        ),
    )
    add_attribute(
        db_session,
        server,
        AttributeCreate(
            name="NICs",
            data_type=DataType.REFERENCE,
            reference_entity_id=nic.id,
            cardinality="many",
        ),
    )

    site = get_entity_with_attributes(db_session, site.id)
    nic = get_entity_with_attributes(db_session, nic.id)
    server = get_entity_with_attributes(db_session, server.id)
    assert site is not None and nic is not None and server is not None
    s1 = create_record(db_session, site, site.attributes, {"name": "S1"})
    s2 = create_record(db_session, site, site.attributes, {"name": "S2"})
    n1 = create_record(db_session, nic, nic.attributes, {"ip": "10.0.0.1"})
    n2 = create_record(db_session, nic, nic.attributes, {"ip": "10.0.0.2"})
    return {
        "site": site,
        "nic": nic,
        "server": server,
        "s1": s1,
        "s2": s2,
        "n1": n1,
        "n2": n2,
    }


def _parse(text):
    return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def test_export_records_csv_round_trip_shapes(csv_graph, db_session):
    server = csv_graph["server"]
    create_record(
        db_session,
        server,
        server.attributes,
        {
            "name": "web01",
            "cores": 8,
            "online": True,
            "status": "active",
            "site": csv_graph["s1"].id,
            "nics": [csv_graph["n1"].id, csv_graph["n2"].id],
        },
    )
    titles = resolve_reference_titles(db_session, server)
    text = export_records_csv(server, list_records(db_session, server.id), titles)
    rows = _parse(text)
    assert rows[0] == ["Name", "Cores", "Online", "Status", "Site", "NICs"]
    assert rows[1][0] == "web01"
    assert rows[1][1] == "8"
    assert rows[1][2] == "true"
    assert rows[1][3] == "active"
    assert rows[1][4] == "S1"
    assert rows[1][5] == "10.0.0.1 | 10.0.0.2"


def test_export_records_csv_missing_values_are_empty(csv_graph, db_session):
    server = csv_graph["server"]
    create_record(db_session, server, server.attributes, {"name": "web02"})
    titles = resolve_reference_titles(db_session, server)
    rows = _parse(export_records_csv(server, list_records(db_session, server.id), titles))
    # Booleans always resolve to a value (checkbox semantics); everything else unset stays empty.
    assert rows[1] == ["web02", "", "false", "", "", ""]


def test_safe_cell_guards_formulas_but_keeps_numbers():
    assert _safe_cell("=cmd()") == "'=cmd()"
    assert _safe_cell("+1+1") == "'+1+1"
    assert _safe_cell("@foo") == "'@foo"
    assert _safe_cell("-5") == "-5"
    assert _safe_cell("-2+3+cmd") == "'-2+3+cmd"
    assert _safe_cell("plain") == "plain"


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #


def test_import_rows_creates_records(csv_graph, db_session):
    server = csv_graph["server"]
    rows = parse_csv_upload(
        b"Name,Cores,Online,Status\nweb01,8,true,active\nweb02,16,false,retired\n"
    )
    imported, errors = import_record_rows(db_session, server, rows)
    assert (imported, errors) == (2, [])
    names = sorted(r.data["name"] for r in list_records(db_session, server.id))
    assert names == ["web01", "web02"]


def test_import_matches_columns_by_name_and_slug(csv_graph, db_session):
    server = csv_graph["server"]
    rows = parse_csv_upload(b"name,CORES,online\nweb01,8,true\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert (imported, errors) == (1, [])
    record = list_records(db_session, server.id)[0]
    assert record.data["cores"] == 8
    assert record.data["online"] is True


def test_import_references_by_title_and_id(csv_graph, db_session):
    server = csv_graph["server"]
    rows = parse_csv_upload(b"Name,Site,NICs\nweb01,S2,10.0.0.1|10.0.0.2\nweb02,1,\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert (imported, errors) == (2, [])
    by_name = {r.data["name"]: r for r in list_records(db_session, server.id)}
    assert by_name["web01"].data["site"] == csv_graph["s2"].id
    assert by_name["web01"].data["nics"] == [csv_graph["n1"].id, csv_graph["n2"].id]
    assert by_name["web02"].data["site"] == csv_graph["s1"].id
    # Empty many-reference resolves to no value (key absent), like the record form.
    assert by_name["web02"].data.get("nics", []) == []


def test_import_all_or_nothing_on_row_error(csv_graph, db_session):
    server = csv_graph["server"]
    rows = parse_csv_upload(b"Name,Cores\nweb01,8\nweb02,notanumber\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert imported == 0
    assert len(errors) == 1
    assert "Row 3" in errors[0]
    assert "Cores" in errors[0]
    assert list_records(db_session, server.id) == []


def test_import_missing_required_column(csv_graph, db_session):
    server = csv_graph["server"]
    rows = parse_csv_upload(b"Cores\n8\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert imported == 0
    assert any("Name" in e for e in errors)


def test_import_unknown_reference_rejected(csv_graph, db_session):
    server = csv_graph["server"]
    rows = parse_csv_upload(b"Name,Site\nweb01,Nope\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert imported == 0
    assert any("unknown reference 'Nope'" in e for e in errors)


def test_import_unknown_columns_ignored(csv_graph, db_session):
    server = csv_graph["server"]
    rows = parse_csv_upload(b"Name,Extra Column\nweb01,whatever\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert (imported, errors) == (1, [])


def test_import_empty_rows_skipped(csv_graph, db_session):
    server = csv_graph["server"]
    rows = parse_csv_upload(b"Name\n\nweb01\n,\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert (imported, errors) == (1, [])


def test_import_unique_duplicate_in_csv_rejected(csv_graph, db_session):
    server = csv_graph["server"]
    add_attribute(
        db_session,
        server,
        AttributeCreate(name="Serial", data_type=DataType.TEXT, is_unique=True),
    )
    db_session.expire_all()  # refresh cached relationship collections after the commit
    server = get_entity_with_attributes(db_session, server.id)
    assert server is not None
    rows = parse_csv_upload(b"Name,Serial\nweb01,SN1\nweb02,SN1\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert imported == 0
    assert any("must be unique" in e for e in errors)
    assert list_records(db_session, server.id) == []


def test_import_reference_by_composite_key_title(csv_graph, db_session):
    # A reference cell carries the target's composite key ("A ^ B"); the
    # import resolves it back through the title index.
    server = csv_graph["server"]
    site = get_entity_with_attributes(db_session, csv_graph["site"].id)
    assert site is not None
    for attr in site.attributes:
        if attr.slug == "name":
            attr.is_key = True
    add_attribute(
        db_session, site, AttributeCreate(name="Region", data_type=DataType.TEXT, is_key=True)
    )
    db_session.expire_all()
    site = get_entity_with_attributes(db_session, site.id)
    assert site is not None
    s3 = create_record(db_session, site, site.attributes, {"name": "S3", "region": "EU"})

    db_session.expire_all()
    server = get_entity_with_attributes(db_session, server.id)
    assert server is not None
    rows = parse_csv_upload(b"Name,Site\nweb01,S3 ^ EU\n")
    imported, errors = import_record_rows(db_session, server, rows)
    assert (imported, errors) == (1, [])
    by_name = {r.data["name"]: r for r in list_records(db_session, server.id)}
    assert by_name["web01"].data["site"] == s3.id
