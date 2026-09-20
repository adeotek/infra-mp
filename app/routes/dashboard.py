"""Dashboard and index routes."""

from __future__ import annotations

import re

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
from app.models.view import View
from app.services.aggregates import aggregate, format_total, is_numeric_attribute, to_decimal
from app.services.record_service import (
    build_rows,
    count_records,
    list_records,
    resolve_reference_titles,
)
from app.services.schema_service import get_entity_with_attributes, list_entities
from app.services.view_service import (
    apply_config,
    build_view_rows,
    list_views,
    view_column_total,
    view_columns,
)
from app.templates import render

router = APIRouter()

# Widget widths are spans of the dashboard's 12-column grid (1 = narrowest,
# 12 = full row) — the Bootstrap-style model users expect.
DEFAULT_WIDGET_SPAN = "6"
# Widths stored before the 12-column grid, mapped to their equivalent span.
LEGACY_WIDGET_WIDTHS = {"1/4": "3", "1/2": "6", "3/4": "9", "full": "12"}
WIDGET_WIDTH_CLASSES = {str(n): f"widget-span-{n}" for n in range(1, 13)}
WIDGET_TYPES = {"table", "count", "sum"}
# Count/sum widgets render a single value: they are the ones a colour applies to.
STAT_WIDGET_TYPES = {"count", "sum"}
# Custom content colours are hex only — the value ends up in an inline style, so
# named colours/CSS functions are rejected rather than escaped (#rgb/#rrggbb/#rrggbbaa).
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


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


def _widget_records(db: Session, entity_id: int, cache: dict) -> list:
    """All live records of ``entity_id``, loaded once per request.

    N widgets bound to the same entity used to issue N full record loads;
    ``cache`` (also used by the view engine for related-entity loads) memoises
    the top-level load with its own key so the per-entity list is fetched
    exactly once per dashboard render.
    """
    key = ("widget-records", entity_id)
    if key in cache:
        return cache[key]
    records = list_records(db, entity_id)
    cache[key] = records
    return records


def _render_table_widget(db: Session, widget: DashboardWidget, entities: list, cache: dict):
    if widget.entity_id is None:
        return None
    entity = get_entity_with_attributes(db, widget.entity_id)
    if entity is None:
        return None
    records = _widget_records(db, widget.entity_id, cache)
    view = widget.view
    if view is not None:
        records, columns = apply_config(entity, records, view.config, entities, db=db, cache=cache)
        # build_view_rows keys cells by column key (base slugs and rel:* keys),
        # so related-entity columns render exactly like the view's detail page.
        rows = build_view_rows(db, entity, records, columns, cache=cache)
        columns = [
            {
                "name": c.label,
                "slug": c.key,
                "with_copy_button": c.with_copy_button,
                "numeric": c.is_numeric,
            }
            for c in columns
        ]
    else:
        columns = [
            {
                "name": a.name,
                "slug": a.slug,
                "with_copy_button": a.with_copy_button,
                "numeric": a.is_numeric,
            }
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
            entity,
            _widget_records(db, widget.entity_id, cache),
            view.config,
            entities,
            db=db,
            cache=cache,
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
    """Sum one numeric field over the (optionally view-filtered) records.

    Returns the formatted total, or ``None`` when the widget's field is missing
    or no longer numeric (the card explains that instead of showing a number).
    A view-bound widget sums one of the view's **columns** — base attributes,
    related-entity attributes and computed formula columns alike — over the
    rows the view keeps.
    """
    field = str((widget.config or {}).get("field") or "")
    if not field:
        return None
    view = widget.view
    if view is not None:
        entity = get_entity_with_attributes(db, view.entity_id)
        if entity is None:
            return None
        records = _widget_records(db, view.entity_id, cache)
        records, columns = apply_config(entity, records, view.config, entities, db=db, cache=cache)
        total = view_column_total(db, entity, records, columns, field, cache=cache)
        return None if total is None else total["value"]
    if widget.entity_id is None:
        return None
    entity = get_entity_with_attributes(db, widget.entity_id)
    if entity is None:
        return None
    attr = next((a for a in entity.attributes if a.slug == field), None)
    if attr is None or not is_numeric_attribute(attr):
        return None
    records = _widget_records(db, widget.entity_id, cache)
    values = [
        value
        for value in (to_decimal(record.data.get(attr.slug)) for record in records)
        if value is not None
    ]
    return format_total(aggregate(values, "sum"))


def _field_options(entities: list, views: list) -> dict[str, list[dict]]:
    """Numeric field options for the sum widget's field select.

    Two sources, embedded as JSON in the widget forms so the select follows the
    entity/view choice without a round-trip:

    - an entity's numeric attributes (value = attribute slug);
    - a view's numeric columns (value = the view column key the renderer uses:
      the base slug, a ``rel:…`` key, or ``calc:<ordinal>`` for a computed
      formula column) — the server-rendered options are the no-JS fallback.
    """
    return {
        "entities": [
            {
                "id": entity.id,
                "name": entity.name,
                "fields": [
                    {"value": attr.slug, "label": attr.name}
                    for attr in entity.attributes
                    if is_numeric_attribute(attr)
                ],
            }
            for entity in entities
        ],
        "views": [
            {
                "id": view.id,
                "name": view.name,
                "entity_id": view.entity_id,
                "fields": [
                    {"value": column.key, "label": column.label}
                    for column in view_columns(view, entities)
                    if column.is_numeric
                ],
            }
            for view in views
        ],
    }


def _normalize_color(value: str) -> str | None:
    """Hex colour -> lower-cased hex; ``""`` when empty; ``None`` when invalid."""
    value = (value or "").strip()
    if not value:
        return ""
    return value.lower() if HEX_COLOR_RE.match(value) else None


def _stored_color(config: dict | None) -> str:
    """The widget's stored content colour, or ``""`` for the default.

    Read-tolerant like every other widget config key: a hand-edited or legacy
    value that is not a hex colour is dropped rather than rendered.
    """
    return _normalize_color(str((config or {}).get("color") or "")) or ""


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
    db: Session,
    widget_type: str,
    entity_id: int | None,
    field: str,
    view: View | None,
) -> str | None:
    """A sum widget must name a numeric field.

    With a view bound the field is one of that view's columns — computed
    (formula) columns included — because the view decides the rows it sums;
    otherwise it is a numeric attribute of the widget's entity.
    """
    if widget_type != "sum":
        return None
    if view is not None:
        column = next((c for c in view_columns(view, list_entities(db)) if c.key == field), None)
        if column is None:
            return "Choose a numeric column of the selected view."
        if not column.is_numeric:
            return f"'{column.label}' is not a numeric column."
        return None
    if entity_id is None:
        return "A sum widget needs an entity or a view."
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        return "Unknown entity for this widget."
    attr = next((a for a in entity.attributes if a.slug == field), None)
    if attr is None:
        return "Choose the numeric field to summarize."
    if not is_numeric_attribute(attr):
        return f"'{attr.name}' is not a numeric field."
    return None


