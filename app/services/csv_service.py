"""CSV import/export for records and saved views."""

from __future__ import annotations

import csv
import io
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
    validate_record_data,
)

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


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #


def import_record_rows(
    db: Session,
    entity: Entity,
    csv_rows: list[list[str]],
    user_id: int | None = None,
) -> tuple[int, list[str]]:
    """Import CSV rows into an entity, all-or-nothing.

    Returns ``(imported_count, errors)``. Any row error rolls back every
    pending insert; errors carry the CSV row number (header = row 1).
    """
    if not csv_rows or not any((cell or "").strip() for cell in csv_rows[0]):
        return 0, ["The CSV file has no header row."]
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
        return 0, [f"Missing required column(s): {', '.join(missing_required)}"]

    ref_maps: dict[int, tuple[dict[str, list[int]], set[int]]] = {}
    for attr in attributes:
        if attr.data_type == DataType.REFERENCE.value:
            target_id = attr.config.get("reference_entity_id")
            if target_id is not None and target_id not in ref_maps:
                ref_maps[target_id] = _title_index(db, target_id)

    errors: list[str] = []
    created = 0
    try:
        for row_number, row in enumerate(csv_rows[1:], start=2):
            if not any((cell or "").strip() for cell in row):
                continue
            raw: dict[str, Any] = {}
            row_errors: list[str] = []
            for attr, index in mapping.items():
                cell = row[index].strip() if index < len(row) else ""
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
            data, validation_errors = validate_record_data(db, attributes, raw)
            if validation_errors:
                errors.append(f"Row {row_number}: {'; '.join(validation_errors)}")
                continue
            db.add(
                Record(
                    entity_id=entity.id,
                    data=data,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            db.flush()
            created += 1
    except Exception:
        db.rollback()
        return 0, ["Import failed unexpectedly; nothing was imported."]

    if errors:
        db.rollback()
        return 0, errors
    db.commit()
    return created, []


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
