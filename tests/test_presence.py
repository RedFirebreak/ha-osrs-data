"""Tests for the account presence / online sensor feature."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
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
    "homeassistant.components.binary_sensor",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

# Provide a minimal BinarySensorEntity stand-in
_bs_mod = MagicMock()


class _BinarySensorEntity:
    """Minimal stand-in for homeassistant.components.binary_sensor.BinarySensorEntity."""

    _attr_has_entity_name: bool = False
    _attr_name: str | None = None
    _attr_unique_id: str | None = None

    @property
    def unique_id(self):
        return self._attr_unique_id


_bs_mod.BinarySensorEntity = _BinarySensorEntity
sys.modules["homeassistant.components.binary_sensor"] = _bs_mod

# Provide a minimal SensorEntity so sensor.py can import
_sensor_mod = MagicMock()


class _SensorEntity:
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

# Force re-import so our stand-ins are used
sys.modules.pop("custom_components.osrs_data.sensor", None)
sys.modules.pop("custom_components.osrs_data.binary_sensor", None)

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.account_store import AccountState, AccountStore  # noqa: E402
from custom_components.osrs_data.binary_sensor import OsrsOnlineBinarySensor  # noqa: E402


def _make_entry():
    entry = MagicMock()
    entry.entry_id = "entry_1"
    entry.data = {}
    return entry


# ── AccountState presence tracking tests ─────────────────────────────


class TestAccountStatePresence:
    """Tests for presence fields on AccountState."""

    def test_initial_state_is_offline(self):
        state = AccountState("hash1", "Player")
        assert state.is_online is False
        assert state.last_seen is None
        assert state.offline_reason is None

    def test_update_sets_online(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        assert state.is_online is True
        assert state.last_seen is not None
        assert state.offline_reason == "online"

    def test_update_refreshes_last_seen(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        first_seen = state.last_seen

        import time
        time.sleep(0.01)
        state.update_player_data({"accountType": "normal"})
        assert state.last_seen > first_seen

    def test_logout_event_sets_offline(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        assert state.is_online is True

        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "LOGOUT"}],
        })
        assert state.is_online is False
        assert state.offline_reason == "logout"

    def test_login_event_sets_online(self):
        state = AccountState("hash1", "Player")
        # Simulate offline state
        state.is_online = False
        state.offline_reason = "timeout"

        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "LOGIN"}],
        })
        assert state.is_online is True
        assert state.offline_reason == "online"

    def test_logout_event_case_insensitive(self):
        """LOGOUT event type comparison is case-insensitive."""
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})

        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "logout"}],
        })
        assert state.is_online is False
        assert state.offline_reason == "logout"

    def test_non_dict_events_are_skipped(self):
        """Non-dict events in the list should not crash."""
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "accountType": "normal",
            "events": ["not_a_dict", 42, None],
        })
        assert state.is_online is True

    def test_client_shutdown_sets_offline(self):
        """ClientShutdown event immediately sets the sensor to offline."""
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        assert state.is_online is True

        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "ClientShutdown", "data": "Shutdown"}],
        })
        assert state.is_online is False
        assert state.offline_reason == "Shutdown"

    def test_client_shutdown_custom_data(self):
        """ClientShutdown data field is stored as the offline reason."""
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})

        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "ClientShutdown", "data": "Crash"}],
        })
        assert state.is_online is False
        assert state.offline_reason == "Crash"

    def test_client_shutdown_without_data(self):
        """ClientShutdown without data field defaults to 'shutdown'."""
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})

        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "ClientShutdown"}],
        })
        assert state.is_online is False
        assert state.offline_reason == "shutdown"

    def test_client_shutdown_case_insensitive(self):
        """ClientShutdown event type is case-insensitive."""
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})

        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "clientshutdown", "data": "Shutdown"}],
        })
        assert state.is_online is False
        assert state.offline_reason == "Shutdown"

    def test_online_after_client_shutdown(self):
        """New data after ClientShutdown sets the account back online."""
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "ClientShutdown", "data": "Shutdown"}],
        })
        assert state.is_online is False
        assert state.offline_reason == "Shutdown"

        # New data arrives — no shutdown event
        state.update_player_data({"accountType": "normal"})
        assert state.is_online is True
        assert state.offline_reason == "online"


class TestAccountStatePresencePersistence:
    """Tests for presence field serialization."""

    def test_roundtrip_online_state(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        assert state.is_online is True

        data = state.to_dict()
        assert data["is_online"] is True
        assert data["last_seen"] is not None
        assert data["offline_reason"] == "online"

        restored = AccountState("hash1", "Player")
        restored.load_dict(data)
        assert restored.is_online is True
        assert restored.last_seen is not None
        assert restored.offline_reason == "online"

    def test_roundtrip_offline_state(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "LOGOUT"}],
        })

        data = state.to_dict()
        assert data["is_online"] is False
        assert data["offline_reason"] == "logout"

        restored = AccountState("hash1", "Player")
        restored.load_dict(data)
        assert restored.is_online is False
        assert restored.offline_reason == "logout"
        assert restored.last_seen is not None

    def test_load_legacy_data_without_presence(self):
        """Loading old persisted data (no presence fields) defaults gracefully."""
        state = AccountState("hash1", "Player")
        state.load_dict({
            "player_name": "Player",
            "account_type": "normal",
        })
        assert state.is_online is False
        assert state.last_seen is None
        assert state.offline_reason is None


# ── Timeout detection tests ──────────────────────────────────────────


class TestPresenceTimeout:
    """Tests for the timeout-based offline detection logic."""

    def test_account_goes_offline_after_timeout(self):
        """Simulate the presence check marking an account offline."""
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        assert state.is_online is True

        # Simulate last_seen being 26 minutes ago
        state.last_seen = datetime.now(timezone.utc) - timedelta(minutes=26)

        # Run the presence check logic (same as in __init__.py)
        from custom_components.osrs_data.const import PRESENCE_TIMEOUT
        now = datetime.now(timezone.utc)
        elapsed = (now - state.last_seen).total_seconds()
        if elapsed > PRESENCE_TIMEOUT:
            state.is_online = False
            state.offline_reason = "timeout"

        assert state.is_online is False
        assert state.offline_reason == "timeout"

    def test_account_stays_online_within_timeout(self):
        """Account should remain online if within timeout period."""
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        assert state.is_online is True

        # last_seen is recent (5 minutes ago)
        state.last_seen = datetime.now(timezone.utc) - timedelta(minutes=5)

        from custom_components.osrs_data.const import PRESENCE_TIMEOUT
        now = datetime.now(timezone.utc)
        elapsed = (now - state.last_seen).total_seconds()
        if elapsed > PRESENCE_TIMEOUT:
            state.is_online = False
            state.offline_reason = "timeout"

        assert state.is_online is True
        assert state.offline_reason == "online"

    def test_already_offline_account_not_rechecked(self):
        """An account already offline should not be re-flagged."""
        state = AccountState("hash1", "Player")
        state.is_online = False
        state.offline_reason = "logout"
        state.last_seen = datetime.now(timezone.utc) - timedelta(hours=1)

        # Only check accounts that are online
        from custom_components.osrs_data.const import PRESENCE_TIMEOUT
        now = datetime.now(timezone.utc)
        if state.is_online and state.last_seen is not None:
            elapsed = (now - state.last_seen).total_seconds()
            if elapsed > PRESENCE_TIMEOUT:
                state.is_online = False
                state.offline_reason = "timeout"

        # Should stay as "logout" not "timeout"
        assert state.offline_reason == "logout"


# ── Binary sensor tests ──────────────────────────────────────────────


class TestOsrsOnlineBinarySensor:
    """Tests for the OsrsOnlineBinarySensor entity."""

    def test_is_off_when_offline(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsOnlineBinarySensor(entry, state)
        assert sensor.is_on is False

    def test_is_on_when_online(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        sensor = OsrsOnlineBinarySensor(entry, state)
        assert sensor.is_on is True

    def test_unique_id(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsOnlineBinarySensor(entry, state)
        assert sensor.unique_id == "hash1_online"

    def test_attributes_contain_last_seen(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        sensor = OsrsOnlineBinarySensor(entry, state)
        attrs = sensor.extra_state_attributes
        assert "last_seen" in attrs

    def test_attributes_contain_offline_reason(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "LOGOUT"}],
        })
        sensor = OsrsOnlineBinarySensor(entry, state)
        attrs = sensor.extra_state_attributes
        assert attrs["status"] == "logout"

    def test_attributes_empty_when_no_data(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsOnlineBinarySensor(entry, state)
        attrs = sensor.extra_state_attributes
        assert "last_seen" not in attrs
        assert "status" not in attrs

    def test_status_is_online_when_online(self):
        """Status attribute shows 'online' when the account is online."""
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({"accountType": "normal"})
        sensor = OsrsOnlineBinarySensor(entry, state)
        attrs = sensor.extra_state_attributes
        assert attrs["status"] == "online"

    def test_status_shows_shutdown_data(self):
        """Status attribute shows the ClientShutdown data value when offline."""
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "ClientShutdown", "data": "Shutdown"}],
        })
        sensor = OsrsOnlineBinarySensor(entry, state)
        attrs = sensor.extra_state_attributes
        assert attrs["status"] == "Shutdown"
        assert sensor.is_on is False

    def test_status_returns_to_online(self):
        """Status attribute returns to 'online' after recovery from ClientShutdown."""
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "ClientShutdown", "data": "Shutdown"}],
        })
        sensor = OsrsOnlineBinarySensor(entry, state)
        assert sensor.is_on is False
        assert sensor.extra_state_attributes["status"] == "Shutdown"

        # New data arrives
        state.update_player_data({"accountType": "normal"})
        assert sensor.is_on is True
        assert sensor.extra_state_attributes["status"] == "online"

    def test_reflects_state_changes(self):
        """Sensor reflects the underlying state changes."""
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsOnlineBinarySensor(entry, state)
        assert sensor.is_on is False

        state.update_player_data({"accountType": "normal"})
        assert sensor.is_on is True

        state.update_player_data({
            "accountType": "normal",
            "events": [{"type": "LOGOUT"}],
        })
        assert sensor.is_on is False


# ── Constants tests ──────────────────────────────────────────────────


class TestPresenceConstants:
    """Tests for presence-related constants."""

    def test_timeout_is_25_minutes(self):
        from custom_components.osrs_data.const import PRESENCE_TIMEOUT
        assert PRESENCE_TIMEOUT == 1500

    def test_check_interval_is_60_seconds(self):
        from custom_components.osrs_data.const import PRESENCE_CHECK_INTERVAL
        assert PRESENCE_CHECK_INTERVAL == 60
