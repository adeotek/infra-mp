"""Slug generation utilities."""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session


def slugify(value: str) -> str:
    """Convert a human-readable name into a URL/identifier-safe slug."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "unnamed"


def unique_slug(
    db: Session,
    model,
    name: str,
    *,
    scope: dict | None = None,
    exclude_id: int | None = None,
) -> str:
    """Return a slug unique for ``model``.

    ``scope`` restricts uniqueness to a subset (e.g. per-entity for
    attributes and views); ``exclude_id`` ignores an existing row on rename.
    """
    base = slugify(name)
    slug = base
    counter = 2
    while True:
        query = select(model.id).where(model.slug == slug)
        if scope:
            for column, value in scope.items():
                query = query.where(column == value)
        if exclude_id is not None:
            query = query.where(model.id != exclude_id)
        if db.execute(query).first() is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1
