"""Tests for form parsing helpers."""

import asyncio

from app.form import parse_form, to_list


class _FakeForm:
    def __init__(self, items):
        self._items = items

    def multi_items(self):
        return iter(self._items)


class _FakeRequest:
    def __init__(self, items):
        self._form = _FakeForm(items)

    async def form(self):
        return self._form


def test_to_list():
    assert to_list(None) == []
    assert to_list("x") == ["x"]
    assert to_list(["a", "b"]) == ["a", "b"]
    assert to_list([1, 2]) == ["1", "2"]


def test_parse_form_single_values():
    req = _FakeRequest([("name", "a"), ("cores", "4")])
    assert asyncio.run(parse_form(req)) == {"name": "a", "cores": "4"}


def test_parse_form_repeated_keys_become_lists():
    req = _FakeRequest([("tag", "a"), ("tag", "b"), ("tag", "c")])
    assert asyncio.run(parse_form(req)) == {"tag": ["a", "b", "c"]}


def test_parse_form_mixed_single_and_repeated():
    req = _FakeRequest([("name", "x"), ("tag", "a"), ("tag", "b")])
    assert asyncio.run(parse_form(req)) == {"name": "x", "tag": ["a", "b"]}
