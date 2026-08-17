"""Entity and attribute (schema) management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_capability
from app.auth.permissions import MANAGE_SCHEMA, has_capability
from app.db import get_session
from app.flash import redirect_with_flash
from app.models.attribute import Attribute
from app.models.entity import Entity
from app.models.enums import DataType
from app.models.user import User
from app.schemas.attribute import AttributeCreate, AttributeUpdate
from app.schemas.entity import EntityCreate, EntityUpdate
from app.services.schema_service import (
    SchemaError,
    add_attribute,
    create_entity,
    delete_attribute,
    delete_entity,
    entity_has_records,
    entity_record_counts,
    get_entity,
    get_entity_with_attributes,
    list_entities,
    reorder_attributes,
    update_attribute,
    update_entity,
)
from app.templates import render

router = APIRouter()


def _attribute_from_form(
    name: str,
    data_type: DataType,
    is_required: bool,
    default_value: str,
    options: str,
    reference_entity_id: str,
    cardinality: str,
    hint: str = "",
    slug: str = "",
    is_active: bool = True,
) -> AttributeUpdate:
    options_list = [o.strip() for o in options.splitlines() if o.strip()] or None
    ref_id = int(reference_entity_id) if reference_entity_id.strip() else None
    return AttributeUpdate(
        name=name,
        data_type=data_type,
        is_required=is_required,
        default_value=default_value or None,
        options=options_list,
        reference_entity_id=ref_id,
        cardinality="many" if cardinality == "many" else "one",
        hint=hint.strip() or None,
        slug=slug.strip() or None,
        is_active=is_active,
    )


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #


@router.get("/entities")
def entities_index(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    return render(
        request,
        "entities/list.html",
        {
            "entities": list_entities(db),
            "record_counts": entity_record_counts(db),
            "can_manage_schema": has_capability(user, MANAGE_SCHEMA),
        },
    )


@router.get("/entities/new")
def new_entity_page(request: Request, user: User = Depends(require_capability(MANAGE_SCHEMA))):
    return render(request, "entities/form.html", {"entity": None})


@router.post("/entities")
def create_entity_post(
    request: Request,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
    name: str = Form(...),
    description: str = Form(""),
    icon: str = Form(""),
):
    try:
        entity = create_entity(
            db, EntityCreate(name=name, description=description, icon=icon), created_by=user.id
        )
    except SchemaError as exc:
        return render(
            request,
            "entities/form.html",
            {
                "entity": None,
                "form_data": {"name": name, "description": description, "icon": icon},
                "error": str(exc),
            },
            status_code=400,
        )
    return redirect_with_flash(
        f"/entities/{entity.id}", f"Entity '{entity.name}' created.", request=request
    )


@router.get("/entities/{entity_id}")
def entity_detail(
    request: Request,
    entity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    entity = get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    return render(
        request,
        "entities/detail.html",
        {
            "entity": entity,
            "can_manage_schema": has_capability(user, MANAGE_SCHEMA),
            "record_counts": entity_record_counts(db),
        },
    )


@router.get("/entities/{entity_id}/edit")
def edit_entity_page(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
):
    entity = get_entity(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    return render(
        request,
        "entities/form.html",
        {"entity": entity, "has_records": entity_has_records(db, entity_id)},
    )


@router.post("/entities/{entity_id}/edit")
def update_entity_post(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
    name: str = Form(...),
    description: str = Form(""),
    icon: str = Form(""),
    slug: str = Form(""),
):
    entity = get_entity(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    try:
        update_entity(
            db,
            entity,
            EntityUpdate(name=name, description=description, icon=icon, slug=slug.strip() or None),
        )
    except SchemaError as exc:
        return render(
            request,
            "entities/form.html",
            {
                "entity": entity,
                "form_data": {
                    "name": name,
                    "description": description,
                    "icon": icon,
                    "slug": slug.strip() or None,
                },
                "error": str(exc),
                "has_records": entity_has_records(db, entity_id),
            },
            status_code=400,
        )
    return redirect_with_flash(
        f"/entities/{entity.id}", f"Entity '{entity.name}' updated.", request=request
    )


@router.post("/entities/{entity_id}/delete")
def delete_entity_post(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
):
    entity = get_entity(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    name = entity.name
    delete_entity(db, entity)
    return redirect_with_flash("/entities", f"Entity '{name}' deleted.")


# --------------------------------------------------------------------------- #
# Attributes
# --------------------------------------------------------------------------- #


@router.get("/entities/{entity_id}/attributes/new")
def new_attribute_page(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
):
    entity = get_entity(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    return render(
        request,
        "attributes/form.html",
        {
            "entity": entity,
            "attribute": None,
            "entities": list_entities(db),
            "data_types": list(DataType),
            "action_url": f"/entities/{entity_id}/attributes",
            "has_records": entity_has_records(db, entity_id),
        },
    )


@router.post("/entities/{entity_id}/attributes")
def create_attribute_post(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
    name: str = Form(...),
    data_type: DataType = Form(...),
    is_required: bool = Form(False),
    default_value: str = Form(""),
    options: str = Form(""),
    reference_entity_id: str = Form(""),
    cardinality: str = Form("one"),
    hint: str = Form(""),
    is_active: bool = Form(True),
):
    entity = get_entity(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)

    data = _attribute_from_form(
        name,
        data_type,
        is_required,
        default_value,
        options,
        reference_entity_id,
        cardinality,
        hint,
        is_active=is_active,
    )
    try:
        attribute = add_attribute(db, entity, data)
    except SchemaError as exc:
        return _render_attribute_form_error(request, db, entity, None, data, str(exc))

    return redirect_with_flash(
        f"/entities/{entity.id}", f"Attribute '{attribute.name}' added.", request=request
    )


@router.post("/entities/{entity_id}/attributes/reorder")
def reorder_attributes_post(
    request: Request,
    entity_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
    order: str = Form(...),
):
    entity = get_entity(db, entity_id)
    if entity is None:
        raise HTTPException(status_code=404)
    try:
        ordered_ids = [int(x) for x in order.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400) from None
    try:
        reorder_attributes(db, entity_id, ordered_ids)
    except SchemaError:
        raise HTTPException(status_code=400) from None
    return Response(status_code=204)


@router.get("/attributes/{attribute_id}/edit")
def edit_attribute_page(
    request: Request,
    attribute_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
):
    attribute = db.get(Attribute, attribute_id)
    if attribute is None:
        raise HTTPException(status_code=404)
    entity = get_entity(db, attribute.entity_id)
    return render(
        request,
        "attributes/form.html",
        {
            "entity": entity,
            "attribute": attribute,
            "entities": list_entities(db),
            "data_types": list(DataType),
            "action_url": f"/attributes/{attribute_id}/edit",
            "has_records": entity_has_records(db, attribute.entity_id),
        },
    )


@router.post("/attributes/{attribute_id}/edit")
def update_attribute_post(
    request: Request,
    attribute_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
    name: str = Form(...),
    data_type: DataType = Form(...),
    is_required: bool = Form(False),
    default_value: str = Form(""),
    options: str = Form(""),
    reference_entity_id: str = Form(""),
    cardinality: str = Form("one"),
    hint: str = Form(""),
    slug: str = Form(""),
    is_active: bool = Form(True),
):
    attribute = db.get(Attribute, attribute_id)
    if attribute is None:
        raise HTTPException(status_code=404)
    entity = get_entity(db, attribute.entity_id)

    data = _attribute_from_form(
        name,
        data_type,
        is_required,
        default_value,
        options,
        reference_entity_id,
        cardinality,
        hint,
        slug=slug,
        is_active=is_active,
    )
    try:
        update_attribute(db, attribute, data)
    except SchemaError as exc:
        return _render_attribute_form_error(request, db, entity, attribute, data, str(exc))

    return redirect_with_flash(
        f"/entities/{entity.id}", f"Attribute '{attribute.name}' updated.", request=request
    )


@router.post("/attributes/{attribute_id}/delete")
def delete_attribute_post(
    request: Request,
    attribute_id: int,
    user: User = Depends(require_capability(MANAGE_SCHEMA)),
    db: Session = Depends(get_session),
):
    attribute = db.get(Attribute, attribute_id)
    if attribute is None:
        raise HTTPException(status_code=404)
    entity_id = attribute.entity_id
    name = attribute.name
    try:
        delete_attribute(db, attribute)
    except SchemaError as exc:
        return redirect_with_flash(
            f"/entities/{entity_id}", str(exc), category="error", request=request
        )
    return redirect_with_flash(
        f"/entities/{entity_id}", f"Attribute '{name}' deleted.", request=request
    )


def _render_attribute_form_error(
    request: Request,
    db: Session,
    entity: Entity,
    attribute: Attribute | None,
    data: AttributeCreate,
    error: str,
):
    return render(
        request,
        "attributes/form.html",
        {
            "entity": entity,
            "attribute": attribute,
            "entities": list_entities(db),
            "data_types": list(DataType),
            "action_url": (
                f"/entities/{entity.id}/attributes"
                if attribute is None
                else f"/attributes/{attribute.id}/edit"
            ),
            "form_data": data,
            "error": error,
            "has_records": entity_has_records(db, entity.id),
        },
        status_code=400,
    )
