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

from custom_components.osrs_webhook.account_store import (  # noqa: E402
    AccountState,
    AccountStore,
)


class TestAccountState:
    def test_initial_state(self):
        state = AccountState("hash1", "PlayerOne")
        assert state.last_event_type is None
        assert state.detail_sensors == {}

    def test_record_level_event(self):
        state = AccountState("hash1", "PlayerOne")
        state.record_event("LEVEL", "Levelled Attack to 70", {"levelledSkills": {"Attack": 70}})
        assert state.last_event_type == "LEVEL"
        assert state.last_event_summary == "Levelled Attack to 70"
        assert state.last_update is not None

    def test_record_multiple_events(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "a", {})
        state.record_event("LEVEL", "b", {})
        state.record_event("DEATH", "died", {"valueLost": 100})
        assert state.last_event_type == "DEATH"

    def test_unsupported_type_still_tracked(self):
        state = AccountState("hash1", "Player")
        state.record_event("LOGIN", "logged in", {})
        assert state.last_event_type == "LOGIN"

    def test_record_updates_player_name(self):
        state = AccountState("hash1", "OldName")
        state.record_event("LEVEL", "test", {}, player_name="NewName")
        assert state.player_name == "NewName"


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
        a = store.get_or_create("hashA", "PlayerA")
        b = store.get_or_create("hashB", "PlayerB")

        a.record_event("LEVEL", "a levelled", {"levelledSkills": {"Attack": 70}})
        a.record_event("LEVEL", "a levelled again", {"levelledSkills": {"Attack": 71}})
        b.record_event("DEATH", "b died", {"valueLost": 500})

        assert a.last_event_type == "LEVEL"
        assert "Attack" in a.detail_sensors
        assert b.last_event_type == "DEATH"
        assert len(b.detail_sensors) == 0
