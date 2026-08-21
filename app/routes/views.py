"""Saved view routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_capability
from app.auth.permissions import MANAGE_VIEWS, has_capability
from app.db import get_session
from app.flash import redirect_with_flash
from app.form import parse_form, to_list
from app.models.entity import Entity
from app.models.user import User
from app.models.view import View
from app.services.csv_service import export_view_csv
from app.services.record_service import list_records
from app.services.schema_service import get_entity_with_attributes, list_entities
from app.services.view_service import (
    FILTER_OPS,
    apply_config,
    build_view_graph,
    build_view_rows,
    column_spec_string,
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


def _config_from_form(raw: dict, entity: Entity) -> dict:
    column_specs = []
    for value in to_list(raw.get("col")):
        spec = parse_column_spec(value)
        if spec is not None:
            column_specs.append(spec)
    if not column_specs:
        # Legacy form: flat base-attribute slugs.
        column_specs = [v for v in to_list(raw.get("columns")) if v.strip()]
    sort_value = str(raw.get("sort_col", "") or raw.get("sort_slug", "") or "").strip()
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

    config: dict = {
        "columns": column_specs,
        "filters": filters,
        "advanced_filter": str(raw.get("advanced_filter", "")).lower()
        in ("on", "true", "1", "yes"),
    }
    if sort_value:
        # Any view column may be the sort column: the form submits the same
        # encoding as the `col` fields. Legacy plain slugs still work.
        spec = parse_column_spec(sort_value)
        if isinstance(spec, str):
            config["sort"] = {"slug": spec, "dir": sort_dir}
        elif isinstance(spec, dict):
            config["sort"] = {"col": spec, "dir": sort_dir}
        elif sort_value in {a.slug for a in entity.attributes}:
            config["sort"] = {"slug": sort_value, "dir": sort_dir}
    return config


def _icon_from_form(raw: dict) -> str:
    # Free text: any value is accepted and normalised to an `fa-*` class at
    # render time by the `icon_class` Jinja filter (same as entity icons).
    return str(raw.get("icon", "")).strip()


def _merged_config(previous: dict | None, new: dict) -> dict:
    """Keep bar-managed filters when the Advanced filters checkbox is on."""
    if new.get("advanced_filter") and previous:
        new["filters"] = list(previous.get("filters", []))
        new["filter_op"] = previous.get("filter_op", "and")
    else:
        new.setdefault("filter_op", "and")
    return new


def _rel_key(spec: dict) -> str:
    """The ViewColumn.key for a related-column spec (matches the resolver)."""
    hops = "/".join(f"{h['dir']}:{h['ref']}:{h['to']}:{h['many']}" for h in spec.get("path", []))
    return f"rel:{hops}→{spec.get('attr', '')}"


def _filter_options(columns: list) -> list[dict]:
    """Metadata for the advanced filter column select (type drives ops/values)."""
    options = []
    for column in columns:
        attr = column.attr
        options.append(
            {
                "value": column_spec_string(column),
                "label": column.label,
                "type": attr.data_type,
                "many": attr.data_type == "reference" and attr.config.get("cardinality") == "many",
                "choices": attr.options if attr.data_type == "enum" else [],
            }
        )
    return options


def _describe_filters(filters: list[dict], columns: list) -> list[dict]:
    """Human-readable rows for the active filter box."""
    described = []
    columns_by_key = {c.key: c for c in columns}
    for spec in filters:
        col = spec.get("col")
        if col is None:
            col = spec.get("slug")
        if col == "quick":
            label = "Quick filter"
        elif isinstance(col, str):
            label = columns_by_key[col].label if col in columns_by_key else col
        elif isinstance(col, dict):
            key = _rel_key(col)
            label = columns_by_key[key].label if key in columns_by_key else "Column"
        else:
            continue
        described.append(
            {"label": label, "op": spec.get("op", "eq"), "value": spec.get("value", "")}
        )
    return described


def _view_detail_context(db: Session, view: View, entity: Entity, can_manage_views: bool) -> dict:
    records, columns = apply_config(
        entity, list_records(db, view.entity_id), view.config, list_entities(db), db=db
    )
    rows = build_view_rows(db, entity, records, columns)
    config = view.config or {}
    return {
        "view": view,
        "entity": entity,
        "columns": columns,
        "rows": rows,
        "can_manage_views": can_manage_views,
        "advanced_filter": bool(config.get("advanced_filter")),
        "filter_op": config.get("filter_op", "and"),
        "filter_op_label": filter_op_label,
        "active_filters": _describe_filters(config.get("filters", []), columns),
        "filter_options": _filter_options(columns),
    }


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
        db,
        entity,
        name,
        _merged_config(None, _config_from_form(raw, entity)),
        icon=_icon_from_form(raw),
        user_id=user.id,
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
    return render(
        request,
        "views/detail.html",
        _view_detail_context(db, view, entity, has_capability(user, MANAGE_VIEWS)),
    )


@router.post("/views/{view_id}/filters")
async def view_filters_post(
    request: Request,
    view_id: int,
    user: User = Depends(require_capability(MANAGE_VIEWS)),
    db: Session = Depends(get_session),
):
    """Add/remove/clear advanced filters or change the global operator.

    Every mutation is applied immediately: the response re-renders the view
    body (filter bar + active box + table) for an HTMX swap.
    """
    view = get_view(db, view_id)
    if view is None:
        raise HTTPException(status_code=404)
    entity = get_entity_with_attributes(db, view.entity_id)
    raw = await parse_form(request)
    config = dict(view.config or {})
    config.setdefault("advanced_filter", False)
    config.setdefault("filter_op", "and")
    filters = list(config.get("filters", []))
    action = str(raw.get("action", ""))

    if action == "add":
        col_raw = str(raw.get("col", "")).strip()
        value = str(raw.get("value", "")).strip()
        if not col_raw:
            return redirect_with_flash(
                f"/views/{view.id}",
                "Choose a filter column first.",
                category="error",
                request=request,
            )
        if not value:
            return redirect_with_flash(
                f"/views/{view.id}",
                "Enter a filter value first.",
                category="error",
                request=request,
            )
        spec: str | dict | None = "quick" if col_raw == "quick" else parse_column_spec(col_raw)
        if spec is None:
            return redirect_with_flash(
                f"/views/{view.id}", "Unknown filter column.", category="error", request=request
            )
        op = str(raw.get("op", "")).strip()
        if op not in FILTER_OPS:
            op = "eq"
        if spec == "quick":
            op = "contains"
        filters.append({"col": spec, "op": op, "value": value})
    elif action == "remove":
        try:
            index = int(raw.get("index", -1))
        except (TypeError, ValueError):
            index = -1
        if 0 <= index < len(filters):
            filters.pop(index)
    elif action == "clear":
        filters = []
    elif action == "set_op":
        config["filter_op"] = "or" if str(raw.get("filter_op", "")) == "or" else "and"
    else:
        return redirect_with_flash(
            f"/views/{view.id}", "Unknown filter action.", category="error", request=request
        )

    config["filters"] = filters
    update_view(db, view, view.name, config, icon=view.icon or "")

    if request.headers.get("HX-Request"):
        return render(
            request, "views/detail_body.html", _view_detail_context(db, view, entity, True)
        )
    return redirect_with_flash(f"/views/{view.id}", "Filters updated.")


@router.get("/views/{view_id}/export")
def export_view(
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
        entity, list_records(db, view.entity_id), view.config, list_entities(db), db=db
    )
    rows = build_view_rows(db, entity, records, columns)
    csv_text = export_view_csv(columns, rows)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{view.slug}.csv"'},
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
    update_view(
        db,
        view,
        name,
        _merged_config(view.config, _config_from_form(raw, entity)),
        icon=_icon_from_form(raw),
    )
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
