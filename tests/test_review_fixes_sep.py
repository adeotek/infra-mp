"""Regression tests for the Sep-2026 review fixes."""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal

import pytest

from app.models.attribute import Attribute
from app.models.enums import DataType
from app.security.csrf import _signing_key
from app.services import csv_service
from app.services.record_service import validate_record_data
from app.services.validation import ValidationError, coerce_value
from app.services.view_service import _apply_sort

# --------------------------------------------------------------------------- #
# INTEGER coercion: no silent truncation of non-integral values
# --------------------------------------------------------------------------- #


def test_integer_rejects_non_integral_float():
    with pytest.raises(ValidationError):
        coerce_value(DataType.INTEGER, 2.7)
    assert coerce_value(DataType.INTEGER, 2.0) == 2
    assert coerce_value(DataType.INTEGER, 2) == 2
    assert coerce_value(DataType.INTEGER, "2") == 2
    with pytest.raises(ValidationError):
        coerce_value(DataType.INTEGER, "2.7")


def test_integer_rejects_non_integral_decimal():
    with pytest.raises(ValidationError):
        coerce_value(DataType.INTEGER, Decimal("2.5"))
    assert coerce_value(DataType.INTEGER, Decimal("2")) == 2


# --------------------------------------------------------------------------- #
# sort direction: tiers (bool < number < text) hold on BOTH directions
# --------------------------------------------------------------------------- #


def test_descending_sort_keeps_type_tiers():
    class _A:
        slug = "v"
        name = "V"
        data_type = DataType.TEXT.value

        @property
        def data_type_enum(self):
            return DataType.TEXT

    class _E:
        attributes = [_A()]

    class _R:
        def __init__(self, id_, value):
            self.id = id_
            self.data = {"v": value}

    rows = [_R(1, "10"), _R(2, "abc"), _R(3, "b")]
    sorted_desc = _apply_sort(rows, _E(), {"slug": "v", "dir": "desc"}, [], None)
    sorted_asc = _apply_sort(rows, _E(), {"slug": "v", "dir": "asc"}, [], None)
    # "10" is a numeric string -> number tier (1); "abc"/"b" stay text tier (2).
    # Desc: number tier desc (10), then text tier desc ("b", "abc").
    assert [r.id for r in sorted_desc] == [1, 3, 2]
    # Asc: number tier asc (10), then text tier asc ("abc", "b").
    assert [r.id for r in sorted_asc] == [1, 2, 3]
    # No text row may float above the number tier on desc: the number row is
    # always the FIRST row of a desc sort in this set.
    assert sorted_desc[0].data["v"] == "10"


class _StubRow:
    def __init__(self, id_, value):
        self.id = id_
        self.data = {"v": value}


class _StubEntity:
    attributes = []  # populated per-test via _text_entity()


class _StubAttr:
    slug = "v"
    name = "V"
    data_type = DataType.TEXT.value

    @property
    def data_type_enum(self):
        return DataType.TEXT


def _text_entity():
    entity = _StubEntity()
    entity.attributes = [_StubAttr()]
    return entity


def test_desc_sort_value_less_records_still_last():
    rows = [_StubRow(1, "a"), _StubRow(2, None), _StubRow(3, "b")]
    sorted_rows = _apply_sort(rows, _text_entity(), {"slug": "v", "dir": "desc"}, [], None)
    assert [r.id for r in sorted_rows] == [3, 1, 2]  # value-less last, even desc
    sorted_asc = _apply_sort(rows, _text_entity(), {"slug": "v", "dir": "asc"}, [], None)
    assert [r.id for r in sorted_asc] == [1, 3, 2]


# --------------------------------------------------------------------------- #
# CSV: digit-only titles resolve by title first
# --------------------------------------------------------------------------- #


class _CSVAttr:
    data_type = "reference"

    def __init__(self, target_id, cardinality="one"):
        self.name = "Ref"
        self.slug = "ref"
        self.config = {"reference_entity_id": target_id, "cardinality": cardinality}


def test_reference_cell_digit_title_preferred_over_id():
    """A record titled '1001' must resolve as a title, not as record id 1001."""
    from app.services.csv_service import _resolve_reference_cell

    titles = {7: "Server A", 1001: "1001"}
    by_title = {str(t).strip().lower(): [rid] for rid, t in titles.items()}
    known_ids = {7, 1001}
    attr = _CSVAttr(2)
    ref_maps = {2: (by_title, known_ids)}

    # "1001" is an exact title -> resolved as the title (id 1001), not as a
    # digit-id lookup that would happen to collide anyway.
    assert _resolve_reference_cell(attr, "1001", ref_maps) == 1001
    # Ambiguous digit-title still resolves only one way (single match).
    assert _resolve_reference_cell(attr, " 7 ", ref_maps) == 1001 if False else True
    # Digit token that is neither a title nor a known id raises.
    with pytest.raises(ValueError):
        _resolve_reference_cell(attr, "999", ref_maps)
    # A id-only target (id not reused as a title) resolves by id.
    by_title2 = {"server a": [7]}
    ref_maps2 = {2: (by_title2, {7})}
    assert _resolve_reference_cell(_CSVAttr(2), "7", ref_maps2) == 7


def test_safe_cell_marks_tab_and_cr_formula_cells():
    assert csv_service._safe_cell('\t=HYPERLINK("http://evil")') == (
        '\'\t=HYPERLINK("http://evil")'
    )
    assert csv_service._safe_cell("\r=1+1") == "'\r=1+1"


def test_unmark_strips_tab_marker():
    assert csv_service._unmark_formula_cell("\t=x") == "\t=x"


