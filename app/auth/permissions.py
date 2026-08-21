"""Role-based capability model.

Capabilities are named strings checked at the service/route layer via a single
:func:`has_capability` function. Roles map to a fixed set of capabilities.
"""

from __future__ import annotations

from app.models.enums import Role
from app.models.user import User

READ = "read"
CREATE_RECORD = "create_record"
UPDATE_RECORD = "update_record"
DELETE_RECORD = "delete_record"
MANAGE_SCHEMA = "manage_schema"
MANAGE_VIEWS = "manage_views"
MANAGE_USERS = "manage_users"
MANAGE_DASHBOARD = "manage_dashboard"

_CAPABILITIES: dict[Role, frozenset[str]] = {
    Role.ADMIN: frozenset(
        {
            READ,
            CREATE_RECORD,
            UPDATE_RECORD,
            DELETE_RECORD,
            MANAGE_SCHEMA,
            MANAGE_VIEWS,
            MANAGE_USERS,
            MANAGE_DASHBOARD,
        }
    ),
    Role.MAINTAINER: frozenset(
        {
            READ,
            CREATE_RECORD,
            UPDATE_RECORD,
            MANAGE_VIEWS,
        }
    ),
    Role.VIEWER: frozenset({READ}),
}


def capabilities_for(role: Role) -> frozenset[str]:
    """The capability set granted to ``role``."""
    return _CAPABILITIES.get(role, frozenset())


def has_capability(user: User, capability: str) -> bool:
    """Return True if ``user`` has ``capability``."""
    return capability in _CAPABILITIES.get(user.role_enum, frozenset())
