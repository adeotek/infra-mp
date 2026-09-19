"""Dashboard and index routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user, require_capability
from app.auth.permissions import MANAGE_DASHBOARD, has_capability
from app.db import get_session
from app.flash import redirect_with_flash
from app.models.dashboard import DashboardWidget
from app.models.user import User
from app.services.aggregates import aggregate, format_total, is_numeric_attribute, to_decimal
from app.services.record_service import (
    build_rows,
    count_records,
    list_records,
    resolve_reference_titles,
)
from app.services.schema_service import get_entity_with_attributes, list_entities
from app.services.view_service import apply_config, build_view_rows, list_views
from app.templates import render

router = APIRouter()

# Widget widths are spans of the dashboard's 12-column grid (1 = narrowest,
# 12 = full row) — the Bootstrap-style model users expect.
DEFAULT_WIDGET_SPAN = "6"
# Widths stored before the 12-column grid, mapped to their equivalent span.
LEGACY_WIDGET_WIDTHS = {"1/4": "3", "1/2": "6", "3/4": "9", "full": "12"}
WIDGET_WIDTH_CLASSES = {str(n): f"widget-span-{n}" for n in range(1, 13)}
WIDGET_TYPES = {"table", "count", "sum"}


def _load_widgets(db: Session) -> list[DashboardWidget]:
    return list(
        db.execute(
            select(DashboardWidget)
            .options(
                selectinload(DashboardWidget.entity),
                selectinload(DashboardWidget.view),
            )
            .order_by(DashboardWidget.sort_order, DashboardWidget.id)
        ).scalars()
    )


def _render_table_widget(db: Session, widget: DashboardWidget, entities: list, cache: dict):
    if widget.entity_id is None:
        return None
    entity = get_entity_with_attributes(db, widget.entity_id)
    if entity is None:
        return None
    records = list_records(db, widget.entity_id)
    view = widget.view
    if view is not None:
        records, columns = apply_config(entity, records, view.config, entities, db=db, cache=cache)
        # build_view_rows keys cells by column key (base slugs and rel:* keys),
        # so related-entity columns render exactly like the view's detail page.
        rows = build_view_rows(db, entity, records, columns, cache=cache)
        columns = [
            {"name": c.label, "slug": c.key, "with_copy_button": c.attr.with_copy_button}
            for c in columns
        ]
    else:
        columns = [
            {"name": a.name, "slug": a.slug, "with_copy_button": a.with_copy_button}
            for a in entity.attributes
        ]
        titles = resolve_reference_titles(db, entity, cache=cache)
        rows = build_rows(entity, records, titles)
    return {"entity": entity, "columns": columns, "rows": rows}


def _render_count_widget(db: Session, widget: DashboardWidget, entities: list, cache: dict) -> int:
    if widget.entity_id is None:
        return 0
    view = widget.view
    if view is not None:
        # A view-bound count must honour the view's filters — materialise.
        entity = get_entity_with_attributes(db, widget.entity_id)
        if entity is None:
            return 0
        records, _ = apply_config(
            entity, list_records(db, widget.entity_id), view.config, entities, db=db, cache=cache
        )
        return len(records)
    # A plain count is a single SQL COUNT(*), not a full record load.
    return count_records(db, widget.entity_id)


def _render_sum_widget(
    db: Session,
    widget: DashboardWidget,
    entities: list,
    cache: dict,
) -> str | None:
    """Sum one numeric attribute over the (optionally view-filtered) records.

    Returns the formatted total, or ``None`` when the widget's field is missing
    or no longer numeric (the card explains that instead of showing a number).
    """
    if widget.entity_id is None:
        return None
    entity = get_entity_with_attributes(db, widget.entity_id)
    if entity is None:
        return None
    field = str((widget.config or {}).get("field") or "")
    attr = next((a for a in entity.attributes if a.slug == field), None)
    if attr is None or not is_numeric_attribute(attr):
        return None
    records = list_records(db, widget.entity_id)
    view = widget.view
    if view is not None and view.entity_id == widget.entity_id:
        records, _ = apply_config(entity, records, view.config, entities, db=db, cache=cache)
    values = [
        value
        for value in (to_decimal(record.data.get(attr.slug)) for record in records)
        if value is not None
    ]
    return format_total(aggregate(values, "sum"))


def _numeric_fields(entities: list) -> list[dict]:
    """Numeric attributes per entity — the sum widget's field options.

    Embedded in the widget forms as JSON so the field select follows the
    chosen entity without a round-trip.
    """
    return [
        {
            "id": entity.id,
            "name": entity.name,
            "fields": [
                {"slug": attr.slug, "name": attr.name}
                for attr in entity.attributes
                if is_numeric_attribute(attr)
            ],
        }
        for entity in entities
    ]


def _next_sort_order(db: Session) -> int:
    current = db.execute(
        select(func.coalesce(func.max(DashboardWidget.sort_order), 0))
    ).scalar_one()
    return current + 1


def _parse_width(value: str) -> str:
    """Normalise a submitted width to a 1-12 span (legacy tokens included)."""
    value = (value or "").strip()
    if value in LEGACY_WIDGET_WIDTHS:
        return LEGACY_WIDGET_WIDTHS[value]
    if value.isdigit() and 1 <= int(value) <= 12:
        return value
    return DEFAULT_WIDGET_SPAN


def _width_class(width: str) -> str:
    return WIDGET_WIDTH_CLASSES.get(_parse_width(width), f"widget-span-{DEFAULT_WIDGET_SPAN}")


def _parse_ids(entity_id: str | None, view_id: str | None) -> tuple[int | None, int | None]:
    """Parse widget id fields; malformed values are a 400, not a 500."""
    try:
        return (
            int(entity_id) if entity_id and entity_id.strip() else None,
            int(view_id) if view_id and view_id.strip() else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid entity or view id") from exc


def _validate_widget_type(widget_type: str) -> str | None:
    """Return the type when valid, else an error message."""
    if widget_type not in WIDGET_TYPES:
        return f"Unknown widget type '{widget_type}'; expected 'table', 'count' or 'sum'."
    return None


def _validate_sum_field(
    db: Session, widget_type: str, entity_id: int | None, field: str
) -> str | None:
    """A sum widget must name a numeric attribute of its entity."""
    if widget_type != "sum":
        return None
    if entity_id is None:
        return "A sum widget needs an entity."
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        return "Unknown entity for this widget."
    attr = next((a for a in entity.attributes if a.slug == field), None)
    if attr is None:
        return "Choose the numeric field to summarize."
    if not is_numeric_attribute(attr):
        return f"'{attr.name}' is not a numeric field."
    return None


@router.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    # Entities and per-entity record loads are shared across widgets: with N
    # widgets on one dashboard these lists are fetched once, not N times.
    entities = list_entities(db)
    cache: dict = {}
    widgets_data = []
    for widget in _load_widgets(db):
        if widget.widget_type == "table":
            data = _render_table_widget(db, widget, entities, cache)
        elif widget.widget_type == "count":
            data = _render_count_widget(db, widget, entities, cache)
        elif widget.widget_type == "sum":
            data = _render_sum_widget(db, widget, entities, cache)
        else:
            continue
        widgets_data.append(
            {
                "widget": widget,
                "data": data,
                "width_class": _width_class(widget.width),
            }
        )

    return render(
        request,
        "dashboard.html",
        {
            "widgets": widgets_data,
            "can_manage_dashboard": has_capability(user, MANAGE_DASHBOARD),
        },
    )


@router.get("/dashboard/config")
def dashboard_config(
    request: Request,
    user: User = Depends(require_capability(MANAGE_DASHBOARD)),
    db: Session = Depends(get_session),
):
    entities = list_entities(db)
    return render(
        request,
        "dashboard/config.html",
        {
            "widgets": _load_widgets(db),
            "entities": entities,
            "views": list_views(db),
            "numeric_fields": _numeric_fields(entities),
        },
    )


@router.post("/dashboard/widgets")
def create_widget(
    request: Request,
    user: User = Depends(require_capability(MANAGE_DASHBOARD)),
    db: Session = Depends(get_session),
    title: str = Form(""),
    widget_type: str = Form(...),
    entity_id: str = Form(""),
    view_id: str = Form(""),
    field: str = Form(""),
    width: str = Form(DEFAULT_WIDGET_SPAN),
):
    type_error = _validate_widget_type(widget_type)
    if type_error is not None:
        return redirect_with_flash(
            "/dashboard/config", type_error, category="error", request=request
        )
    eid, vid = _parse_ids(entity_id, view_id)
    field = field.strip()
    field_error = _validate_sum_field(db, widget_type, eid, field)
    if field_error is not None:
        return redirect_with_flash(
            "/dashboard/config", field_error, category="error", request=request
        )
    db.add(
        DashboardWidget(
            title=title.strip(),
            widget_type=widget_type,
            entity_id=eid,
            view_id=vid,
            sort_order=_next_sort_order(db),
            width=_parse_width(width),
            config={"field": field} if widget_type == "sum" else {},
        )
    )
    db.commit()
    return redirect_with_flash("/dashboard/config", "Widget added.")


@router.get("/dashboard/widgets/{widget_id}/edit")
def edit_widget_page(
    request: Request,
    widget_id: int,
    user: User = Depends(require_capability(MANAGE_DASHBOARD)),
    db: Session = Depends(get_session),
):
    widget = db.get(DashboardWidget, widget_id)
    if widget is None:
        raise HTTPException(status_code=404)
    entities = list_entities(db)
    return render(
        request,
        "dashboard/widget_form.html",
        {
            "widget": widget,
            "entities": entities,
            "views": list_views(db),
            "numeric_fields": _numeric_fields(entities),
        },
    )


@router.post("/dashboard/widgets/{widget_id}/edit")
def update_widget(
    request: Request,
    widget_id: int,
    user: User = Depends(require_capability(MANAGE_DASHBOARD)),
    db: Session = Depends(get_session),
    title: str = Form(""),
    widget_type: str = Form(...),
    entity_id: str = Form(""),
    view_id: str = Form(""),
    field: str = Form(""),
    width: str = Form(DEFAULT_WIDGET_SPAN),
):
    widget = db.get(DashboardWidget, widget_id)
    if widget is None:
        raise HTTPException(status_code=404)
    type_error = _validate_widget_type(widget_type)
    if type_error is not None:
        return redirect_with_flash(
            "/dashboard/config", type_error, category="error", request=request
        )
    eid, vid = _parse_ids(entity_id, view_id)
    field = field.strip()
    field_error = _validate_sum_field(db, widget_type, eid, field)
    if field_error is not None:
        return redirect_with_flash(
            "/dashboard/config", field_error, category="error", request=request
        )
    widget.title = title.strip()
    widget.widget_type = widget_type
    widget.entity_id = eid
    widget.view_id = vid
    widget.width = _parse_width(width)
    widget.config = {"field": field} if widget_type == "sum" else {}
    db.commit()
    return redirect_with_flash("/dashboard/config", "Widget updated.")


@router.post("/dashboard/widgets/reorder")
def reorder_widgets_post(
    request: Request,
    user: User = Depends(require_capability(MANAGE_DASHBOARD)),
    db: Session = Depends(get_session),
    order: str = Form(...),
):
    try:
        ordered_ids = [int(x) for x in order.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400) from None
    widgets = db.execute(select(DashboardWidget)).scalars().all()
    by_id = {w.id: w for w in widgets}
    if len(ordered_ids) != len(by_id) or set(ordered_ids) != set(by_id):
        raise HTTPException(status_code=400)
    for index, widget_id in enumerate(ordered_ids):
        by_id[widget_id].sort_order = index
    db.commit()
    return Response(status_code=204)


@router.post("/dashboard/widgets/{widget_id}/delete")
def delete_widget(
    request: Request,
    widget_id: int,
    user: User = Depends(require_capability(MANAGE_DASHBOARD)),
    db: Session = Depends(get_session),
):
    widget = db.get(DashboardWidget, widget_id)
    if widget is None:
        raise HTTPException(status_code=404)
    db.delete(widget)
    db.commit()
    return redirect_with_flash("/dashboard/config", "Widget removed.")
