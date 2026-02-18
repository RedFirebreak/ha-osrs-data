"""Tests for the OSRS Data HTTP API endpoints."""

from __future__ import annotations

import json
import os
import sys
from typing import Any
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
    "homeassistant.components.webhook",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

# Provide a minimal HomeAssistantView mock
_http_mod = sys.modules["homeassistant.components.http"]


class _MockView:
    """Minimal HomeAssistantView stand-in."""
    requires_auth = True

    def json(self, data, status_code=200):
        from aiohttp.web import json_response
        return json_response(data, status=status_code)


_http_mod.HomeAssistantView = _MockView

# Force re-import of the api module
sys.modules.pop("custom_components.osrs_data.api", None)

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.api import (  # noqa: E402
    OsrsDeviceRevokeView,
    OsrsDevicesView,
    OsrsEventsView,
    OsrsPairView,
)
from custom_components.osrs_data.account_store import AccountStore  # noqa: E402
from custom_components.osrs_data.const import (  # noqa: E402
    DATA_ACCOUNT_STORE,
    DATA_DEDUPE_CACHE,
    DATA_HISTORY_STORE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    DOMAIN,
)
from custom_components.osrs_data.dedupe import DedupeCache  # noqa: E402
from custom_components.osrs_data.history import HistoryStore  # noqa: E402
from custom_components.osrs_data.pairing import PairingStore  # noqa: E402


# ── Sample payloads ──────────────────────────────────────────────────

LEVEL_PAYLOAD: dict[str, Any] = {
    "type": "LEVEL",
    "playerName": "PlayerOne",
    "accountType": "NORMAL",
    "dinkAccountHash": "hashAAA",
    "extra": {
        "levelledSkills": {"Attack": 70},
        "combatLevel": {"value": 85, "increased": True},
    },
}


def _make_hass_with_pairing():
    """Create a mock hass with pairing store wired up."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    store = AccountStore()
    pairing_store = PairingStore()
    mock_storage = MagicMock()
    entry_id = "test_entry"
    hass.data = {
        DOMAIN: {
            entry_id: {
                DATA_ACCOUNT_STORE: store,
                DATA_HISTORY_STORE: HistoryStore(),
                DATA_DEDUPE_CACHE: DedupeCache(),
                DATA_PAIRING_STORE: pairing_store,
                DATA_STORE: mock_storage,
            }
        }
    }
    return hass, store, pairing_store, mock_storage


def _make_json_request(hass, payload, headers=None):
    """Create a mock aiohttp request with JSON body."""
    request = MagicMock()
    request.app = {"hass": hass}
    request.headers = {"Content-Type": "application/json"}
    if headers:
        request.headers.update(headers)
    request.json = AsyncMock(return_value=payload)
    request.post = AsyncMock(return_value={})
    return request


# ── Pair endpoint tests ──────────────────────────────────────────────


class TestOsrsPairView:
    @pytest.mark.asyncio
    async def test_pair_valid_code(self):
        """Consuming a valid pairing code returns device token."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code("My Plugin")

        view = OsrsPairView()
        request = _make_json_request(hass, {"code": code})
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        assert "device_id" in body
        assert "token" in body

    @pytest.mark.asyncio
    async def test_pair_invalid_code(self):
        """Invalid pairing code returns 403."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()

        view = OsrsPairView()
        request = _make_json_request(hass, {"code": "000000"})
        result = await view.post(request)

        assert result.status == 403
        body = json.loads(result.body)
        assert body["ok"] is False

    @pytest.mark.asyncio
    async def test_pair_missing_code(self):
        """Missing code field returns 400."""
        hass, _, _, _ = _make_hass_with_pairing()

        view = OsrsPairView()
        request = _make_json_request(hass, {})
        result = await view.post(request)

        assert result.status == 400
        body = json.loads(result.body)
        assert body["ok"] is False

    @pytest.mark.asyncio
    async def test_pair_code_consumed_once(self):
        """Code can only be used once."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()

        view = OsrsPairView()
        r1 = await view.post(_make_json_request(hass, {"code": code}))
        r2 = await view.post(_make_json_request(hass, {"code": code}))

        assert r1.status == 200
        assert r2.status == 403


# ── Events endpoint tests ───────────────────────────────────────────


