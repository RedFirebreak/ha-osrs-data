"""Integration tests: webhook → parser → account store → signal."""

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
    "homeassistant.components.sensor",
    "homeassistant.helpers",
    "homeassistant.helpers.webhook",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_webhook.account_store import AccountStore  # noqa: E402
from custom_components.osrs_webhook.const import (  # noqa: E402
    DATA_ACCOUNT_STORE,
    DOMAIN,
    SIGNAL_ACCOUNT_UPDATED,
)
from custom_components.osrs_webhook.webhook import _handle_webhook  # noqa: E402


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


class TestWebhookIntegration:
    """End-to-end tests: webhook handler updates account store."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock hass with account store wired up."""
        hass = MagicMock()
        hass.bus = MagicMock()
        hass.bus.async_fire = MagicMock()

        store = AccountStore()
        entry_id = "test_entry"
        hass.data = {
            DOMAIN: {
                entry_id: {
                    DATA_ACCOUNT_STORE: store,
                }
            }
        }
        return hass, store

    def _make_json_request(self, payload: dict[str, Any]):
        request = MagicMock()
        request.headers = {"Content-Type": "application/json"}
        request.json = AsyncMock(return_value=payload)
        return request

    @pytest.mark.asyncio
    async def test_level_updates_account_store(self, mock_hass):
        """LEVEL event increments level counter for correct account."""
        hass, store = mock_hass
        request = self._make_json_request(LEVEL_PAYLOAD)
        result = await _handle_webhook(hass, "wh-id", request)

        assert result == {"ok": True}
        acct = store.get_or_create("hashAAA", "PlayerOne")
        assert acct.levels_total == 1
        assert acct.last_event_type == "LEVEL"
        assert "Attack" in acct.last_event_summary

    @pytest.mark.asyncio
    async def test_multi_account_separate_state(self, mock_hass):
        """Two different accounts get separate counters."""
        hass, store = mock_hass

        await _handle_webhook(hass, "wh-id", self._make_json_request(LEVEL_PAYLOAD))
        await _handle_webhook(hass, "wh-id", self._make_json_request(DEATH_PAYLOAD))

        acct_a = store.get_or_create("hashAAA", "PlayerOne")
        acct_b = store.get_or_create("hashBBB", "PlayerTwo")

        assert acct_a.levels_total == 1
        assert acct_a.deaths_total == 0
        assert acct_b.levels_total == 0
        assert acct_b.deaths_total == 1

    @pytest.mark.asyncio
    async def test_same_account_multiple_events(self, mock_hass):
        """Same account receives multiple events, counters accumulate."""
        hass, store = mock_hass

        await _handle_webhook(hass, "wh-id", self._make_json_request(LEVEL_PAYLOAD))
        await _handle_webhook(hass, "wh-id", self._make_json_request(QUEST_PAYLOAD))

        acct = store.get_or_create("hashAAA", "PlayerOne")
        assert acct.levels_total == 1
        assert acct.quests_total == 1
        assert acct.last_event_type == "QUEST"

    @pytest.mark.asyncio
    async def test_dispatcher_signal_fired(self, mock_hass):
        """Verify dispatcher signal is sent for account updates."""
        hass, store = mock_hass
        request = self._make_json_request(LEVEL_PAYLOAD)

        # Patch dispatcher
        with patch(
            "custom_components.osrs_webhook.webhook.async_dispatcher_send"
        ) as mock_signal:
            await _handle_webhook(hass, "wh-id", request)
            mock_signal.assert_called_once_with(
                hass, SIGNAL_ACCOUNT_UPDATED, "hashAAA"
            )

    @pytest.mark.asyncio
    async def test_unsupported_type_no_store_update(self, mock_hass):
        """Unsupported event types don't update the store."""
        hass, store = mock_hass
        payload = {
            "type": "LOGIN",
            "playerName": "Player",
            "dinkAccountHash": "hashXYZ",
            "extra": {},
        }
        request = self._make_json_request(payload)
        result = await _handle_webhook(hass, "wh-id", request)

        assert result == {"ok": True}
        # The account should NOT be created since LOGIN is not a parsed type
        assert len(store.accounts) == 0

    @pytest.mark.asyncio
    async def test_no_embeds_dependency(self, mock_hass):
        """Parsing does not depend on embeds being present."""
        hass, store = mock_hass
        payload = dict(LEVEL_PAYLOAD)
        payload.pop("embeds", None)  # Remove embeds if present to test without them
        request = self._make_json_request(payload)

        result = await _handle_webhook(hass, "wh-id", request)
        assert result == {"ok": True}
        acct = store.get_or_create("hashAAA", "PlayerOne")
        assert acct.levels_total == 1
