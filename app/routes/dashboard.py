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
from app.services.record_service import build_rows, list_records, resolve_reference_titles
from app.services.schema_service import get_entity_with_attributes, list_entities
from app.services.view_service import apply_config, list_views
from app.templates import render

router = APIRouter()

# Allowed dashboard widget widths and their grid span classes.
WIDGET_WIDTHS = {"1/4", "1/2", "3/4", "full"}
WIDGET_WIDTH_CLASSES = {
    "1/4": "widget-span-1",
    "1/2": "widget-span-2",
    "3/4": "widget-span-3",
    "full": "widget-span-4",
}


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


def _render_table_widget(db: Session, widget: DashboardWidget):
    if widget.entity_id is None:
        return None
    entity = get_entity_with_attributes(db, widget.entity_id)
    records = list_records(db, widget.entity_id)
    if widget.view_id is not None:
        records, columns = apply_config(entity, records, widget.view.config)
    else:
        columns = entity.attributes
    titles = resolve_reference_titles(db, entity)
    rows = build_rows(entity, records, titles)
    return {"entity": entity, "columns": columns, "rows": rows}


def _render_count_widget(db: Session, widget: DashboardWidget) -> int:
    if widget.entity_id is None:
        return 0
    entity = get_entity_with_attributes(db, widget.entity_id)
    records = list_records(db, widget.entity_id)
    if widget.view_id is not None:
        records, _ = apply_config(entity, records, widget.view.config)
    return len(records)


def _next_sort_order(db: Session) -> int:
    current = db.execute(
        select(func.coalesce(func.max(DashboardWidget.sort_order), 0))
    ).scalar_one()
    return current + 1


def _parse_width(value: str) -> str:
    return value if value in WIDGET_WIDTHS else "1/2"


def _parse_ids(entity_id: str | None, view_id: str | None) -> tuple[int | None, int | None]:
    return (
        int(entity_id) if entity_id and entity_id.strip() else None,
        int(view_id) if view_id and view_id.strip() else None,
    )


@router.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    widgets_data = []
    for widget in _load_widgets(db):
        if widget.widget_type == "table":
            data = _render_table_widget(db, widget)
        elif widget.widget_type == "count":
            data = _render_count_widget(db, widget)
        else:
            continue
        widgets_data.append(
            {
                "widget": widget,
                "data": data,
                "width_class": WIDGET_WIDTH_CLASSES.get(widget.width, "widget-span-2"),
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
    return render(
        request,
        "dashboard/config.html",
        {
            "widgets": _load_widgets(db),
            "entities": list_entities(db),
            "views": list_views(db),
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
    width: str = Form("1/2"),
):
    eid, vid = _parse_ids(entity_id, view_id)
    db.add(
        DashboardWidget(
            title=title.strip(),
            widget_type=widget_type,
            entity_id=eid,
            view_id=vid,
            sort_order=_next_sort_order(db),
            width=_parse_width(width),
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
    return render(
        request,
        "dashboard/widget_form.html",
        {"widget": widget, "entities": list_entities(db), "views": list_views(db)},
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
    width: str = Form("1/2"),
):
    widget = db.get(DashboardWidget, widget_id)
    if widget is None:
        raise HTTPException(status_code=404)
    eid, vid = _parse_ids(entity_id, view_id)
    widget.title = title.strip()
    widget.widget_type = widget_type
    widget.entity_id = eid
    widget.view_id = vid
    widget.width = _parse_width(width)
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
