"""Record CRUD routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_capability
from app.auth.permissions import (
    CREATE_RECORD,
    DELETE_RECORD,
    UPDATE_RECORD,
    has_capability,
)
from app.db import get_session
from app.flash import redirect_with_flash
from app.form import parse_form
from app.models.record import Record
from app.models.user import User
from app.services.csv_service import (
    MAX_UPLOAD_BYTES,
    export_records_csv,
    import_record_rows,
    parse_csv_upload,
)
from app.services.record_service import (
    RecordError,
    best_effort_coerce,
    build_rows,
    create_record,
    get_record,
    list_records,
    reference_options,
    resolve_reference_titles,
    soft_delete_record,
    update_record,
    username_map,
)
from app.services.schema_service import get_entity_with_attributes
from app.templates import render

router = APIRouter()


@router.get("/entities/{entity_id}/records")
def records_index(
    request: Request,
    entity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    records = list_records(db, entity_id)
    titles = resolve_reference_titles(db, entity)
    return render(
        request,
        "records/list.html",
        {
            "entity": entity,
            "rows": build_rows(entity, records, titles),
            "user_names": username_map(db),
            "can_create": has_capability(user, CREATE_RECORD),
            "can_update": has_capability(user, UPDATE_RECORD),
            "can_delete": has_capability(user, DELETE_RECORD),
        },
    )


@router.get("/entities/{entity_id}/records/export")
def export_records(
    request: Request,
    entity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    titles = resolve_reference_titles(db, entity)
    csv_text = export_records_csv(entity, list_records(db, entity_id), titles)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{entity.slug}-records.csv"'},
    )


@router.get("/entities/{entity_id}/records/import")
def import_records_page(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(CREATE_RECORD)),
    db: Session = Depends(get_session),
):
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    return render(request, "records/import.html", {"entity": entity})


@router.post("/entities/{entity_id}/records/import")
async def import_records_post(
    request: Request,
    entity_id: int,
    file: Annotated[UploadFile, File(...)],
    user: User = Depends(require_capability(CREATE_RECORD)),
    db: Session = Depends(get_session),
):
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    target = f"/entities/{entity_id}/records"
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        return redirect_with_flash(target, "Import aborted: the file is larger than 5 MB.", "error")
    try:
        rows = parse_csv_upload(contents)
    except UnicodeDecodeError:
        return redirect_with_flash(
            target, "Import aborted: the file must be UTF-8 encoded CSV.", "error"
        )
    imported, errors = import_record_rows(db, entity, rows, user_id=user.id)
    if errors:
        detail = "; ".join(errors[:5])
        if len(errors) > 5:
            detail += f" (and {len(errors) - 5} more)"
        return redirect_with_flash(
            target, f"Import aborted — nothing was changed. {detail}", "error"
        )
    return redirect_with_flash(target, f"Imported {imported} record(s).")


@router.get("/entities/{entity_id}/records/new")
def new_record_page(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(CREATE_RECORD)),
    db: Session = Depends(get_session),
):
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    return render(
        request,
        "records/form.html",
        {
            "entity": entity,
            "record": None,
            "current": None,
            "ref_options": reference_options(db, entity),
            "action_url": f"/entities/{entity_id}/records",
        },
    )


@router.post("/entities/{entity_id}/records")
async def create_record_post(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(CREATE_RECORD)),
    db: Session = Depends(get_session),
):
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    raw = await parse_form(request)
    try:
        create_record(db, entity, entity.attributes, raw, user_id=user.id)
    except RecordError as exc:
        return _render_form_error(request, db, entity, None, raw, str(exc))

    return redirect_with_flash(f"/entities/{entity_id}/records", "Record created.")


@router.get("/records/{record_id}/edit")
def edit_record_page(
    request: Request,
    record_id: int,
    user: User = Depends(require_capability(UPDATE_RECORD)),
    db: Session = Depends(get_session),
):
    record = get_record(db, record_id)
    if record is None:
        raise HTTPException(status_code=404)
    entity = get_entity_with_attributes(db, record.entity_id)
    user_names = username_map(db)
    return render(
        request,
        "records/form.html",
        {
            "entity": entity,
            "record": record,
            "current": record.data,
            "ref_options": reference_options(db, entity),
            "action_url": f"/records/{record_id}/edit",
            "created_by_name": user_names.get(record.created_by, "—"),
            "updated_by_name": user_names.get(record.updated_by, "—"),
        },
    )


@router.post("/records/{record_id}/edit")
async def update_record_post(
    request: Request,
    record_id: int,
    user: User = Depends(require_capability(UPDATE_RECORD)),
    db: Session = Depends(get_session),
):
    record = get_record(db, record_id)
    if record is None:
        raise HTTPException(status_code=404)
    entity = get_entity_with_attributes(db, record.entity_id)
    raw = await parse_form(request)
    try:
        update_record(db, record, entity.attributes, raw, user_id=user.id)
    except RecordError as exc:
        return _render_form_error(request, db, entity, record, raw, str(exc))

    return redirect_with_flash(f"/entities/{entity.id}/records", "Record updated.")


@router.post("/records/{record_id}/delete")
def delete_record_post(
    request: Request,
    record_id: int,
    user: User = Depends(require_capability(DELETE_RECORD)),
    db: Session = Depends(get_session),
):
    record = get_record(db, record_id)
    if record is None:
        raise HTTPException(status_code=404)
    soft_delete_record(db, record)
    return redirect_with_flash(f"/entities/{record.entity_id}/records", "Record deleted.")


def _render_form_error(
    request: Request,
    db: Session,
    entity,
    record: Record | None,
    raw: dict[str, Any],
    error: str,
):
    context = {
        "entity": entity,
        "record": record,
        "current": best_effort_coerce(entity.attributes, raw),
        "ref_options": reference_options(db, entity),
        "action_url": (
            f"/entities/{entity.id}/records" if record is None else f"/records/{record.id}/edit"
        ),
        "error": error,
    }
    if record is not None:
        user_names = username_map(db)
        context["created_by_name"] = user_names.get(record.created_by, "—")
        context["updated_by_name"] = user_names.get(record.updated_by, "—")
    return render(request, "records/form.html", context, status_code=400)
