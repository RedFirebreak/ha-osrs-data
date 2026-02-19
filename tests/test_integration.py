"""Integration tests: events API → parser → account store → signal."""

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

from custom_components.osrs_data.account_store import AccountStore  # noqa: E402
from custom_components.osrs_data.api import OsrsEventsView  # noqa: E402
from custom_components.osrs_data.const import (  # noqa: E402
    DATA_ACCOUNT_STORE,
    DATA_DEDUPE_CACHE,
    DATA_HISTORY_STORE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    DOMAIN,
    SIGNAL_ACCOUNT_UPDATED,
)
from custom_components.osrs_data.dedupe import DedupeCache  # noqa: E402
from custom_components.osrs_data.history import HistoryStore  # noqa: E402
from custom_components.osrs_data.pairing import PairingStore  # noqa: E402


# ── Sample payloads ──────────────────────────────────────────────────

PLAYER_ONE_PAYLOAD: dict[str, Any] = {
    "player": {
        "name": "PlayerOne",
        "accountType": "normal",
        "world": "302",
        "stats": {
            "skills": {
                "Attack": {"xp": 737627, "level": 60},
            }
        },
        "inventory": {"items": []},
        "equipment": {"items": []},
        "events": [],
    }
}

PLAYER_TWO_PAYLOAD: dict[str, Any] = {
    "player": {
        "name": "PlayerTwo",
        "accountType": "iron",
        "world": "303",
        "stats": {
            "skills": {
                "Defence": {"xp": 123456, "level": 50},
            }
        },
        "inventory": {"items": []},
        "equipment": {"items": []},
        "events": [],
    }
}

PLAYER_ONE_UPDATED_PAYLOAD: dict[str, Any] = {
    "player": {
        "name": "PlayerOne",
        "accountType": "normal",
        "world": "302",
        "stats": {
            "skills": {
                "Attack": {"xp": 900000, "level": 70},
            }
        },
        "inventory": {"items": []},
        "equipment": {"items": []},
        "events": [],
    }
}


def _setup_hass_and_token():
    """Create a mock hass with account store and return (hass, store, token, mock_storage)."""
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

    # Pair a device to get a token
    code = pairing_store.create_pairing_code()
    result = pairing_store.consume_pairing_code(code)
    token = result["token"]

    return hass, store, token, mock_storage


def _make_json_request(hass, payload, token):
    """Create a mock request with JSON body and auth token."""
    request = MagicMock()
    request.app = {"hass": hass}
    request.headers = {
        "Content-Type": "application/json",
        "X-Osrs-Token": token,
    }
    request.json = AsyncMock(return_value=payload)
    request.post = AsyncMock(return_value={})
    return request


class TestEventsIntegration:
    """End-to-end tests: events API handler updates account store."""

    @pytest.mark.asyncio
    async def test_player_data_updates_account_store(self):
        """Player data payload updates account state correctly."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PLAYER_ONE_PAYLOAD, token)
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body == {"ok": True}
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.account_type == "normal"
        assert acct.world == "302"
        assert "Attack XP" in acct.detail_sensors

    @pytest.mark.asyncio
    async def test_multi_account_separate_state(self):
        """Two different accounts get separate state."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PLAYER_ONE_PAYLOAD, token))
        await view.post(_make_json_request(hass, PLAYER_TWO_PAYLOAD, token))

        acct_a = store.get_or_create(None, "PlayerOne")
        acct_b = store.get_or_create(None, "PlayerTwo")

        assert acct_a.account_type == "normal"
        assert acct_b.account_type == "iron"
        assert "Attack XP" in acct_a.detail_sensors
        assert "Defence XP" in acct_b.detail_sensors

    @pytest.mark.asyncio
    async def test_same_account_multiple_updates(self):
        """Same account receives multiple updates, skills change."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PLAYER_ONE_PAYLOAD, token))
        await view.post(_make_json_request(hass, PLAYER_ONE_UPDATED_PAYLOAD, token))

        acct = store.get_or_create(None, "PlayerOne")
        assert acct.detail_sensors["Attack XP"]["value"] == 900000
        assert acct.detail_sensors["Attack Level"]["value"] == 70

    @pytest.mark.asyncio
    async def test_dispatcher_signal_fired(self):
        """Verify dispatcher signal is sent for account updates."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PLAYER_ONE_PAYLOAD, token)

        # Patch dispatcher
        with patch(
            "custom_components.osrs_data.api.async_dispatcher_send"
        ) as mock_signal:
            await view.post(request)
            mock_signal.assert_called_once()
            call_args = mock_signal.call_args[0]
            assert call_args[0] is hass
            assert call_args[1] == SIGNAL_ACCOUNT_UPDATED

    @pytest.mark.asyncio
    async def test_invalid_payload_returns_400(self):
        """Payload without player data returns 400."""
        hass, store, token, _ = _setup_hass_and_token()
        payload = {"not_player": "data"}
        view = OsrsEventsView()
        request = _make_json_request(hass, payload, token)
        result = await view.post(request)

        assert result.status == 400
        body = json.loads(result.body)
        assert body["ok"] is False
        assert len(store.accounts) == 0

    @pytest.mark.asyncio
    async def test_events_schedules_save(self):
        """Events handler schedules a deferred save to persist state."""
        hass, store, token, mock_storage = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PLAYER_ONE_PAYLOAD, token)
        await view.post(request)

        mock_storage.async_delay_save.assert_called_once()
        # Verify the callback produces a payload with accounts
        save_callback = mock_storage.async_delay_save.call_args[0][0]
        payload = save_callback()
        assert "accounts" in payload
        assert len(payload["accounts"]) == 1
        assert payload["accounts"][0]["player_name"] == "PlayerOne"
