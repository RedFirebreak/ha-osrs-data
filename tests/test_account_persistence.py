"""Tests for AccountState and AccountStore persistence (to_dict / load_dict)."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

# Mock homeassistant before imports
for mod_name in (
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.webhook",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.account_store import (  # noqa: E402
    AccountState,
    AccountStore,
)


class TestAccountStatePersistence:
    def test_roundtrip_empty_state(self):
        """An empty AccountState survives a serialization roundtrip."""
        state = AccountState("hash1", "PlayerOne")
        data = state.to_dict()

        restored = AccountState("hash1", "PlayerOne")
        restored.load_dict(data)

        assert restored.account_hash == "hash1"
        assert restored.player_name == "PlayerOne"
        assert restored.last_event_type is None
        assert restored.last_event_summary is None
        assert restored.last_event_data == {}
        assert restored.last_update is None
        assert restored.last_typed_events == {}
        assert restored.detail_sensors == {}

    def test_roundtrip_level_event(self):
        """A LEVEL event with skill detail sensors roundtrips correctly."""
        state = AccountState("hash1", "RedFuhrbreak")
        state.record_event("LEVEL", "Levelled Sailing to 70", {
            "levelledSkills": {"Sailing": 70},
            "allSkills": {"Attack": 99, "Sailing": 70},
            "combatLevel": 126,
            "combatLevelIncreased": False,
        })

        data = state.to_dict()
        restored = AccountState("hash1", "placeholder")
        restored.load_dict(data)

        assert restored.player_name == "RedFuhrbreak"
        assert restored.last_event_type == "LEVEL"
        assert restored.last_event_summary == "Levelled Sailing to 70"
        assert restored.last_update is not None
        assert "Sailing" in restored.detail_sensors
        assert restored.detail_sensors["Sailing"]["value"] == 70
        assert "Attack" in restored.detail_sensors
        assert restored.detail_sensors["Attack"]["value"] == 99
        assert "Combat Level" in restored.detail_sensors
        assert restored.detail_sensors["Combat Level"]["value"] == 126

    def test_roundtrip_typed_event(self):
        """A typed event (DEATH) roundtrips correctly."""
        state = AccountState("hash1", "Player")
        state.record_event("DEATH", "Died to Jad", {"valueLost": 5000, "isPvp": False})

        data = state.to_dict()
        restored = AccountState("hash1", "placeholder")
        restored.load_dict(data)

        assert restored.last_event_type == "DEATH"
        assert "DEATH" in restored.last_typed_events
        assert restored.last_typed_events["DEATH"]["summary"] == "Died to Jad"
        assert restored.last_typed_events["DEATH"]["data"]["valueLost"] == 5000

    def test_roundtrip_multiple_typed_events(self):
        """Multiple typed events all persist correctly."""
        state = AccountState("hash1", "Player")
        state.record_event("DEATH", "Died", {"valueLost": 100})
        state.record_event("LOOT", "Got loot", {"source": "Goblin"})
        state.record_event("QUEST", "Completed quest", {"questName": "Dragon Slayer I"})

        data = state.to_dict()
        restored = AccountState("hash1", "placeholder")
        restored.load_dict(data)

        assert restored.last_event_type == "QUEST"
        assert "DEATH" in restored.last_typed_events
        assert "LOOT" in restored.last_typed_events
        assert "QUEST" in restored.last_typed_events


class TestAccountStorePersistence:
    def test_roundtrip_empty_store(self):
        """An empty store roundtrips to an empty list."""
        store = AccountStore()
        data = store.to_dict()
        assert data == []

        store2 = AccountStore()
        store2.load_dict(data)
        assert len(store2.accounts) == 0

    def test_roundtrip_single_account(self):
        """A single account with events roundtrips correctly."""
        store = AccountStore()
        acct = store.get_or_create("hashAAA", "PlayerOne")
        acct.record_event("LEVEL", "Levelled Attack to 70", {
            "levelledSkills": {"Attack": 70},
        })

        data = store.to_dict()

        store2 = AccountStore()
        store2.load_dict(data)

        assert len(store2.accounts) == 1
        restored = store2.get_by_hash("hashAAA")
        assert restored is not None
        assert restored.player_name == "PlayerOne"
        assert restored.last_event_type == "LEVEL"
        assert "Attack" in restored.detail_sensors
        assert restored.detail_sensors["Attack"]["value"] == 70

    def test_roundtrip_multiple_accounts(self):
        """Multiple accounts roundtrip correctly with separate state."""
        store = AccountStore()
        a = store.get_or_create("hashA", "PlayerA")
        a.record_event("LEVEL", "Levelled Attack to 70", {"levelledSkills": {"Attack": 70}})
        b = store.get_or_create("hashB", "PlayerB")
        b.record_event("DEATH", "Died", {"valueLost": 500})

        data = store.to_dict()

        store2 = AccountStore()
        store2.load_dict(data)

        assert len(store2.accounts) == 2
        ra = store2.get_by_hash("hashA")
        rb = store2.get_by_hash("hashB")
        assert ra is not None
        assert rb is not None
        assert ra.last_event_type == "LEVEL"
        assert rb.last_event_type == "DEATH"

    def test_load_empty_list_is_noop(self):
        """Loading an empty list does not create any accounts."""
        store = AccountStore()
        store.load_dict([])
        assert len(store.accounts) == 0

    def test_sensor_value_survives_roundtrip(self):
        """The exact scenario from the bug: skill level persists after roundtrip."""
        store = AccountStore()
        acct = store.get_or_create("hashRedFuhrbreak", "RedFuhrbreak")
        acct.record_event("LEVEL", "Levelled Sailing to 70", {
            "levelledSkills": {"Sailing": 70},
        })

        # Simulate save
        data = store.to_dict()

        # Simulate restart: fresh store, restore from data
        store2 = AccountStore()
        store2.load_dict(data)

        restored = store2.get_by_hash("hashRedFuhrbreak")
        assert restored is not None
        assert restored.detail_sensors["Sailing"]["value"] == 70
        assert restored.last_event_summary == "Levelled Sailing to 70"
