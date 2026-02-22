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

PAYLOAD_WITH_DEATH: dict[str, Any] = {
    "player": {
        "name": "TestPlayer",
        "accountType": "normal",
        "world": "302",
        "stats": {"skills": {}},
        "inventory": {"items": []},
        "equipment": {"items": []},
    },
    "events": [
        {"type": "DEATH", "data": {"killer": "Jad"}},
    ],
}

PAYLOAD_WITH_LOOT: dict[str, Any] = {
    "player": {
        "name": "TestPlayer",
        "accountType": "normal",
        "world": "302",
        "stats": {"skills": {}},
        "inventory": {"items": []},
        "equipment": {"items": []},
    },
    "events": [
        {"type": "LOOT", "data": {"items": [{"id": 11286, "name": "Dragonfire shield"}]}},
    ],
}

PAYLOAD_WITH_MULTIPLE_EVENTS: dict[str, Any] = {
    "player": {
        "name": "TestPlayer",
        "accountType": "normal",
        "world": "302",
        "stats": {"skills": {}},
        "inventory": {"items": []},
        "equipment": {"items": []},
    },
    "events": [
        {"type": "DEATH", "data": {"killer": "Jad"}},
        {"type": "LOOT", "data": {"items": [{"id": 995, "name": "Coins"}]}},
    ],
}

PAYLOAD_NO_EVENTS: dict[str, Any] = {
    "player": {
        "name": "TestPlayer",
        "accountType": "normal",
        "world": "302",
        "stats": {"skills": {}},
        "inventory": {"items": []},
        "equipment": {"items": []},
        "events": [],
    },
}

PAYLOAD_WITH_EVENT_ID: dict[str, Any] = {
    "player": {
        "name": "TestPlayer",
        "accountType": "normal",
        "world": "302",
        "stats": {"skills": {}},
        "inventory": {"items": []},
        "equipment": {"items": []},
    },
    "events": [
        {"type": "DEATH", "event_id": "unique-death-123", "data": {"killer": "Jad"}},
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
        assert event_data["event_data"] == {"killer": "Jad"}
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
            "player": {
                "name": "TestPlayer",
                "accountType": "normal",
                "world": "303",  # different world to bypass base dedupe
                "stats": {"skills": {}},
                "inventory": {"items": []},
                "equipment": {"items": []},
            },
            "events": [
                {"type": "DEATH", "data": {"killer": "Jad"}},
            ],
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
            "player": {
                "name": "TestPlayer",
                "accountType": "normal",
                "world": "303",
                "stats": {"skills": {}},
                "inventory": {"items": []},
                "equipment": {"items": []},
            },
            "events": [
                {"type": "DEATH", "event_id": "unique-death-123", "data": {"killer": "Jad"}},
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
