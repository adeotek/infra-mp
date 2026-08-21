"""Embedded MCP server: agent access to InfraMP data.

Exposes tools mirroring the web UI's capabilities. Authentication uses the
API tokens generated in the web UI (``Authorization: Bearer imp_...``); every
request is verified against the tokens table and the tools enforce the same
capability checks as the web routes, so a viewer token is read-only, a
maintainer token can manage records and views, and an admin token can manage
schema, views, dashboard and users.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer, authenticated_principal
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AnyHttpUrl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.auth.permissions import (
    CREATE_RECORD,
    DELETE_RECORD,
    MANAGE_DASHBOARD,
    MANAGE_SCHEMA,
    MANAGE_USERS,
    MANAGE_VIEWS,
    READ,
    UPDATE_RECORD,
    capabilities_for,
    has_capability,
)
from app.config import Settings
from app.models.attribute import Attribute
from app.models.dashboard import DashboardWidget
from app.models.enums import DataType
from app.models.record import Record
from app.models.user import User
from app.schemas.attribute import AttributeCreate, AttributeUpdate
from app.schemas.entity import EntityCreate, EntityUpdate
from app.services import (
    api_token_service,
    record_service,
    schema_service,
    user_service,
    view_service,
)
from app.services.record_service import RecordError
from app.services.schema_service import SchemaError

MAX_PAGE_SIZE = 200


class InfraMPTokenVerifier(TokenVerifier):
    """Validates InfraMP API tokens issued in the web UI."""

    def __init__(self, session_factory: Any):
        self._session_factory = session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        with self._session_factory() as db:
            user = api_token_service.verify_token(db, token)
        if user is None:
            return None
        return AccessToken(
            token=token,
            client_id="inframp",
            scopes=list(capabilities_for(user.role_enum)),
            subject=str(user.id),
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _dt(value: Any) -> str | None:
    """ISO-format a datetime for JSON output."""
    return value.isoformat() if value is not None else None


def _user_id(ctx: Context) -> int:
    principal = authenticated_principal(ctx.request_context)
    if principal is None:
        raise ToolError("Not authenticated")
    try:
        subject = json.loads(principal)[2]
        user_id = int(subject)
    except (TypeError, ValueError, IndexError, json.JSONDecodeError) as exc:
        raise ToolError("Invalid credentials") from exc
    return user_id


def _require(db: Session, ctx: Context, capability: str) -> User:
    """Resolve the authenticated user and enforce ``capability``."""
    user = db.get(User, _user_id(ctx))
    if user is None or not user.is_active:
        raise ToolError("User account is not active")
    if not has_capability(user, capability):
        raise ToolError(f"Requires the '{capability}' capability")
    return user


def _entity_or_raise(db: Session, entity_id: int):
    entity = schema_service.get_entity_with_attributes(db, entity_id)
    if entity is None:
        raise ToolError(f"Entity {entity_id} not found")
    return entity


def _record_or_raise(db: Session, record_id: int) -> Record:
    record = record_service.get_record(db, record_id)
    if record is None:
        raise ToolError(f"Record {record_id} not found")
    return record


def _entity_summary(entity) -> dict:
    return {
        "id": entity.id,
        "name": entity.name,
        "slug": entity.slug,
        "description": entity.description,
        "icon": entity.icon,
        "created_at": _dt(entity.created_at),
        "attributes": [
            {
                "id": a.id,
                "name": a.name,
                "slug": a.slug,
                "data_type": a.data_type,
                "required": a.is_required,
                "unique": a.is_unique,
                "key": a.is_key,
                "active": a.is_active,
                "default_value": a.default_value,
                "hint": a.hint,
                "config": a.config,
            }
            for a in sorted(entity.attributes, key=lambda a: a.sort_order)
        ],
    }


def _record_dict(record: Record) -> dict:
    return {
        "id": record.id,
        "entity_id": record.entity_id,
        "data": record.data,
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
        "created_by": record.created_by,
        "updated_by": record.updated_by,
    }


def _paginate(records: list[Record], page: int, page_size: int) -> dict:
    total = len(records)
    start = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": [_record_dict(r) for r in records[start : start + page_size]],
    }


# --------------------------------------------------------------------------- #
# Server + tools
# --------------------------------------------------------------------------- #


def build_mcp_server(session_factory: Any, settings: Settings) -> MCPServer:
    """Build the InfraMP MCP server (tools + API-token authentication)."""
    auth = AuthSettings(
        issuer_url=AnyHttpUrl(settings.base_url),
        resource_server_url=AnyHttpUrl(f"{settings.base_url}/mcp"),
    )
    server = MCPServer(
        name="InfraMP",
        version=__version__,
        description=(
            "InfraMP data API: query entities, attributes, records and views, "
            "and modify data according to the token user's role (admin, "
            "maintainer or viewer)."
        ),
        auth=auth,
        token_verifier=InfraMPTokenVerifier(session_factory),
    )

    # ------------------------------------------------------------- read tools

    @server.tool(description="List all entities with their attributes (schema).")
    def list_entities(ctx: Context) -> list[dict]:
        with session_factory() as db:
            _require(db, ctx, READ)
            return [_entity_summary(e) for e in schema_service.list_entities(db)]

    @server.tool(description="Get one entity (by id) with its attributes.")
    def get_entity(entity_id: int, ctx: Context) -> dict:
        with session_factory() as db:
            _require(db, ctx, READ)
            return _entity_summary(_entity_or_raise(db, entity_id))

    @server.tool(
        description=(
            "List records of an entity. Optional: page/page_size pagination, "
            "'search' (case-insensitive substring over any field), 'sort' "
            "(attribute slug; use sort_desc for descending) and 'filters' "
            "(dict of attribute slug -> exact value; reference attributes "
            "match on the numeric record id)."
        )
    )
    def list_records(
        entity_id: int,
        page: int = 1,
        page_size: int = 50,
        sort: str | None = None,
        sort_desc: bool = False,
        search: str | None = None,
        filters: dict[str, Any] | None = None,
        ctx: Context = None,
    ) -> dict:
        with session_factory() as db:
            _require(db, ctx, READ)
            entity = _entity_or_raise(db, entity_id)
            attrs = {a.slug: a for a in entity.attributes}
            records = record_service.list_records(db, entity.id)
            if filters:
                for slug, value in filters.items():
                    attr = attrs.get(slug)
                    if attr is None:
                        raise ToolError(f"Unknown attribute '{slug}'")
                    try:
                        wanted = record_service.coerce_attribute_value(attr, value)
                    except (TypeError, ValueError):
                        wanted = value
                    records = [r for r in records if r.data.get(slug) == wanted]
            if search:
                needle = search.lower()
                records = [
                    r
                    for r in records
                    if any(str(v).lower().find(needle) >= 0 for v in r.data.values())
                ]
            if sort:
                if sort not in attrs:
                    raise ToolError(f"Unknown attribute '{sort}'")
                records = sorted(
                    records,
                    key=lambda r: (str(r.data.get(sort, "")).lower(),),
                    reverse=sort_desc,
                )
            page = max(1, page)
            page_size = min(max(1, page_size), MAX_PAGE_SIZE)
            result = _paginate(records, page, page_size)
            result["entity"] = {"id": entity.id, "name": entity.name}
            return result

    @server.tool(description="Get a single record by id.")
    def get_record(entity_id: int, record_id: int, ctx: Context) -> dict:
        with session_factory() as db:
            _require(db, ctx, READ)
            record = _record_or_raise(db, record_id)
            if record.entity_id != entity_id:
                raise ToolError("Record does not belong to the given entity")
            return _record_dict(record)

    @server.tool(description="List saved views (id, name, entity, icon).")
    def list_views(ctx: Context) -> list[dict]:
        with session_factory() as db:
            _require(db, ctx, READ)
            return [
                {
                    "id": v.id,
                    "name": v.name,
                    "entity_id": v.entity_id,
                    "icon": v.icon,
                }
                for v in view_service.list_views(db)
            ]

    @server.tool(description="Get a saved view with its full configuration.")
    def get_view(view_id: int, ctx: Context) -> dict:
        with session_factory() as db:
            _require(db, ctx, READ)
            view = view_service.get_view(db, view_id)
            if view is None:
                raise ToolError(f"View {view_id} not found")
            return {
                "id": view.id,
                "name": view.name,
                "entity_id": view.entity_id,
                "icon": view.icon,
                "config": view.config,
            }

    @server.tool(
        description=(
            "Run a saved view: returns its records after applying the view's "
            "filters and sorting, paginated."
        )
    )
    def view_records(view_id: int, page: int = 1, page_size: int = 50, ctx: Context = None) -> dict:
        with session_factory() as db:
            _require(db, ctx, READ)
            view = view_service.get_view(db, view_id)
            if view is None:
                raise ToolError(f"View {view_id} not found")
            entity = _entity_or_raise(db, view.entity_id)
            records, _columns = view_service.apply_config(
                entity,
                record_service.list_records(db, view.entity_id),
                view.config,
                schema_service.list_entities(db),
                db=db,
            )
            page = max(1, page)
            page_size = min(max(1, page_size), MAX_PAGE_SIZE)
            result = _paginate(records, page, page_size)
            result["view"] = {"id": view.id, "name": view.name}
            return result

    @server.tool(
        description=(
            "Application-wide counts (entities, records, views; users included for admins)."
        )
    )
    def dashboard_stats(ctx: Context) -> dict:
        with session_factory() as db:
            user = _require(db, ctx, READ)
            active_records = select(func.count(Record.id)).where(Record.deleted_at.is_(None))
            record_count = db.scalar(active_records) or 0
            stats = {
                "entities": len(schema_service.list_entities(db)),
                "records": record_count,
                "views": len(view_service.list_views(db)),
            }
            if has_capability(user, MANAGE_USERS):
                stats["users"] = len(user_service.list_users(db))
            return stats

    @server.tool(description="List users (requires the manage_users capability — admin).")
    def list_users(ctx: Context) -> list[dict]:
        with session_factory() as db:
            _require(db, ctx, MANAGE_USERS)
            return [
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "role": u.role,
                    "is_active": u.is_active,
                    "created_at": _dt(u.created_at),
                }
                for u in user_service.list_users(db)
            ]

    # ------------------------------------------------------- record mutations

    @server.tool(
        description=(
            "Create a record. 'data' maps attribute slugs to values; required "
            "and unique/key constraints apply exactly like the web UI."
        )
    )
    def create_record(entity_id: int, data: dict[str, Any], ctx: Context) -> dict:
        with session_factory() as db:
            user = _require(db, ctx, CREATE_RECORD)
            entity = _entity_or_raise(db, entity_id)
            try:
                record = record_service.create_record(
                    db, entity, entity.attributes, data, user_id=user.id
                )
            except RecordError as exc:
                raise ToolError(str(exc)) from exc
            return _record_dict(record)

    @server.tool(
        description=(
            "Update a record. 'data' contains only the attribute slugs to "
            "change; omitted attributes keep their current values."
        )
    )
    def update_record(entity_id: int, record_id: int, data: dict[str, Any], ctx: Context) -> dict:
        with session_factory() as db:
            user = _require(db, ctx, UPDATE_RECORD)
            record = _record_or_raise(db, record_id)
            if record.entity_id != entity_id:
                raise ToolError("Record does not belong to the given entity")
            entity = _entity_or_raise(db, entity_id)
            try:
                record_service.update_record(db, record, entity.attributes, data, user_id=user.id)
            except RecordError as exc:
                raise ToolError(str(exc)) from exc
            return _record_dict(record)

    @server.tool(description="Delete a record (soft delete, like the web UI).")
    def delete_record(entity_id: int, record_id: int, ctx: Context) -> dict:
        with session_factory() as db:
            _require(db, ctx, DELETE_RECORD)
            record = _record_or_raise(db, record_id)
            if record.entity_id != entity_id:
                raise ToolError("Record does not belong to the given entity")
            record_service.soft_delete_record(db, record)
            return {"deleted": True, "id": record.id}

    # ------------------------------------------------------ schema management

    @server.tool(description="Create an entity (manage_schema — admin).")
    def create_entity(
        name: str, description: str = "", icon: str = "", ctx: Context = None
    ) -> dict:
        with session_factory() as db:
            _require(db, ctx, MANAGE_SCHEMA)
            try:
                data = EntityCreate(name=name, description=description, icon=icon)
                entity = schema_service.create_entity(db, data)
            except SchemaError as exc:
                raise ToolError(str(exc)) from exc
            return {"id": entity.id, "name": entity.name, "slug": entity.slug}

    @server.tool(
        description="Update an entity's name, description or icon (manage_schema — admin)."
    )
    def update_entity(
        entity_id: int,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        ctx: Context = None,
    ) -> dict:
        with session_factory() as db:
            _require(db, ctx, MANAGE_SCHEMA)
            entity = _entity_or_raise(db, entity_id)
            try:
                entity = schema_service.update_entity(
                    db,
                    entity,
                    EntityUpdate(
                        name=name or entity.name,
                        description=entity.description if description is None else description,
                        icon=entity.icon if icon is None else icon,
                    ),
                )
            except SchemaError as exc:
                raise ToolError(str(exc)) from exc
            return {"id": entity.id, "name": entity.name, "slug": entity.slug}

    @server.tool(
        description=("Delete an entity and all its records and attributes (manage_schema — admin).")
    )
    def delete_entity(entity_id: int, ctx: Context) -> dict:
        with session_factory() as db:
            _require(db, ctx, MANAGE_SCHEMA)
            entity = _entity_or_raise(db, entity_id)
            schema_service.delete_entity(db, entity)
            return {"deleted": True, "id": entity_id}

    @server.tool(
        description=(
            "Add an attribute to an entity (manage_schema — admin). "
            "data_type is one of: text, textarea, number, date, datetime, "
            "boolean, enum, reference. For enum pass 'options'; for reference "
            "pass 'reference_entity_id' and 'cardinality' ('one' or 'many')."
        )
    )
    def create_attribute(
        entity_id: int,
        name: str,
        data_type: str,
        is_required: bool = False,
        is_unique: bool = False,
        is_key: bool = False,
        default_value: Any = None,
        hint: str | None = None,
        options: list[str] | None = None,
        reference_entity_id: int | None = None,
        cardinality: str = "one",
        ctx: Context = None,
    ) -> dict:
        with session_factory() as db:
            _require(db, ctx, MANAGE_SCHEMA)
            entity = _entity_or_raise(db, entity_id)
            try:
                data_type_enum = DataType(data_type)
                attribute = schema_service.add_attribute(
                    db,
                    entity,
                    AttributeCreate(
                        name=name,
                        data_type=data_type_enum,
                        is_required=is_required,
                        is_unique=is_unique,
                        is_key=is_key,
                        default_value=default_value,
                        hint=hint,
                        options=options,
                        reference_entity_id=reference_entity_id,
                        cardinality=cardinality,  # type: ignore[arg-type]
                    ),
                )
            except (ValueError, SchemaError) as exc:
                raise ToolError(str(exc)) from exc
            return {"id": attribute.id, "name": attribute.name, "slug": attribute.slug}

    @server.tool(
        description=(
            "Update an attribute (manage_schema — admin). Only the fields "
            "passed are changed; the rest keep their current values."
        )
    )
    def update_attribute(
        attribute_id: int,
        name: str | None = None,
        is_required: bool | None = None,
        is_unique: bool | None = None,
        is_active: bool | None = None,
        default_value: Any = None,
        hint: str | None = None,
        options: list[str] | None = None,
        ctx: Context = None,
    ) -> dict:
        with session_factory() as db:
            _require(db, ctx, MANAGE_SCHEMA)
            attribute = db.get(Attribute, attribute_id)
            if attribute is None:
                raise ToolError(f"Attribute {attribute_id} not found")
            try:
                attribute = schema_service.update_attribute(
                    db,
                    attribute,
                    AttributeUpdate(
                        name=attribute.name if name is None else name,
                        data_type=attribute.data_type_enum,
                        is_required=attribute.is_required if is_required is None else is_required,
                        is_unique=attribute.is_unique if is_unique is None else is_unique,
                        is_key=attribute.is_key,
                        default_value=(
                            attribute.default_value if default_value is None else default_value
                        ),
                        hint=attribute.hint if hint is None else hint,
                        is_active=attribute.is_active if is_active is None else is_active,
                        options=attribute.config.get("options") if options is None else options,
                        reference_entity_id=attribute.config.get("reference_entity_id"),
                        cardinality=attribute.config.get("cardinality", "one"),
                    ),
                )
            except SchemaError as exc:
                raise ToolError(str(exc)) from exc
            return {"id": attribute.id, "name": attribute.name, "slug": attribute.slug}

    @server.tool(description="Delete an attribute (manage_schema — admin).")
    def delete_attribute(attribute_id: int, ctx: Context) -> dict:
        with session_factory() as db:
            _require(db, ctx, MANAGE_SCHEMA)
            attribute = db.get(Attribute, attribute_id)
            if attribute is None:
                raise ToolError(f"Attribute {attribute_id} not found")
            schema_service.delete_attribute(db, attribute)
            return {"deleted": True, "id": attribute_id}

    # --------------------------------------------------------- view management

    @server.tool(
        description=(
            "Create a view (manage_views — admin or maintainer). 'sort' is an "
            "attribute slug, 'filters' a list of {'slug', 'op', 'value'} "
            "conditions (ops: eq, neq, contains, not contains, gt, gte, lt, "
            "lte), 'columns' attribute slugs, 'filter_op' 'and' or 'or'."
        )
    )
    def create_view(
        entity_id: int,
        name: str,
        icon: str = "",
        sort: str | None = None,
        sort_desc: bool = False,
        filters: list[dict] | None = None,
        columns: list[str] | None = None,
        filter_op: str = "and",
        ctx: Context = None,
    ) -> dict:
        with session_factory() as db:
            user = _require(db, ctx, MANAGE_VIEWS)
            entity = _entity_or_raise(db, entity_id)
            op = filter_op if filter_op in ("and", "or") else "and"
            config: dict[str, Any] = {"filter_op": op}
            if sort:
                config["sort"] = {"slug": sort, "dir": "desc" if sort_desc else "asc"}
            if filters:
                config["filters"] = filters
            if columns:
                config["columns"] = columns
            view = view_service.create_view(db, entity, name, config, icon=icon, user_id=user.id)
            return {"id": view.id, "name": view.name, "entity_id": view.entity_id}

    @server.tool(
        description=(
            "Update a view's configuration (manage_views). Passed fields are "
            "merged into the existing config; pass None to keep a field."
        )
    )
    def update_view(
        view_id: int,
        name: str | None = None,
        icon: str | None = None,
        sort: str | None = None,
        sort_desc: bool | None = None,
        filters: list[dict] | None = None,
        columns: list[str] | None = None,
        filter_op: str | None = None,
        ctx: Context = None,
    ) -> dict:
        with session_factory() as db:
            _require(db, ctx, MANAGE_VIEWS)
            view = view_service.get_view(db, view_id)
            if view is None:
                raise ToolError(f"View {view_id} not found")
            config = dict(view.config or {})
            if sort is not None:
                config["sort"] = {"slug": sort, "dir": "desc" if sort_desc else "asc"}
            elif sort_desc is not None and "sort" in config:
                config["sort"] = {**config["sort"], "dir": "desc" if sort_desc else "asc"}
            if filters is not None:
                config["filters"] = filters
            if columns is not None:
                config["columns"] = columns
            if filter_op is not None:
                config["filter_op"] = filter_op if filter_op in ("and", "or") else "and"
            new_icon = view.icon if icon is None else icon
            view_service.update_view(db, view, name or view.name, config, icon=new_icon)
            return {"id": view.id, "name": view.name, "config": config}

    @server.tool(description="Delete a view (manage_views).")
    def delete_view(view_id: int, ctx: Context) -> dict:
        with session_factory() as db:
            _require(db, ctx, MANAGE_VIEWS)
            view = view_service.get_view(db, view_id)
            if view is None:
                raise ToolError(f"View {view_id} not found")
            view_service.delete_view(db, view)
            return {"deleted": True, "id": view_id}

    # ---------------------------------------------------- dashboard widgets

    @server.tool(description="List dashboard widgets (manage_dashboard — admin).")
    def list_dashboard_widgets(ctx: Context) -> list[dict]:
        with session_factory() as db:
            _require(db, ctx, MANAGE_DASHBOARD)
            widgets = db.execute(
                select(DashboardWidget).order_by(DashboardWidget.sort_order)
            ).scalars()
            return [
                {
                    "id": w.id,
                    "title": w.title,
                    "widget_type": w.widget_type,
                    "entity_id": w.entity_id,
                    "span": w.span,
                    "config": w.config,
                }
                for w in widgets
            ]

    return server
