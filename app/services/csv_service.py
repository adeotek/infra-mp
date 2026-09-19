"""CSV import/export for records and saved views."""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.attribute import Attribute
from app.models.entity import Entity
from app.models.enums import DataType
from app.models.record import Record
from app.services.record_service import (
    active_attributes,
    build_record_titles,
    canonical_key_values,
    list_records,
    unique_value_key,
    validate_record_data,
)
from app.services.validation import ValidationError, coerce_value

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# Separators accepted for multiple reference values in one CSV cell.
_REF_SEPARATORS = re.compile(r"[|;]")
# A leading "-" that parses as a number is data, not a formula.
_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def parse_csv_upload(contents: bytes) -> list[list[str]]:
    """Decode an uploaded CSV (UTF-8, BOM-tolerant) into rows of cells.

    Raises ``UnicodeDecodeError`` for non-UTF-8 input.
    """
    text = contents.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def export_records_csv(
    entity: Entity, records: list[Record], titles: dict[int, dict[int, str]]
) -> str:
    """CSV for an entity's records: one column per attribute (header = name).

    Values use their display form (reference titles, ``true``/``false``,
    `` | ``-joined titles for multiple references) so the file round-trips
    through the importer.
    """
    headers = [a.name for a in entity.attributes]
    body = [
        [_export_cell(a, r.data.get(a.slug), titles) for a in entity.attributes] for r in records
    ]
    return _write_csv(headers, body)


def export_view_csv(columns: list[Any], rows: list[dict[str, Any]]) -> str:
    """CSV for a view: the resolved columns exactly as displayed."""
    headers = [c.label for c in columns]
    body = [[row["cells"].get(c.key, "") for c in columns] for row in rows]
    return _write_csv(headers, body)


