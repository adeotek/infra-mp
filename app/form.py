"""Form parsing helpers."""

from __future__ import annotations

from typing import Any

from fastapi import Request


async def parse_form(request: Request) -> dict[str, Any]:
    """Read form data into a dict, collapsing repeated keys into lists."""
    form = await request.form()
    raw: dict[str, Any] = {}
    for key, value in form.multi_items():
        if key in raw:
            if isinstance(raw[key], list):
                raw[key].append(value)
            else:
                raw[key] = [raw[key], value]
        else:
            raw[key] = value
    return raw


def to_list(value: Any) -> list[str]:
    """Normalise a form value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]
