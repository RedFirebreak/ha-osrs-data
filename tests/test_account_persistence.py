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
    "homeassistant.components.http",
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
        assert restored.account_type is None
        assert restored.world is None
        assert restored.skills == {}
        assert restored.inventory == []
        assert restored.equipment == {}
        assert restored.events == []
        assert restored.game_state == "UNKNOWN"
        assert restored.last_update is None
        assert restored.detail_sensors == {}

    def test_roundtrip_player_data(self):
        """Player data with skill sensors roundtrips correctly."""
        state = AccountState("hash1", "RedFuhrbreak")
        state.update_player_data({
            "accountType": "normal",
            "world": "302",
            "skills": {
                "Sailing": {"xp": 50000, "level": 70},
                "Attack": {"xp": 13000000, "level": 99},
            },
            "inventory": [{"name": "Shark", "quantity": 10}],
            "equipment": {"HEAD": {"name": "Helm"}},
            "events": [],
        })

        data = state.to_dict()
        restored = AccountState("hash1", "placeholder")
        restored.load_dict(data)

        assert restored.player_name == "RedFuhrbreak"
        assert restored.account_type == "normal"
        assert restored.world == "302"
        assert restored.last_update is not None
        assert "Sailing" in restored.detail_sensors
        assert restored.detail_sensors["Sailing"]["value"] == 70
        assert restored.detail_sensors["Sailing"]["attributes"]["xp"] == 50000
        assert "Attack" in restored.detail_sensors
        assert restored.detail_sensors["Attack"]["value"] == 99
        assert restored.detail_sensors["Attack"]["attributes"]["xp"] == 13000000
        assert len(restored.inventory) == 1
        assert restored.equipment["HEAD"]["name"] == "Helm"

    def test_roundtrip_skills_preserved(self):
        """Skills dict persists correctly."""
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })

        data = state.to_dict()
        restored = AccountState("hash1", "placeholder")
        restored.load_dict(data)

        assert restored.skills == {"Attack": {"xp": 1000, "level": 10}}

    def test_roundtrip_game_state(self):
        """Game state persists correctly through a roundtrip."""
        state = AccountState("hash1", "Player")
        state.update_player_data({"state": "LOGGED_IN"})

        data = state.to_dict()
        assert data["game_state"] == "LOGGED_IN"

        restored = AccountState("hash1", "placeholder")
        restored.load_dict(data)

        assert restored.game_state == "LOGGED_IN"


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
        """A single account with data roundtrips correctly."""
        store = AccountStore()
        acct = store.get_or_create(None, "PlayerOne")
        acct.update_player_data({
            "accountType": "normal",
            "skills": {"Attack": {"xp": 1000, "level": 70}},
        })

        data = store.to_dict()

        store2 = AccountStore()
        store2.load_dict(data)

        assert len(store2.accounts) == 1
        restored = store2.get_or_create(None, "PlayerOne")
        assert restored is not None
        assert restored.player_name == "PlayerOne"
        assert restored.account_type == "normal"
        assert "Attack" in restored.detail_sensors
        assert restored.detail_sensors["Attack"]["value"] == 70
        assert restored.detail_sensors["Attack"]["attributes"]["xp"] == 1000

    def test_roundtrip_multiple_accounts(self):
        """Multiple accounts roundtrip correctly with separate state."""
        store = AccountStore()
        a = store.get_or_create(None, "PlayerA")
        a.update_player_data({"skills": {"Attack": {"xp": 1000, "level": 70}}})
        b = store.get_or_create(None, "PlayerB")
        b.update_player_data({"skills": {"Defence": {"xp": 500, "level": 50}}})

        data = store.to_dict()

        store2 = AccountStore()
        store2.load_dict(data)

        assert len(store2.accounts) == 2

    def test_load_empty_list_is_noop(self):
        """Loading an empty list does not create any accounts."""
        store = AccountStore()
        store.load_dict([])
        assert len(store.accounts) == 0

    def test_sensor_value_survives_roundtrip(self):
        """Skill data persists after roundtrip."""
        store = AccountStore()
        acct = store.get_or_create(None, "RedFuhrbreak")
        acct.update_player_data({
            "skills": {"Sailing": {"xp": 50000, "level": 70}},
        })

        # Simulate save
        data = store.to_dict()

        # Simulate restart: fresh store, restore from data
        store2 = AccountStore()
        store2.load_dict(data)

        restored = store2.get_or_create(None, "RedFuhrbreak")
        assert restored is not None
        assert restored.detail_sensors["Sailing"]["value"] == 70
        assert restored.detail_sensors["Sailing"]["attributes"]["xp"] == 50000
