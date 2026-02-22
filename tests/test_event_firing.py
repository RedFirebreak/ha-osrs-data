"""Tests for per-event HA event firing, event deduplication, and event total sensors."""

from __future__ import annotations

import json
import os
import sys
import time
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

from custom_components.osrs_data.account_store import AccountStore, AccountState  # noqa: E402
from custom_components.osrs_data.api import OsrsEventsView  # noqa: E402
from custom_components.osrs_data.const import (  # noqa: E402
    DATA_ACCOUNT_STORE,
    DATA_DEDUPE_CACHE,
    DATA_EVENT_DEDUPE_CACHE,
    DATA_HISTORY_STORE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    DOMAIN,
)
from custom_components.osrs_data.dedupe import DedupeCache, EventDedupeCache  # noqa: E402
from custom_components.osrs_data.history import HistoryStore  # noqa: E402
from custom_components.osrs_data.pairing import PairingStore  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────


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
                DATA_EVENT_DEDUPE_CACHE: EventDedupeCache(),
                DATA_PAIRING_STORE: pairing_store,
                DATA_STORE: mock_storage,
            }
        }
    }

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


# ── Sample payloads ──────────────────────────────────────────────────

_BASE_PLAYER: dict[str, Any] = {
    "name": "TestPlayer",
    "accountType": "normal",
    "world": "302",
    "stats": {"skills": {}},
    "inventory": {"items": []},
    "equipment": {"items": []},
}

PAYLOAD_WITH_DEATH: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [
        {
            "type": "death",
            "data": {
                "valueLost": 88,
                "danger": "DANGEROUS",
                "killerName": "Guard",
                "killerNpcId": 11917,
                "keptItems": [
                    {"name": "Amulet of fury", "id": 6585, "gePrice": 2391076, "haPrice": 121200, "quantity": 1},
                ],
                "lostItems": [
                    {"name": "Bucket", "id": 1925, "gePrice": 5, "haPrice": 1, "quantity": 10},
                    {"name": "Coins", "id": 995, "gePrice": 1, "haPrice": 0, "quantity": 30},
                ],
                "location": {"x": 3175, "y": 3433, "plane": 0},
            },
        },
    ],
}

PAYLOAD_WITH_LOOT: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [
        {
            "type": "loot",
            "data": {
                "items": [
                    {"name": "Bones", "id": 526, "gePrice": 34, "haPrice": 0, "quantity": 1},
                    {"name": "Coins", "id": 995, "gePrice": 1, "haPrice": 0, "quantity": 1},
                ],
                "highestValueItem": {"name": "Bones", "id": 526, "gePrice": 34, "haPrice": 0, "quantity": 1},
                "totalValue": 35,
                "source": {"text": "Guard", "link": "https://oldschool.runescape.wiki/w/Special:Search?search=Guard"},
                "type": "NPC",
                "npcId": 11916,
                "criteria": [],
            },
        },
    ],
}

PAYLOAD_WITH_PKLOOT: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [
        {
            "type": "pkLoot",
            "data": {
                "items": [
                    {"name": "Bones", "id": 526, "gePrice": 34, "haPrice": 0, "quantity": 1},
                ],
                "highestValueItem": {"name": "Bones", "id": 526, "gePrice": 34, "haPrice": 0, "quantity": 1},
                "totalValue": 34,
                "source": {"text": "Player", "link": ""},
                "type": "PLAYER",
                "criteria": [],
            },
        },
    ],
}

PAYLOAD_WITH_CLIENTSHUTDOWN: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [
        {"type": "clientShutdown", "data": "Logout"},
    ],
}

PAYLOAD_WITH_LEVELUP: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [
        {
            "type": "levelUp",
            "data": [
                {"skill": "sailing", "level": 75},
            ],
        },
    ],
}

PAYLOAD_WITH_MULTI_LEVELUP: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [
        {
            "type": "levelUp",
            "data": [
                {"skill": "attack", "level": 60},
                {"skill": "strength", "level": 55},
            ],
        },
    ],
}

