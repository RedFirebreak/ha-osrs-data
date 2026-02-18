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

DEATH_PAYLOAD: dict[str, Any] = {
    "type": "DEATH",
    "playerName": "PlayerTwo",
    "accountType": "IRONMAN",
    "dinkAccountHash": "hashBBB",
    "extra": {
        "valueLost": 5000,
        "isPvp": False,
        "keptItems": [],
        "lostItems": [],
    },
}

QUEST_PAYLOAD: dict[str, Any] = {
    "type": "QUEST",
    "playerName": "PlayerOne",
    "accountType": "NORMAL",
    "dinkAccountHash": "hashAAA",
    "extra": {
        "questName": "Dragon Slayer I",
        "completedQuests": 22,
        "totalQuests": 156,
        "questPoints": 44,
        "totalQuestPoints": 293,
    },
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
    async def test_level_updates_account_store(self):
        """LEVEL event updates account state for correct account."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, LEVEL_PAYLOAD, token)
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body == {"ok": True}
        acct = store.get_or_create("hashAAA", "PlayerOne")
        assert acct.last_event_type == "LEVEL"
        assert "Attack" in acct.last_event_summary

    @pytest.mark.asyncio
    async def test_multi_account_separate_state(self):
        """Two different accounts get separate state."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, LEVEL_PAYLOAD, token))
        await view.post(_make_json_request(hass, DEATH_PAYLOAD, token))

        acct_a = store.get_or_create("hashAAA", "PlayerOne")
        acct_b = store.get_or_create("hashBBB", "PlayerTwo")

        assert acct_a.last_event_type == "LEVEL"
        assert acct_b.last_event_type == "DEATH"

    @pytest.mark.asyncio
    async def test_same_account_multiple_events(self):
        """Same account receives multiple events, last event updates."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, LEVEL_PAYLOAD, token))
        await view.post(_make_json_request(hass, QUEST_PAYLOAD, token))

        acct = store.get_or_create("hashAAA", "PlayerOne")
        assert acct.last_event_type == "QUEST"

    @pytest.mark.asyncio
    async def test_dispatcher_signal_fired(self):
        """Verify dispatcher signal is sent for account updates."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, LEVEL_PAYLOAD, token)

        # Patch dispatcher
        with patch(
            "custom_components.osrs_data.api.async_dispatcher_send"
        ) as mock_signal:
            await view.post(request)
            mock_signal.assert_called_once_with(
                hass, SIGNAL_ACCOUNT_UPDATED, "hashAAA"
            )

    @pytest.mark.asyncio
    async def test_unsupported_type_no_store_update(self):
        """Unsupported event types don't update the store."""
        hass, store, token, _ = _setup_hass_and_token()
        payload = {
            "type": "LOGIN",
            "playerName": "Player",
            "dinkAccountHash": "hashXYZ",
            "extra": {},
        }
        view = OsrsEventsView()
        request = _make_json_request(hass, payload, token)
        result = await view.post(request)

        assert result.status == 200
        body = json.loads(result.body)
        assert body == {"ok": True}
        # The account should NOT be created since LOGIN is not a parsed type
        assert len(store.accounts) == 0

    @pytest.mark.asyncio
    async def test_no_embeds_dependency(self):
        """Parsing does not depend on embeds being present."""
        hass, store, token, _ = _setup_hass_and_token()
        payload = dict(LEVEL_PAYLOAD)
        payload.pop("embeds", None)
        view = OsrsEventsView()
        request = _make_json_request(hass, payload, token)

        result = await view.post(request)
        assert result.status == 200
        acct = store.get_or_create("hashAAA", "PlayerOne")
        assert acct.last_event_type == "LEVEL"

    @pytest.mark.asyncio
    async def test_events_schedules_save(self):
        """Events handler schedules a deferred save to persist state."""
        hass, store, token, mock_storage = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, LEVEL_PAYLOAD, token)
        await view.post(request)

        mock_storage.async_delay_save.assert_called_once()
        # Verify the callback produces a payload with accounts
        save_callback = mock_storage.async_delay_save.call_args[0][0]
        payload = save_callback()
        assert "accounts" in payload
        assert len(payload["accounts"]) == 1
        assert payload["accounts"][0]["player_name"] == "PlayerOne"