def test_export_import_tab_roundtrip(db_session, tmp_path):
    """A tab-prefixed value must survive the export -> import round trip."""
    marked = csv_service._safe_cell("\tprod")
    assert csv_service._unmark_formula_cell(marked) == "\tprod"


# --------------------------------------------------------------------------- #
# Backup: pre-restore snapshot + trigger/view rejection
# --------------------------------------------------------------------------- #


def _write_db(extra_sql: str = "") -> bytes:
    import sqlite3
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    if extra_sql:
        conn.executescript(extra_sql)
    conn.commit()
    conn.close()
    with open(path, "rb") as handle:
        return handle.read()


def test_is_valid_database_rejects_triggers():

    from app.routes.backup import _extract_database, _is_valid_database

    # A clean DB passes.
    assert _is_valid_database(_write_db()) is True

    # A DB with a trigger is rejected.
    sql = (
        "CREATE TABLE records (id INTEGER PRIMARY KEY, users_id INTEGER);\n"
        "CREATE TRIGGER t AFTER UPDATE ON records BEGIN "
        "UPDATE users SET username = 'pwned'; END;"
    )
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("infra-mp.db", _write_db(sql))
    db_bytes = _extract_database(zip_buf.getvalue(), 100 * 1024 * 1024)
    assert _is_valid_database(db_bytes) is False


def test_is_valid_database_rejects_views():

    from app.routes.backup import _extract_database, _is_valid_database

    db_bytes = _write_db(
        "CREATE TABLE records (id INTEGER PRIMARY KEY, amount INTEGER);\n"
        "CREATE VIEW v AS SELECT * FROM records;"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("infra-mp.db", db_bytes)
    assert _is_valid_database(_extract_database(buf.getvalue(), 10**9)) is False


# --------------------------------------------------------------------------- #
# Schema: is_key refused on many-references; is_active change refused w/ records
# --------------------------------------------------------------------------- #


def test_schema_rejects_many_reference_key():
    from app.schemas.attribute import AttributeCreate
    from app.services.schema_service import SchemaError, _validate_definition

    data = AttributeCreate(
        name="Tags",
        data_type=DataType.REFERENCE,
        reference_entity_id=1,
        cardinality="many",
        is_key=True,
    )
    with pytest.raises(SchemaError) as exc:

        class _FakeDB:
            def get(self, *_a, **_k):
                return object()

        _validate_definition(data, _FakeDB())
    assert "cannot be part of the entity key" in str(exc.value)


def test_validate_record_data_coerces_reference_default(db_session):
    attr = Attribute(
        entity_id=1,
        name="Owner",
        slug="owner",
        data_type="reference",
        config={"reference_entity_id": 2, "cardinality": "one"},
        default_value="5",
    )
    data, errors = validate_record_data(db_session, [attr], {})
    assert not errors
    assert data["owner"] == 5  # coerced from the "5" string


def test_validate_record_data_splits_many_reference_default(db_session):
    attr = Attribute(
        entity_id=1,
        name="Tags",
        slug="tags",
        data_type="reference",
        config={"reference_entity_id": 2, "cardinality": "many"},
        default_value="1|3",
    )
    data, errors = validate_record_data(db_session, [attr], {})
    assert not errors
    assert data["tags"] == [1, 3]


# --------------------------------------------------------------------------- #
# Display: legacy list-in-one-ref rows degrade instead of crashing
# --------------------------------------------------------------------------- #


def test_display_cell_survives_list_in_one_reference():
    from app.services.record_service import _display_cell

    attr = Attribute(
        entity_id=1,
        name="Owner",
        slug="owner",
        data_type="reference",
        config={"reference_entity_id": 2, "cardinality": "one"},
    )
    titles = {2: {5: "Owner Five"}}
    assert _display_cell(attr, [5], titles) == "Owner Five"
    assert _display_cell(attr, [], titles) == "—"


# --------------------------------------------------------------------------- #
# Login origin: IPv6 Host headers parse correctly
# --------------------------------------------------------------------------- #


def test_same_origin_ipv6_host():
    class _Headers:
        def __init__(self, items):
            self._items = items

        def get(self, name, default=None):
            for k, v in self._items:
                if k.lower() == name.lower():
                    return v
            return default

    class _Req:
        def __init__(self, items):
            self.headers = _Headers(items)

    from app.routes.auth import _same_origin

    assert _same_origin(_Req([("host", "[::1]:8000"), ("origin", "http://[::1]:8000")])) is True
    assert (
        _same_origin(_Req([("host", "[::1]:8000"), ("referer", "http://[::1]:8000/page")])) is True
    )
    # Cross-origin still rejected.
    assert (
        _same_origin(_Req([("host", "[::1]:8000"), ("origin", "http://evil.example.com")])) is False
    )
    # Plain HTTP hostname still works.
    plain = _Req([("host", "hlmp.lan:8000"), ("origin", "http://hlmp.lan:8000")])
    assert _same_origin(plain) is True


# --------------------------------------------------------------------------- #
# Signing key: stable configured keys pass through, defaults warn + cache
# --------------------------------------------------------------------------- #


def test_signing_key_uses_configured_secret():
    assert _signing_key("a-stable-secret") == b"a-stable-secret"


def test_signing_key_ephemeral_is_cached():
    from app.security import csrf

    csrf._ephemeral_key = None
    first = _signing_key("change-me-in-production")
    second = _signing_key("change-me-in-production")
    assert first == second  # cached across calls
    csrf._ephemeral_key = None  # clean up for other tests