PAYLOAD_WITH_MULTIPLE_EVENTS: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [
        {"type": "death", "data": {"killerName": "Jad", "valueLost": 0}},
        {"type": "loot", "data": {"items": [{"id": 995, "name": "Coins"}], "totalValue": 1}},
    ],
}

PAYLOAD_NO_EVENTS: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [],
}

PAYLOAD_WITH_EVENT_ID: dict[str, Any] = {
    "player": _BASE_PLAYER,
    "events": [
        {"type": "death", "event_id": "unique-death-123", "data": {"killerName": "Jad"}},
    ],
}


# ── Per-event HA event firing tests ──────────────────────────────────


class TestPerEventFiring:
    """Tests that individual HA events are fired for each event in the payload."""

    @pytest.mark.asyncio
    async def test_single_event_fires_per_event_ha_event(self):
        """A payload with one event fires the base event + one per-event."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_WITH_DEATH, token)
        await view.post(request)

        # 1 base event + 1 per-event = 2 calls
        assert hass.bus.async_fire.call_count == 2

        # Check the per-event call
        calls = hass.bus.async_fire.call_args_list
        per_event_call = calls[1]
        event_name, event_data = per_event_call[0]
        assert event_name == "osrs_data_event"
        assert event_data["account_name"] == "TestPlayer"
        assert event_data["event_type"] == "DEATH"
        assert event_data["event_data"]["killerName"] == "Guard"
        assert "received_at" in event_data

    @pytest.mark.asyncio
    async def test_multiple_events_fire_multiple_ha_events(self):
        """A payload with two events fires 1 base + 2 per-event = 3."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_WITH_MULTIPLE_EVENTS, token)
        await view.post(request)

        # 1 base + 2 per-event = 3
        assert hass.bus.async_fire.call_count == 3

        calls = hass.bus.async_fire.call_args_list
        # Call 1: base normalized event
        assert calls[0][0][1].get("player_name") == "TestPlayer"
        # Call 2: DEATH per-event
        assert calls[1][0][1]["event_type"] == "DEATH"
        # Call 3: LOOT per-event
        assert calls[2][0][1]["event_type"] == "LOOT"

    @pytest.mark.asyncio
    async def test_no_events_only_fires_base(self):
        """A payload with no events only fires the base event."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_NO_EVENTS, token)
        await view.post(request)

        hass.bus.async_fire.assert_called_once()

    @pytest.mark.asyncio
    async def test_per_event_type_is_uppercased(self):
        """Event type field in per-event HA event is uppercased."""
        hass, store, token, _ = _setup_hass_and_token()
        payload = {
            "player": {
                "name": "TestPlayer",
                "accountType": "normal",
                "world": "302",
                "stats": {"skills": {}},
                "inventory": {"items": []},
                "equipment": {"items": []},
            },
            "events": [
                {"type": "death", "data": {}},
            ],
        }
        view = OsrsEventsView()
        request = _make_json_request(hass, payload, token)
        await view.post(request)

        calls = hass.bus.async_fire.call_args_list
        per_event = calls[1][0][1]
        assert per_event["event_type"] == "DEATH"

    @pytest.mark.asyncio
    async def test_per_event_missing_data_uses_empty_dict(self):
        """If event has no 'data' key, event_data defaults to empty dict."""
        hass, store, token, _ = _setup_hass_and_token()
        payload = {
            "player": {
                "name": "TestPlayer",
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
        view = OsrsEventsView()
        request = _make_json_request(hass, payload, token)
        await view.post(request)

        calls = hass.bus.async_fire.call_args_list
        per_event = calls[1][0][1]
        assert per_event["event_data"] == {}

    @pytest.mark.asyncio
    async def test_death_event_parsed_correctly(self):
        """Realistic death event fires with correct type and full data."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_WITH_DEATH, token)
        await view.post(request)

        calls = hass.bus.async_fire.call_args_list
        per_event = calls[1][0][1]
        assert per_event["event_type"] == "DEATH"
        assert per_event["event_data"]["killerName"] == "Guard"
        assert per_event["event_data"]["danger"] == "DANGEROUS"
        assert per_event["event_data"]["valueLost"] == 88
        assert len(per_event["event_data"]["keptItems"]) == 1
        assert len(per_event["event_data"]["lostItems"]) == 2
        assert per_event["event_data"]["location"] == {"x": 3175, "y": 3433, "plane": 0}

    @pytest.mark.asyncio
    async def test_loot_event_parsed_correctly(self):
        """Realistic loot event fires with correct type and full data."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_WITH_LOOT, token)
        await view.post(request)

        calls = hass.bus.async_fire.call_args_list
        per_event = calls[1][0][1]
        assert per_event["event_type"] == "LOOT"
        assert per_event["event_data"]["totalValue"] == 35
        assert per_event["event_data"]["source"]["text"] == "Guard"
        assert per_event["event_data"]["type"] == "NPC"
        assert per_event["event_data"]["npcId"] == 11916
        assert len(per_event["event_data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_pkloot_event_parsed_correctly(self):
        """Realistic pkLoot event fires with correct type and full data."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_WITH_PKLOOT, token)
        await view.post(request)

        calls = hass.bus.async_fire.call_args_list
        per_event = calls[1][0][1]
        assert per_event["event_type"] == "PKLOOT"
        assert per_event["event_data"]["totalValue"] == 34
        assert per_event["event_data"]["type"] == "PLAYER"
        assert len(per_event["event_data"]["items"]) == 1

    @pytest.mark.asyncio
    async def test_clientshutdown_event_parsed_correctly(self):
        """Realistic clientShutdown event fires with correct type and string data."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_WITH_CLIENTSHUTDOWN, token)
        await view.post(request)

        calls = hass.bus.async_fire.call_args_list
        per_event = calls[1][0][1]
        assert per_event["event_type"] == "CLIENTSHUTDOWN"
        assert per_event["event_data"] == "Logout"

    @pytest.mark.asyncio
    async def test_clientshutdown_marks_account_offline(self):
        """clientShutdown event marks the account as offline via account_store."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        # First: normal heartbeat
        await view.post(_make_json_request(hass, PAYLOAD_NO_EVENTS, token))
        acct = store.get_or_create(None, "TestPlayer")
        assert acct.is_online is True

        # Second: clientShutdown
        await view.post(_make_json_request(hass, PAYLOAD_WITH_CLIENTSHUTDOWN, token))
        assert acct.is_online is False
        assert acct.offline_reason == "Logout"

    @pytest.mark.asyncio
    async def test_levelup_event_parsed_correctly(self):
        """Realistic levelUp event fires with correct type and list data."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_WITH_LEVELUP, token)
        await view.post(request)

        calls = hass.bus.async_fire.call_args_list
        per_event = calls[1][0][1]
        assert per_event["event_type"] == "LEVELUP"
        assert isinstance(per_event["event_data"], list)
        assert len(per_event["event_data"]) == 1
        assert per_event["event_data"][0]["skill"] == "sailing"
        assert per_event["event_data"][0]["level"] == 75

    @pytest.mark.asyncio
    async def test_levelup_multiple_skills_parsed_correctly(self):
        """levelUp event with multiple skills in data list."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()
        request = _make_json_request(hass, PAYLOAD_WITH_MULTI_LEVELUP, token)
        await view.post(request)

        calls = hass.bus.async_fire.call_args_list
        per_event = calls[1][0][1]
        assert per_event["event_type"] == "LEVELUP"
        assert isinstance(per_event["event_data"], list)
        assert len(per_event["event_data"]) == 2
        assert per_event["event_data"][0]["skill"] == "attack"
        assert per_event["event_data"][1]["skill"] == "strength"


