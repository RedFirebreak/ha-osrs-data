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
        assert "Attack" in acct.detail_sensors

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
        assert "Attack" in acct_a.detail_sensors
        assert "Defence" in acct_b.detail_sensors

    @pytest.mark.asyncio
    async def test_same_account_multiple_updates(self):
        """Same account receives multiple updates, skills change."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PLAYER_ONE_PAYLOAD, token))
        await view.post(_make_json_request(hass, PLAYER_ONE_UPDATED_PAYLOAD, token))

        acct = store.get_or_create(None, "PlayerOne")
        assert acct.detail_sensors["Attack"]["value"] == 70
        assert acct.detail_sensors["Attack"]["attributes"]["xp"] == 900000

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


# ── ClientShutdown / presence through API tests ─────────────────────

PLAYER_ONE_SHUTDOWN_PAYLOAD: dict[str, Any] = {
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
    },
    "events": [
        {"type": "ClientShutdown", "data": "Shutdown"},
    ],
}

PLAYER_ONE_LOGOUT_PAYLOAD: dict[str, Any] = {
    "player": {
        "name": "PlayerOne",
        "accountType": "normal",
        "world": "302",
        "stats": {"skills": {}},
        "inventory": {"items": []},
        "equipment": {"items": []},
    },
    "events": [
        {"type": "LOGOUT"},
    ],
}


class TestClientShutdownIntegration:
    """End-to-end: ClientShutdown / Logout events through the API mark account offline."""

    @pytest.mark.asyncio
    async def test_client_shutdown_marks_offline(self):
        """A ClientShutdown event through the API sets the account offline."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        # First: normal heartbeat → online
        r1 = await view.post(_make_json_request(hass, PLAYER_ONE_PAYLOAD, token))
        assert r1.status == 200

        acct = store.get_or_create(None, "PlayerOne")
        assert acct.is_online is True
        assert acct.offline_reason == "online"

        # Second: ClientShutdown → offline
        r2 = await view.post(
            _make_json_request(hass, PLAYER_ONE_SHUTDOWN_PAYLOAD, token)
        )
        assert r2.status == 200

        assert acct.is_online is False
        assert acct.offline_reason == "Shutdown"

    @pytest.mark.asyncio
    async def test_logout_event_marks_offline(self):
        """A LOGOUT event through the API sets the account offline."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PLAYER_ONE_PAYLOAD, token))
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.is_online is True

        await view.post(_make_json_request(hass, PLAYER_ONE_LOGOUT_PAYLOAD, token))
        assert acct.is_online is False
        assert acct.offline_reason == "logout"

    @pytest.mark.asyncio
    async def test_normal_heartbeat_after_shutdown_goes_online(self):
        """A normal heartbeat after shutdown brings the account back online."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PLAYER_ONE_PAYLOAD, token))
        acct = store.get_or_create(None, "PlayerOne")
        assert acct.is_online is True

        await view.post(
            _make_json_request(hass, PLAYER_ONE_SHUTDOWN_PAYLOAD, token)
        )
        assert acct.is_online is False

        # Use an updated payload (different world) to avoid dedupe with the
        # first heartbeat — mirrors real reconnection where data changes.
        reconnect_payload: dict[str, Any] = {
            "player": {
                "name": "PlayerOne",
                "accountType": "normal",
                "world": "400",
                "stats": {"skills": {}},
                "inventory": {"items": []},
                "equipment": {"items": []},
                "events": [],
            }
        }
        await view.post(_make_json_request(hass, reconnect_payload, token))
        assert acct.is_online is True
        assert acct.offline_reason == "online"

    @pytest.mark.asyncio
    async def test_shutdown_persists_in_saved_data(self):
        """Offline state from shutdown is reflected in persisted account data."""
        hass, store, token, mock_storage = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(
            _make_json_request(hass, PLAYER_ONE_SHUTDOWN_PAYLOAD, token)
        )

        save_callback = mock_storage.async_delay_save.call_args[0][0]
        payload = save_callback()
        acct_data = payload["accounts"][0]
        assert acct_data["is_online"] is False
        assert acct_data["offline_reason"] == "Shutdown"

    @pytest.mark.asyncio
    async def test_shutdown_only_payload_marks_offline(self):
        """ClientShutdown as the very first (and only) event marks account offline."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        r = await view.post(
            _make_json_request(hass, PLAYER_ONE_SHUTDOWN_PAYLOAD, token)
        )
        assert r.status == 200

        acct = store.get_or_create(None, "PlayerOne")
        assert acct.is_online is False
        assert acct.offline_reason == "Shutdown"

    @pytest.mark.asyncio
    async def test_realistic_runelite_shutdown_payload(self):
        """Full realistic RuneLite payload with root-level ClientShutdown."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        # First: normal heartbeat
        normal_payload: dict[str, Any] = {
            "player": {
                "name": "TestPlayer",
                "accountType": "0",
                "world": "395",
                "stats": {"skills": {"Attack": {"xp": 6124520, "level": 91}}},
                "inventory": {"items": []},
                "equipment": {"items": []},
            },
            "events": [],
            "state": "LOGGED_IN",
        }
        await view.post(_make_json_request(hass, normal_payload, token))
        acct = store.get_or_create(None, "TestPlayer")
        assert acct.is_online is True

        # Second: ClientShutdown at root level (real RuneLite format)
        shutdown_payload: dict[str, Any] = {
            "player": {
                "name": "TestPlayer",
                "accountType": "0",
                "world": "395",
                "stats": {"skills": {"Attack": {"xp": 6124520, "level": 91}}},
                "inventory": {"items": []},
                "equipment": {"items": []},
            },
            "events": [
                {"type": "ClientShutdown", "data": "Shutdown"},
            ],
            "state": "LOGGED_IN",
        }
        await view.post(_make_json_request(hass, shutdown_payload, token))
        assert acct.is_online is False
        assert acct.offline_reason == "Shutdown"

    @pytest.mark.asyncio
    async def test_tick_delay_stored_through_api(self):
        """tickDelay from RuneLite payload is stored on the account."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        payload: dict[str, Any] = {
            "player": {
                "name": "PlayerOne",
                "accountType": "normal",
                "world": "302",
                "stats": {"skills": {}},
                "inventory": {"items": []},
                "equipment": {"items": []},
            },
            "events": [],
            "tickDelay": 20,
            "state": "LOGGED_IN",
        }
        r = await view.post(_make_json_request(hass, payload, token))
        assert r.status == 200

        acct = store.get_or_create(None, "PlayerOne")
        assert acct.tick_delay == 20
        assert acct.presence_timeout == 18

    @pytest.mark.asyncio
    async def test_tick_delay_persisted_in_save(self):
        """tickDelay is included in the save payload."""
        hass, store, token, mock_storage = _setup_hass_and_token()
        view = OsrsEventsView()

        payload: dict[str, Any] = {
            "player": {
                "name": "PlayerOne",
                "accountType": "normal",
                "world": "302",
                "stats": {"skills": {}},
                "inventory": {"items": []},
                "equipment": {"items": []},
            },
            "tickDelay": 20,
        }
        await view.post(_make_json_request(hass, payload, token))

        save_callback = mock_storage.async_delay_save.call_args[0][0]
        saved = save_callback()
        assert saved["accounts"][0]["tick_delay"] == 20
