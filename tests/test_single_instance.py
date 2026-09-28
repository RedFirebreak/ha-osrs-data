"""Only one config entry is supported: every entry shares one storage file."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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

import custom_components.osrs_data as integration  # noqa: E402
from custom_components.osrs_data.const import DOMAIN  # noqa: E402


def _read_json(*parts: str) -> dict:
    with open(os.path.join(_root, *parts), encoding="utf-8") as handle:
        return json.load(handle)


def _entry(entry_id: str) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = f"OSRS Data ({entry_id})"
    return entry


class TestManifest:
    def test_single_config_entry(self):
        manifest = _read_json("custom_components", "osrs_data", "manifest.json")
        assert manifest.get("single_config_entry") is True

    def test_minimum_ha_version_supports_single_config_entry(self):
        # ``single_config_entry`` was added in Home Assistant 2024.3.
        minimum = _read_json("hacs.json")["homeassistant"]
        assert tuple(int(p) for p in minimum.split(".")[:2]) >= (2024, 3)


class TestExistingDuplicateEntries:
    """Installs that already have a second entry from an older version."""

    @pytest.mark.asyncio
    async def test_duplicate_entry_is_not_set_up(self):
        hass = MagicMock()
        hass.data = {DOMAIN: {"first": {}, "_views_registered": True}}
        with patch.object(integration, "get_store") as get_store:
            result = await integration.async_setup_entry(hass, _entry("second"))
        assert result is False
        get_store.assert_not_called()
        assert "second" not in hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_removing_a_duplicate_keeps_shared_storage(self):
        hass = MagicMock()
        first, second = _entry("first"), _entry("second")
        hass.config_entries.async_entries.return_value = [first, second]
        store = MagicMock()
        store.async_remove = AsyncMock()
        with patch.object(integration, "get_store", return_value=store):
            await integration.async_remove_entry(hass, second)
        store.async_remove.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_removing_the_last_entry_removes_storage(self):
        hass = MagicMock()
        only = _entry("only")
        hass.config_entries.async_entries.return_value = [only]
        store = MagicMock()
        store.async_remove = AsyncMock()
        with patch.object(integration, "get_store", return_value=store):
            await integration.async_remove_entry(hass, only)
        store.async_remove.assert_awaited_once()