# ── Event deduplication tests ────────────────────────────────────────


class TestEventDedupeCache:
    """Tests for the EventDedupeCache class."""

    def test_first_event_not_duplicate(self):
        cache = EventDedupeCache(ttl=30)
        event = {"type": "DEATH", "data": {"killer": "Jad"}}
        assert cache.is_duplicate("player1", event) is False

    def test_same_event_is_duplicate(self):
        cache = EventDedupeCache(ttl=30)
        event = {"type": "DEATH", "data": {"killer": "Jad"}}
        cache.is_duplicate("player1", event)
        assert cache.is_duplicate("player1", event) is True

    def test_different_event_type_not_duplicate(self):
        cache = EventDedupeCache(ttl=30)
        event_a = {"type": "DEATH", "data": {}}
        event_b = {"type": "LOOT", "data": {}}
        cache.is_duplicate("player1", event_a)
        assert cache.is_duplicate("player1", event_b) is False

    def test_different_account_not_duplicate(self):
        cache = EventDedupeCache(ttl=30)
        event = {"type": "DEATH", "data": {"killer": "Jad"}}
        cache.is_duplicate("player1", event)
        assert cache.is_duplicate("player2", event) is False

    def test_event_id_used_for_dedup(self):
        cache = EventDedupeCache(ttl=30)
        event = {"type": "DEATH", "event_id": "unique-123", "data": {"killer": "Jad"}}
        cache.is_duplicate("player1", event)
        # Same event_id but different data should still be duplicate
        event_modified = {"type": "DEATH", "event_id": "unique-123", "data": {"killer": "Zuk"}}
        assert cache.is_duplicate("player1", event_modified) is True

    def test_different_event_id_not_duplicate(self):
        cache = EventDedupeCache(ttl=30)
        event_a = {"type": "DEATH", "event_id": "id-1", "data": {}}
        event_b = {"type": "DEATH", "event_id": "id-2", "data": {}}
        cache.is_duplicate("player1", event_a)
        assert cache.is_duplicate("player1", event_b) is False

    def test_ttl_expiry_allows_resubmission(self):
        cache = EventDedupeCache(ttl=1)
        event = {"type": "DEATH", "data": {}}
        cache.is_duplicate("player1", event)

        # Simulate time passing
        for key in cache._seen:
            cache._seen[key] = time.monotonic() - 2
        assert cache.is_duplicate("player1", event) is False


