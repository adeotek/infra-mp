"""Domain models.

Importing this package registers every model with :class:`app.db.Base`, which
is what Alembic autogenerate and ``Base.metadata.create_all`` rely on.
"""

from app.models.attribute import Attribute
from app.models.dashboard import DashboardWidget
from app.models.entity import Entity
from app.models.record import Record
from app.models.session import AuthSession
from app.models.user import User
from app.models.view import View

__all__ = [
    "Attribute",
    "AuthSession",
    "DashboardWidget",
    "Entity",
    "Record",
    "User",
    "View",
]
