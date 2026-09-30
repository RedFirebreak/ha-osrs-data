"""Tests for the OSRS icon resolver (icons.py)."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from unittest.mock import MagicMock

import aiohttp
import pytest

# Mock homeassistant before imports
for mod_name in (
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.components.sensor",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.const import DEFAULT_ICONS_BASE_URL  # noqa: E402
from custom_components.osrs_data.icons import (  # noqa: E402
    SKILLS,
    IconResolver,
    icons_base,
    stacked_item_id,
)

BASE = "https://icons.example"
STACKS = {
    "995": [
        [2, 996], [3, 997], [4, 998], [5, 999], [25, 1000],
        [100, 1001], [250, 1002], [1000, 1003], [10000, 1004],
    ]
}


class _Response:
    def __init__(self, data=None, status=200, error: Exception | None = None):
        self._data = data
        self._status = status
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self._status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=MagicMock(), history=(), status=self._status
            )

    async def json(self, content_type=None):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class _Session:
    """Minimal aiohttp.ClientSession stand-in: ``get`` returns *response*."""

    def __init__(self, response: _Response):
        self.response = response
        self.urls: list[str] = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self.response


class TestBase:
    def test_default(self):
        assert icons_base(None) == DEFAULT_ICONS_BASE_URL
        assert IconResolver().base == "https://icons.scapekeeper.com"

    def test_trailing_slashes_and_whitespace(self):
        assert icons_base("  https://icons.example//  ") == BASE
        assert IconResolver("https://icons.example/").base == BASE

    def test_empty_disables(self):
        for value in ("", "   ", "/"):
            resolver = IconResolver(value)
            assert resolver.base is None
            assert resolver.enabled is False
            assert resolver.item_url(4151) is None
            assert resolver.skill_url("Attack") is None
            assert resolver.slot_url("HEAD") is None


class TestStacks:
    def test_breakpoints(self):
        assert stacked_item_id(STACKS, 995, 1) == 995
        assert stacked_item_id(STACKS, 995, 2) == 996
        assert stacked_item_id(STACKS, 995, 250) == 1002
        assert stacked_item_id(STACKS, 995, 9999) == 1003
        assert stacked_item_id(STACKS, 995, 10000) == 1004
        assert stacked_item_id(STACKS, 4151, 5) == 4151
        assert stacked_item_id(None, 995, 5) == 995

    def test_bad_quantity_counts_as_one(self):
        assert stacked_item_id(STACKS, 995, None) == 995
        assert stacked_item_id(STACKS, 995, "250") == 995


class TestUrls:
    def test_item_url_uses_stack_variant(self):
        resolver = IconResolver(BASE)
        resolver.stacks = STACKS
        assert resolver.item_url(995, 100) == f"{BASE}/items/1001.webp"
        assert resolver.item_url(995) == f"{BASE}/items/995.webp"
        assert resolver.item_url(4151, 1) == f"{BASE}/items/4151.webp"

    def test_item_url_unknown_id(self):
        resolver = IconResolver(BASE)
        for item_id in (None, -1, "4151", True, 1.5):
            assert resolver.item_url(item_id) is None

    def test_skill_url(self):
        resolver = IconResolver(BASE)
        assert resolver.skill_url("Attack") == f"{BASE}/skills/attack.png"
        assert resolver.skill_url("sailing") == f"{BASE}/skills/sailing.png"
        assert resolver.skill_url("Overall") is None
        assert resolver.skill_url("Hunter XP") is None
        assert resolver.skill_url(None) is None
        assert len(SKILLS) == 24

    def test_slot_url(self):
        resolver = IconResolver(BASE)
        assert resolver.slot_url("AMULET") == f"{BASE}/slots/amulet.png"
        # The quiver's extra ammo slot has no silhouette.
        assert resolver.slot_url("AMMO_EXTRA") is None


class TestRefresh:
    def test_loads_stacks(self):
        resolver = IconResolver(BASE + "/")
        session = _Session(_Response(STACKS))
        assert asyncio.run(resolver.async_refresh(session)) is True
        assert session.urls == [f"{BASE}/data/stacks.json"]
        assert resolver.item_url(995, 250) == f"{BASE}/items/1002.webp"
        # Same tables again: nothing changed.
        assert asyncio.run(resolver.async_refresh(session)) is False

    def test_bad_entries_are_left_out(self):
        resolver = IconResolver(BASE)
        data = {"995": [[250, 1002], [2, 996], ["x", 1], [3]], "1": "nope", "2": []}
        assert asyncio.run(resolver.async_refresh(_Session(_Response(data)))) is True
        assert resolver.stacks == {"995": [[2, 996], [250, 1002]]}

    @pytest.mark.parametrize(
        "response",
        [
            _Response(status=404),
            _Response(status=503),
            _Response(error=aiohttp.ClientConnectionError("down")),
            _Response(error=asyncio.TimeoutError()),
            _Response(ValueError("not json")),
            _Response(["not", "an", "object"]),
        ],
    )
    def test_failure_keeps_previous_stacks(self, response):
        resolver = IconResolver(BASE)
        resolver.stacks = {"995": [[2, 996]]}
        assert asyncio.run(resolver.async_refresh(_Session(response))) is False
        assert resolver.stacks == {"995": [[2, 996]]}

    def test_failure_warns_once(self, caplog):
        resolver = IconResolver(BASE)
        session = _Session(_Response(status=503))
        with caplog.at_level(logging.DEBUG, logger="custom_components.osrs_data.icons"):
            asyncio.run(resolver.async_refresh(session))
            asyncio.run(resolver.async_refresh(session))
            session.response = _Response(STACKS)
            asyncio.run(resolver.async_refresh(session))
            session.response = _Response(status=503)
            asyncio.run(resolver.async_refresh(session))
        levels = [r.levelname for r in caplog.records if "stack tables from" in r.message]
        assert levels == ["WARNING", "DEBUG", "DEBUG", "WARNING"]

    def test_disabled_does_not_fetch(self):
        resolver = IconResolver("")
        session = _Session(_Response(STACKS))
        assert asyncio.run(resolver.async_refresh(session)) is False
        assert session.urls == []