class TestPerEventDeduplication:
    """Integration tests for per-event dedup through the API."""

    @pytest.mark.asyncio
    async def test_duplicate_event_not_fired_twice(self):
        """Sending the same event twice only fires once."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        # First request
        await view.post(_make_json_request(hass, PAYLOAD_WITH_DEATH, token))
        # Second request (same events) — note: base payload dedupe will catch this
        # so we need a slightly different base payload
        payload2 = {
            "player": {**_BASE_PLAYER, "world": "303"},
            "events": PAYLOAD_WITH_DEATH["events"],
        }
        await view.post(_make_json_request(hass, payload2, token))

        # First request: 1 base + 1 per-event = 2
        # Second request: 1 base + 0 per-event (deduped) = 1
        # Total = 3
        assert hass.bus.async_fire.call_count == 3

    @pytest.mark.asyncio
    async def test_event_with_id_deduped_across_requests(self):
        """Events with event_id are deduped even across different base payloads."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PAYLOAD_WITH_EVENT_ID, token))

        payload2 = {
            "player": {**_BASE_PLAYER, "world": "303"},
            "events": [
                {"type": "death", "event_id": "unique-death-123", "data": {"killerName": "Jad"}},
            ],
        }
        await view.post(_make_json_request(hass, payload2, token))

        # First: 1 base + 1 per-event = 2
        # Second: 1 base + 0 (deduped by event_id) = 1
        assert hass.bus.async_fire.call_count == 3


# ── Event total sensor tests ────────────────────────────────────────


class TestAccountStateEventTotals:
    """Tests for event_totals on AccountState."""

    def test_record_event_increments_count(self):
        state = AccountState("hash1", "Player")
        state.record_event("DEATH")
        assert state.event_totals["DEATH"]["count"] == 1
        state.record_event("DEATH")
        assert state.event_totals["DEATH"]["count"] == 2

    def test_record_event_sets_last_fired(self):
        state = AccountState("hash1", "Player")
        state.record_event("DEATH")
        assert "last_fired" in state.event_totals["DEATH"]
        assert state.event_totals["DEATH"]["last_fired"] is not None

    def test_different_event_types_tracked_separately(self):
        state = AccountState("hash1", "Player")
        state.record_event("DEATH")
        state.record_event("LOOT")
        state.record_event("LOOT")
        assert state.event_totals["DEATH"]["count"] == 1
        assert state.event_totals["LOOT"]["count"] == 2

    def test_event_totals_persisted(self):
        state = AccountState("hash1", "Player")
        state.record_event("DEATH")
        state.record_event("DEATH")
        data = state.to_dict()
        assert data["event_totals"]["DEATH"]["count"] == 2

    def test_event_totals_restored(self):
        state = AccountState("hash1", "Player")
        state.load_dict({
            "event_totals": {
                "DEATH": {"count": 5, "last_fired": "2025-01-01T00:00:00Z"},
            },
        })
        assert state.event_totals["DEATH"]["count"] == 5