def _export_cell(attr: Attribute, value: Any, titles: dict[int, dict[int, str]]) -> str:
    if attr.data_type == DataType.REFERENCE.value:
        target_titles = titles.get(attr.config.get("reference_entity_id"), {})
        if value is None:
            return ""
        ids = value if isinstance(value, list) else [value]
        return " | ".join(target_titles.get(i, f"#{i}") for i in ids)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _write_csv(headers: list[str], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([_safe_cell(h) for h in headers])
    for row in rows:
        writer.writerow([_safe_cell(c) for c in row])
    # BOM so spreadsheet apps detect UTF-8.
    return "\ufeff" + buf.getvalue()


def _safe_cell(value: Any) -> str:
    """Guard against spreadsheet formula injection, keeping numbers intact."""
    cell = str(value)
    if cell.startswith(("=", "+", "@")):
        return "'" + cell
    if cell.startswith("-") and not _NUMERIC.match(cell):
        return "'" + cell
    return cell


def _unmark_formula_cell(cell: str) -> str:
    """Strip the export-time formula-injection apostrophe marker on import.

    ``_safe_cell`` prefixes formula-looking values with a literal apostrophe
    so spreadsheets open them as text; keeping that apostrophe on import would
    corrupt the export -> import round trip (``=prod`` stored as ``'=prod``).
    Only the exact marker pattern is stripped — a value a user actually typed
    with a leading apostrophe is preserved.
    """
    if cell.startswith("'") and len(cell) > 1:
        rest = cell[1:]
        if rest.startswith(("=", "+", "@")) or (rest.startswith("-") and not _NUMERIC.match(rest)):
            return rest
    return cell


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #


def import_record_rows(
    db: Session,
    entity: Entity,
    csv_rows: list[list[str]],
    user_id: int | None = None,
) -> tuple[int, int, list[str]]:
    """Import CSV rows into an entity, all-or-nothing.

    When the entity has key attributes, the key decides whether a row
    creates a record or updates the existing one with the same key: only
    the columns present in the CSV are written — other attributes keep
    their values, and an empty cell clears the column's value. When several
    existing records share a key (legacy data), the newest one is updated.
    Entities without a key always create.

    Returns ``(created_count, updated_count, errors)``. Any row error rolls
    back every pending change; errors carry the CSV row number (header =
    row 1).
    """
    if not csv_rows or not any((cell or "").strip() for cell in csv_rows[0]):
        return 0, 0, ["The CSV file has no header row."]
    header = csv_rows[0]
    attributes = active_attributes(entity.attributes)

    mapping: dict[Attribute, int] = {}
    unknown: list[str] = []
    used: set[str] = set()
    for index, column in enumerate(header):
        name = (column or "").strip()
        if not name:
            continue
        match = None
        for attr in attributes:
            if attr.slug.lower() == name.lower():
                match = attr
                break
        if match is None:
            for attr in attributes:
                if attr.name.lower() == name.lower():
                    match = attr
                    break
        if match is None or match.slug in used:
            unknown.append(name)
            continue
        mapping[match] = index
        used.add(match.slug)

    missing_required = [a.name for a in attributes if a.is_required and a.slug not in used]
    if missing_required:
        return 0, 0, [f"Missing required column(s): {', '.join(missing_required)}"]

    ref_maps: dict[int, tuple[dict[str, list[int]], set[int]]] = {}
    for attr in attributes:
        if attr.data_type == DataType.REFERENCE.value:
            target_id = attr.config.get("reference_entity_id")
            if target_id is not None and target_id not in ref_maps:
                ref_maps[target_id] = _title_index(db, target_id)

    # Upsert lookup: key tuple -> existing record (newest kept for legacy
    # duplicates). list_records returns newest first, setdefault keeps it.
    key_attrs = [a for a in attributes if a.is_key]
    records_by_key: dict[tuple[Any, ...], Record] = {}
    if key_attrs:
        for record in list_records(db, entity.id):
            records_by_key.setdefault(canonical_key_values(record, key_attrs), record)
    # Load the entity's records once and reuse the list across rows so
    # validation stays O(rows) instead of re-querying per row.
    existing_cache = list(list_records(db, entity.id))

    # Prebuilt O(1) lookup maps so unique/key checks stay constant-time per
    # row (a linear scan over existing_cache would make a large import
    # quadratic in the number of records). Both are kept in sync below as
    # rows are created/updated.
    unique_attrs = [a for a in attributes if a.is_unique]
    unique_index: dict[tuple[Any, Any], int] = {}
    for attr in unique_attrs:
        for record in existing_cache:
            value = record.data.get(attr.slug)
            if value is None or isinstance(value, list):
                continue
            index_key = unique_value_key(attr, value)
            if index_key is not None:
                unique_index.setdefault((attr.slug, index_key), record.id)
    key_index: dict[tuple[Any, ...], int] = (
        {canonical_key_values(record, key_attrs): record.id for record in existing_cache}
        if key_attrs
        else {}
    )

    errors: list[str] = []
    created = 0
    updated = 0
    try:
        for row_number, row in enumerate(csv_rows[1:], start=2):
            if not any((cell or "").strip() for cell in row):
                continue
            raw: dict[str, Any] = {}
            row_errors: list[str] = []
            for attr, index in mapping.items():
                cell = row[index].strip() if index < len(row) else ""
                cell = _unmark_formula_cell(cell)
                if attr.data_type == DataType.REFERENCE.value:
                    try:
                        raw[attr.slug] = _resolve_reference_cell(attr, cell, ref_maps)
                    except ValueError as exc:
                        row_errors.append(f"{attr.name}: {exc}")
                else:
                    raw[attr.slug] = cell
            if row_errors:
                errors.append(f"Row {row_number}: {'; '.join(row_errors)}")
                continue

            # Coerce the row's key values (canonical form) to find a match.
            existing: Record | None = None
            if key_attrs:
                key_values: list[Any] = []
                key_error: str | None = None
                for attr in key_attrs:
                    try:
                        key_values.append(coerce_value(attr.data_type_enum, raw.get(attr.slug)))
                    except ValidationError as exc:
                        key_error = f"{attr.name}: {exc}"
                        break
                if key_error:
                    errors.append(f"Row {row_number}: {key_error}")
                    continue
                existing = records_by_key.get(_canonical_from_values(key_values, key_attrs))

            if existing is None:
                data, validation_errors = validate_record_data(
                    db,
                    attributes,
                    raw,
                    existing_records=existing_cache,
                    unique_index=unique_index if unique_attrs else None,
                    key_index=key_index if key_attrs else None,
                )
                if validation_errors:
                    errors.append(
                        f"Row {row_number}: {'; '.join(msg for _, msg in validation_errors)}"
                    )
                    continue
                record = Record(
                    entity_id=entity.id,
                    data=data,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(record)
                db.flush()
                existing_cache.append(record)
                records_by_key.setdefault(canonical_key_values(record, key_attrs), record)
                if key_attrs:
                    key_index[canonical_key_values(record, key_attrs)] = record.id
                for attr in unique_attrs:
                    value = data.get(attr.slug)
                    if isinstance(value, list):
                        continue
                    index_key = unique_value_key(attr, value) if value is not None else None
                    if index_key is not None:
                        unique_index[(attr.slug, index_key)] = record.id
                created += 1
            else:
                # Update: merge the CSV columns over the existing values so
                # attributes absent from the file are preserved. Validate the
                # merged state (self excluded; key check handled by lookup).
                merged_raw = {a.slug: existing.data.get(a.slug) for a in attributes}
                merged_raw.update(raw)
                data, validation_errors = validate_record_data(
                    db,
                    attributes,
                    merged_raw,
                    exclude_record_id=existing.id,
                    enforce_key=False,
                    existing_records=existing_cache,
                    unique_index=unique_index if unique_attrs else None,
                    key_index=key_index if key_attrs else None,
                )
                if validation_errors:
                    errors.append(
                        f"Row {row_number}: {'; '.join(msg for _, msg in validation_errors)}"
                    )
                    continue
                old_key = canonical_key_values(existing, key_attrs)
                old_unique = {attr.slug: existing.data.get(attr.slug) for attr in unique_attrs}
                existing.data = data
                existing.updated_by = user_id
                db.flush()
                if key_attrs:
                    new_key = canonical_key_values(existing, key_attrs)
                    if old_key in key_index and key_index[old_key] == existing.id:
                        del key_index[old_key]
                    key_index[new_key] = existing.id
                    # Keep the upsert map in sync: a key change must re-point
                    # it, or later rows carrying the OLD key would silently
                    # merge into this record instead of finding/creating the
                    # record the new key identifies.
                    if old_key in records_by_key and records_by_key[old_key] is existing:
                        del records_by_key[old_key]
                    records_by_key[new_key] = existing
                for attr in unique_attrs:
                    old_value = old_unique.get(attr.slug)
                    new_value = data.get(attr.slug)
                    if not isinstance(old_value, list) and old_value is not None:
                        old_key_value = unique_value_key(attr, old_value)
                        if (
                            old_key_value is not None
                            and unique_index.get((attr.slug, old_key_value)) == existing.id
                        ):
                            del unique_index[(attr.slug, old_key_value)]
                    if isinstance(new_value, list):
                        continue
                    new_index_key = (
                        unique_value_key(attr, new_value) if new_value is not None else None
                    )
                    if new_index_key is not None:
                        unique_index[(attr.slug, new_index_key)] = existing.id
                updated += 1
    except Exception:
        logger.exception("CSV import failed unexpectedly")
        db.rollback()
        return 0, 0, ["Import failed unexpectedly; nothing was imported."]

    if errors:
        db.rollback()
        return 0, 0, errors
    db.commit()
    return created, updated, []


def _canonical_from_values(values: list[Any], key_attrs: list[Attribute]) -> tuple[Any, ...]:
    """Normalise coerced key values to match ``canonical_key_values``.

    Only DECIMAL-typed keys convert to ``Decimal``; TEXT keys like "123" must
    stay strings so they match their stored values.
    """
    from decimal import Decimal, InvalidOperation

    normalised: list[Any] = []
    for attr, value in zip(key_attrs, values, strict=True):
        if attr.data_type_enum == DataType.DECIMAL and isinstance(value, str):
            try:
                normalised.append(Decimal(value))
                continue
            except InvalidOperation:
                pass
        normalised.append(value)
    return tuple(normalised)


def _title_index(db: Session, target_id: int) -> tuple[dict[str, list[int]], set[int]]:
    """Map lowercased titles -> record ids (plus the known id set) for lookups."""
    titles = build_record_titles(db, target_id)
    by_title: dict[str, list[int]] = {}
    for record_id, title in titles.items():
        by_title.setdefault(str(title).strip().lower(), []).append(record_id)
    return by_title, set(titles)


def _resolve_reference_cell(
    attr: Attribute,
    cell: str,
    ref_maps: dict[int, tuple[dict[str, list[int]], set[int]]],
) -> Any:
    """Resolve a CSV cell for a reference attribute into record id(s).

    Accepts numeric ids (must exist) or record titles (case-insensitive,
    must be unambiguous). Multiple values for ``many`` references are
    separated by ``|`` or ``;``.
    """
    by_title, known_ids = ref_maps.get(attr.config.get("reference_entity_id"), ({}, set()))
    cardinality = attr.config.get("cardinality", "one")
    tokens = [cell] if cardinality == "one" else _REF_SEPARATORS.split(cell)

    resolved: list[int] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            record_id = int(token)
            if record_id in known_ids:
                resolved.append(record_id)
                continue
            raise ValueError(f"unknown reference '{token}'")
        matches = by_title.get(token.lower(), [])
        if not matches:
            raise ValueError(f"unknown reference '{token}'")
        if len(matches) > 1:
            raise ValueError(f"ambiguous reference '{token}'")
        resolved.append(matches[0])

    if cardinality == "one":
        if len(resolved) > 1:
            raise ValueError("expected a single value")
        return resolved[0] if resolved else None
    return resolved