class TestOsrsEventsView:
    @pytest.mark.asyncio
    async def test_events_with_valid_token(self):
        """Valid token allows event submission."""
        hass, store, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]

        view = OsrsEventsView()
        request = _make_json_request(
            hass, LEVEL_PAYLOAD, headers={"X-Osrs-Token": token}
        )
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        hass.bus.async_fire.assert_called_once()

        # Account should be updated
        acct = store.get_or_create("hashAAA", "PlayerOne")
        assert acct.last_event_type == "LEVEL"

    @pytest.mark.asyncio
    async def test_events_missing_token(self):
        """Missing token returns 401."""
        hass, _, _, _ = _make_hass_with_pairing()

        view = OsrsEventsView()
        request = _make_json_request(hass, LEVEL_PAYLOAD)
        result = await view.post(request)

        assert result.status == 401
        body = json.loads(result.body)
        assert body["ok"] is False

    @pytest.mark.asyncio
    async def test_events_invalid_token(self):
        """Invalid token returns 403."""
        hass, _, _, _ = _make_hass_with_pairing()

        view = OsrsEventsView()
        request = _make_json_request(
            hass, LEVEL_PAYLOAD, headers={"X-Osrs-Token": "bad_token"}
        )
        result = await view.post(request)

        assert result.status == 403
        body = json.loads(result.body)
        assert body["ok"] is False

    @pytest.mark.asyncio
    async def test_events_revoked_token(self):
        """Revoked token returns 403."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]
        pairing_store.revoke_device(pair_result["device_id"])

        view = OsrsEventsView()
        request = _make_json_request(
            hass, LEVEL_PAYLOAD, headers={"X-Osrs-Token": token}
        )
        result = await view.post(request)

        assert result.status == 403

    @pytest.mark.asyncio
    async def test_events_fires_ha_event(self):
        """Valid event submission fires HA event."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]

        view = OsrsEventsView()
        request = _make_json_request(
            hass, LEVEL_PAYLOAD, headers={"X-Osrs-Token": token}
        )
        await view.post(request)

        hass.bus.async_fire.assert_called_once()
        event_name, event_data = hass.bus.async_fire.call_args[0]
        assert event_name == "osrs_data_event"
        assert event_data["event_type"] == "LEVEL"

    @pytest.mark.asyncio
    async def test_events_schedules_save(self):
        """Event submission schedules a save."""
        hass, _, pairing_store, mock_storage = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]

        view = OsrsEventsView()
        request = _make_json_request(
            hass, LEVEL_PAYLOAD, headers={"X-Osrs-Token": token}
        )
        await view.post(request)

        mock_storage.async_delay_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_events_deduplication(self):
        """Duplicate events are detected."""
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)
        token = pair_result["token"]

        view = OsrsEventsView()
        r1 = await view.post(
            _make_json_request(hass, LEVEL_PAYLOAD, headers={"X-Osrs-Token": token})
        )
        r2 = await view.post(
            _make_json_request(hass, LEVEL_PAYLOAD, headers={"X-Osrs-Token": token})
        )

        body1 = json.loads(r1.body)
        body2 = json.loads(r2.body)
        assert body1["ok"] is True
        assert body2["ok"] is True
        assert body2.get("duplicate") is True


# ── Devices endpoint tests ──────────────────────────────────────────


class TestOsrsDevicesView:
    @pytest.mark.asyncio
    async def test_list_devices_empty(self):
        hass, _, _, _ = _make_hass_with_pairing()
        view = OsrsDevicesView()
        request = _make_json_request(hass, {})
        result = await view.get(request)
        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True
        assert body["devices"] == []

    @pytest.mark.asyncio
    async def test_list_devices_with_paired(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code("My Device")
        pairing_store.consume_pairing_code(code)

        view = OsrsDevicesView()
        request = _make_json_request(hass, {})
        result = await view.get(request)

        body = json.loads(result.body)
        assert len(body["devices"]) == 1
        assert body["devices"][0]["name"] == "My Device"


class TestOsrsDeviceRevokeView:
    @pytest.mark.asyncio
    async def test_revoke_existing_device(self):
        hass, _, pairing_store, _ = _make_hass_with_pairing()
        code = pairing_store.create_pairing_code()
        pair_result = pairing_store.consume_pairing_code(code)

        view = OsrsDeviceRevokeView()
        request = _make_json_request(hass, {})
        result = await view.delete(request, pair_result["device_id"])

        assert result.status == 200
        body = json.loads(result.body)
        assert body["ok"] is True

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_device(self):
        hass, _, _, _ = _make_hass_with_pairing()

        view = OsrsDeviceRevokeView()
        request = _make_json_request(hass, {})
        result = await view.delete(request, "nonexistent_id")

        assert result.status == 404
        body = json.loads(result.body)
        assert body["ok"] is False