class TestEventTotalsThroughAPI:
    """Integration tests: event totals updated via the API."""

    @pytest.mark.asyncio
    async def test_event_total_incremented_via_api(self):
        """Sending events through the API increments event totals."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PAYLOAD_WITH_DEATH, token))

        acct = store.get_or_create(None, "TestPlayer")
        assert acct.event_totals["DEATH"]["count"] == 1
        assert "last_fired" in acct.event_totals["DEATH"]

    @pytest.mark.asyncio
    async def test_multiple_events_increment_totals(self):
        """Multiple events in one payload each increment their type counter."""
        hass, store, token, _ = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PAYLOAD_WITH_MULTIPLE_EVENTS, token))

        acct = store.get_or_create(None, "TestPlayer")
        assert acct.event_totals["DEATH"]["count"] == 1
        assert acct.event_totals["LOOT"]["count"] == 1

    @pytest.mark.asyncio
    async def test_event_totals_in_saved_data(self):
        """Event totals are included in the persisted save data."""
        hass, store, token, mock_storage = _setup_hass_and_token()
        view = OsrsEventsView()

        await view.post(_make_json_request(hass, PAYLOAD_WITH_DEATH, token))

        save_callback = mock_storage.async_delay_save.call_args[0][0]
        saved = save_callback()
        assert saved["accounts"][0]["event_totals"]["DEATH"]["count"] == 1


# ── OsrsEventTotalSensor tests ──────────────────────────────────────


# Provide a minimal real SensorEntity so the class can be instantiated.
_sensor_mod = MagicMock()


class _SensorEntity:
    """Minimal stand-in for homeassistant.components.sensor.SensorEntity."""

    _attr_has_entity_name: bool = False
    _attr_name: str | None = None
    _attr_unique_id: str | None = None
    _attr_native_value = None

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def unique_id(self):
        return self._attr_unique_id


_sensor_mod.SensorEntity = _SensorEntity
sys.modules["homeassistant.components.sensor"] = _sensor_mod

# Force re-import of sensor module
sys.modules.pop("custom_components.osrs_data.sensor", None)

from custom_components.osrs_data.sensor import OsrsEventTotalSensor  # noqa: E402


def _make_entry():
    entry = MagicMock()
    entry.entry_id = "entry_1"
    entry.data = {}
    return entry


class TestOsrsEventTotalSensor:
    """Tests for the OsrsEventTotalSensor entity."""

    def test_default_value_is_zero(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsEventTotalSensor(entry, state, "hash1", "DEATH")
        assert sensor.native_value == 0

    def test_value_reflects_count(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.record_event("DEATH")
        state.record_event("DEATH")
        sensor = OsrsEventTotalSensor(entry, state, "hash1", "DEATH")
        assert sensor.native_value == 2

    def test_attributes_contain_last_fired(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.record_event("DEATH")
        sensor = OsrsEventTotalSensor(entry, state, "hash1", "DEATH")
        attrs = sensor.extra_state_attributes
        assert "last_fired" in attrs

    def test_attributes_empty_when_no_events(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsEventTotalSensor(entry, state, "hash1", "DEATH")
        attrs = sensor.extra_state_attributes
        assert attrs == {}

    def test_unique_id(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsEventTotalSensor(entry, state, "hash1", "DEATH")
        assert sensor.unique_id == "hash1_event_death_total"

    def test_name(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsEventTotalSensor(entry, state, "hash1", "DEATH")
        assert sensor._attr_name == "DEATH Total"
