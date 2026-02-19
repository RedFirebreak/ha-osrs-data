"""Tests for the AccountStore and AccountState."""

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


class TestAccountState:
    def test_initial_state(self):
        state = AccountState("hash1", "PlayerOne")
        assert state.account_type is None
        assert state.world is None
        assert state.skills == {}
        assert state.inventory == []
        assert state.equipment == {}
        assert state.events == []
        assert state.detail_sensors == {}

    def test_update_player_data(self):
        state = AccountState("hash1", "PlayerOne")
        state.update_player_data({
            "accountType": "normal",
            "world": "302",
            "skills": {"Attack": {"xp": 1000, "level": 10}},
            "inventory": [{"name": "Shark", "quantity": 5}],
            "equipment": {"HEAD": {"name": "Helm"}},
            "events": [],
        })
        assert state.account_type == "normal"
        assert state.world == "302"
        assert state.skills == {"Attack": {"xp": 1000, "level": 10}}
        assert len(state.inventory) == 1
        assert state.equipment["HEAD"]["name"] == "Helm"
        assert state.last_update is not None

    def test_update_creates_skill_sensors(self):
        state = AccountState("hash1", "PlayerOne")
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })
        assert "Attack XP" in state.detail_sensors
        assert "Attack Level" in state.detail_sensors
        assert state.detail_sensors["Attack XP"]["value"] == 1000
        assert state.detail_sensors["Attack Level"]["value"] == 10

    def test_update_player_name(self):
        state = AccountState("hash1", "OldName")
        state.update_player_data({}, player_name="NewName")
        assert state.player_name == "NewName"

    def test_skill_sensor_only_on_change(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })
        first_update = state.detail_sensors["Attack XP"]["last_update"]

        # Same values — sensor should not be refreshed
        import time
        time.sleep(0.01)
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })
        assert state.detail_sensors["Attack XP"]["last_update"] == first_update

    def test_skill_sensor_refreshed_on_change(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })
        first_update = state.detail_sensors["Attack XP"]["last_update"]

        import time
        time.sleep(0.01)
        state.update_player_data({
            "skills": {"Attack": {"xp": 2000, "level": 10}},
        })
        assert state.detail_sensors["Attack XP"]["last_update"] != first_update
        assert state.detail_sensors["Attack XP"]["value"] == 2000


class TestAccountStore:
    def test_create_new_by_hash(self):
        store = AccountStore()
        acct = store.get_or_create("abc123", "PlayerOne")
        assert acct.account_hash == "abc123"
        assert acct.player_name == "PlayerOne"

    def test_lookup_by_hash(self):
        store = AccountStore()
        first = store.get_or_create("abc123", "PlayerOne")
        second = store.get_or_create("abc123", "PlayerOne")
        assert first is second

    def test_fallback_to_name(self):
        store = AccountStore()
        first = store.get_or_create(None, "PlayerOne")
        second = store.get_or_create(None, "PlayerOne")
        assert first is second

    def test_name_normalization(self):
        store = AccountStore()
        first = store.get_or_create(None, " Player  One ")
        second = store.get_or_create(None, "player one")
        assert first is second

    def test_upgrade_name_to_hash(self):
        store = AccountStore()
        first = store.get_or_create(None, "Player")
        second = store.get_or_create("hash123", "Player")
        assert first is second
        assert first.account_hash == "hash123"

    def test_multiple_accounts(self):
        store = AccountStore()
        a = store.get_or_create("hash1", "PlayerA")
        b = store.get_or_create("hash2", "PlayerB")
        assert a is not b
        assert len(store.accounts) == 2

    def test_accounts_list_deduplicates(self):
        store = AccountStore()
        store.get_or_create("hash1", "PlayerA")
        store.get_or_create("hash1", "PlayerA")
        assert len(store.accounts) == 1

    def test_separate_accounts_separate_state(self):
        """Multiple accounts posting to the same store keep separate state."""
        store = AccountStore()
        a = store.get_or_create(None, "PlayerA")
        b = store.get_or_create(None, "PlayerB")

        a.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 70}},
        })
        b.update_player_data({
            "skills": {"Defence": {"xp": 500, "level": 50}},
        })

        assert "Attack XP" in a.detail_sensors
        assert "Attack XP" not in b.detail_sensors
        assert "Defence XP" in b.detail_sensors
        assert "Defence XP" not in a.detail_sensors