def _widget_config(widget_type: str, field: str, color: str) -> dict[str, str]:
    """Stored widget config: only the keys the widget type actually uses.

    A key the type does not use is dropped (switching a widget's type clears
    the previous type's settings), and the colour only applies to the
    single-value cards.
    """
    config: dict[str, str] = {}
    if widget_type == "sum":
        config["field"] = field
    if color and widget_type in STAT_WIDGET_TYPES:
        config["color"] = color
    return config


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
                # Validated hex or "" — the template inlines it as a style.
                "color": _stored_color(widget.config),
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
    views = list_views(db)
    return render(
        request,
        "dashboard/config.html",
        {
            "widgets": _load_widgets(db),
            "entities": entities,
            "views": views,
            "field_options": _field_options(entities, views),
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
    color: str = Form(""),
    width: str = Form(DEFAULT_WIDGET_SPAN),
):
    type_error = _validate_widget_type(widget_type)
    if type_error is not None:
        return redirect_with_flash(
            "/dashboard/config", type_error, category="error", request=request
        )
    eid, vid = _parse_ids(entity_id, view_id)
    view = db.get(View, vid) if vid is not None else None
    if vid is not None and view is None:
        return redirect_with_flash(
            "/dashboard/config", "Unknown view for this widget.", category="error", request=request
        )
    if view is not None:
        # A view-bound widget reads the view's entity, so the stored entity
        # follows the view (the form keeps the select in step too).
        eid = view.entity_id
    field = field.strip()
    field_error = _validate_sum_field(db, widget_type, eid, field, view)
    if field_error is not None:
        return redirect_with_flash(
            "/dashboard/config", field_error, category="error", request=request
        )
    normalized_color = _normalize_color(color)
    if normalized_color is None:
        return redirect_with_flash(
            "/dashboard/config",
            "Color must be a hex value like #14b8a6.",
            category="error",
            request=request,
        )
    db.add(
        DashboardWidget(
            title=title.strip(),
            widget_type=widget_type,
            entity_id=eid,
            view_id=vid,
            sort_order=_next_sort_order(db),
            width=_parse_width(width),
            config=_widget_config(widget_type, field, normalized_color),
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
    views = list_views(db)
    return render(
        request,
        "dashboard/widget_form.html",
        {
            "widget": widget,
            "entities": entities,
            "views": views,
            "field_options": _field_options(entities, views),
            # Normalised here so a stale/unknown stored colour shows as empty.
            "stored_color": _stored_color(widget.config),
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
    color: str = Form(""),
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
    view = db.get(View, vid) if vid is not None else None
    if vid is not None and view is None:
        return redirect_with_flash(
            "/dashboard/config", "Unknown view for this widget.", category="error", request=request
        )
    if view is not None:
        # A view-bound widget reads the view's entity, so the stored entity
        # follows the view (the form keeps the select in step too).
        eid = view.entity_id
    field = field.strip()
    field_error = _validate_sum_field(db, widget_type, eid, field, view)
    if field_error is not None:
        return redirect_with_flash(
            "/dashboard/config", field_error, category="error", request=request
        )
    normalized_color = _normalize_color(color)
    if normalized_color is None:
        return redirect_with_flash(
            "/dashboard/config",
            "Color must be a hex value like #14b8a6.",
            category="error",
            request=request,
        )
    widget.title = title.strip()
    widget.widget_type = widget_type
    widget.entity_id = eid
    widget.view_id = vid
    widget.width = _parse_width(width)
    widget.config = _widget_config(widget_type, field, normalized_color)
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
