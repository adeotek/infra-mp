"""Saved view routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_capability
from app.auth.permissions import MANAGE_VIEWS, has_capability
from app.db import get_session
from app.flash import redirect_with_flash
from app.form import parse_form, to_list
from app.models.entity import Entity
from app.models.user import User
from app.models.view import View
from app.services.record_service import list_records
from app.services.schema_service import get_entity_with_attributes, list_entities
from app.services.view_service import (
    FILTER_OPS,
    apply_config,
    build_view_graph,
    build_view_rows,
    create_view,
    delete_view,
    filter_op_label,
    get_view,
    list_views,
    parse_column_spec,
    update_view,
)
from app.templates import render

router = APIRouter()


def _config_from_form(raw: dict) -> dict:
    column_specs = []
    for value in to_list(raw.get("col")):
        spec = parse_column_spec(value)
        if spec is not None:
            column_specs.append(spec)
    if not column_specs:
        # Legacy form: flat base-attribute slugs.
        column_specs = [v for v in to_list(raw.get("columns")) if v.strip()]
    sort_slug = raw.get("sort_slug")
    sort_dir = raw.get("sort_dir") if raw.get("sort_dir") in ("asc", "desc") else "asc"

    filters = []
    slugs = to_list(raw.get("filter_slug"))
    ops = to_list(raw.get("filter_op"))
    values = to_list(raw.get("filter_value"))
    for i, slug in enumerate(slugs):
        if not slug:
            continue
        filters.append(
            {
                "slug": slug,
                "op": ops[i] if i < len(ops) else "eq",
                "value": values[i] if i < len(values) else "",
            }
        )

    config: dict = {"columns": column_specs, "filters": filters}
    if sort_slug:
        config["sort"] = {"slug": sort_slug, "dir": sort_dir}
    return config


def _icon_from_form(raw: dict) -> str:
    # Free text: any value is accepted and normalised to an `fa-*` class at
    # render time by the `icon_class` Jinja filter (same as entity icons).
    return str(raw.get("icon", "")).strip()


def _view_form_context(db: Session, entity: Entity, view: View | None) -> dict:
    return {
        "entity": entity,
        "view": view,
        "entities": list_entities(db),
        "filter_ops": FILTER_OPS,
        "filter_op_label": filter_op_label,
        "current_config": view.config if view else None,
        "view_graph": build_view_graph(db, entity.id),
    }


@router.get("/views")
def views_index(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    return render(
        request,
        "views/list.html",
        {
            "views": list_views(db),
            "can_manage_views": has_capability(user, MANAGE_VIEWS),
        },
    )


@router.get("/views/new")
def new_view_page(
    request: Request,
    user: User = Depends(require_capability(MANAGE_VIEWS)),
    db: Session = Depends(get_session),
    entity_id: int | None = None,
):
    if entity_id is not None:
        entity = get_entity_with_attributes(db, entity_id)
        if entity is None:
            raise HTTPException(status_code=404)
        return render(request, "views/form.html", _view_form_context(db, entity, None))

    # Step 1: pick an entity.
    return render(
        request,
        "views/choose_entity.html",
        {"entities": list_entities(db)},
    )


@router.post("/views")
async def create_view_post(
    request: Request,
    user: User = Depends(require_capability(MANAGE_VIEWS)),
    db: Session = Depends(get_session),
):
    raw = await parse_form(request)
    entity_id = int(raw.get("entity_id"))
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    name = str(raw.get("name", "")).strip()
    if not name:
        return render(
            request,
            "views/form.html",
            {**_view_form_context(db, entity, None), "error": "Name is required."},
            status_code=400,
        )
    view = create_view(
        db, entity, name, _config_from_form(raw), icon=_icon_from_form(raw), user_id=user.id
    )
    return redirect_with_flash(f"/views/{view.id}", f"View '{view.name}' created.")


@router.get("/views/{view_id}")
def view_detail(
    request: Request,
    view_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    view = get_view(db, view_id)
    if view is None:
        raise HTTPException(status_code=404)
    entity = get_entity_with_attributes(db, view.entity_id)
    records, columns = apply_config(
        entity, list_records(db, view.entity_id), view.config, list_entities(db)
    )
    rows = build_view_rows(db, entity, records, columns)
    return render(
        request,
        "views/detail.html",
        {
            "view": view,
            "entity": entity,
            "columns": columns,
            "rows": rows,
            "can_manage_views": has_capability(user, MANAGE_VIEWS),
        },
    )


@router.get("/views/{view_id}/edit")
def edit_view_page(
    request: Request,
    view_id: int,
    user: User = Depends(require_capability(MANAGE_VIEWS)),
    db: Session = Depends(get_session),
):
    view = get_view(db, view_id)
    if view is None:
        raise HTTPException(status_code=404)
    entity = get_entity_with_attributes(db, view.entity_id)
    return render(request, "views/form.html", _view_form_context(db, entity, view))


@router.post("/views/{view_id}/edit")
async def update_view_post(
    request: Request,
    view_id: int,
    user: User = Depends(require_capability(MANAGE_VIEWS)),
    db: Session = Depends(get_session),
):
    view = get_view(db, view_id)
    if view is None:
        raise HTTPException(status_code=404)
    entity = get_entity_with_attributes(db, view.entity_id)
    raw = await parse_form(request)
    name = str(raw.get("name", "")).strip()
    if not name:
        return render(
            request,
            "views/form.html",
            {**_view_form_context(db, entity, view), "error": "Name is required."},
            status_code=400,
        )
    update_view(db, view, name, _config_from_form(raw), icon=_icon_from_form(raw))
    return redirect_with_flash(f"/views/{view.id}", f"View '{view.name}' updated.")


@router.post("/views/{view_id}/delete")
def delete_view_post(
    request: Request,
    view_id: int,
    user: User = Depends(require_capability(MANAGE_VIEWS)),
    db: Session = Depends(get_session),
):
    view = get_view(db, view_id)
    if view is None:
        raise HTTPException(status_code=404)
    name = view.name
    delete_view(db, view)
    return redirect_with_flash("/views", f"View '{name}' deleted.")
