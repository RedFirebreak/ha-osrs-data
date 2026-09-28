"""Tests for persistent history buffers."""

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

from custom_components.osrs_data.history import (  # noqa: E402
    AccountHistory,
    HistoryBuffer,
    HistoryStore,
)


class TestHistoryBuffer:
    def test_append_and_retrieve(self):
        buf = HistoryBuffer(maxlen=5)
        buf.append({"a": 1})
        buf.append({"a": 2})
        assert len(buf) == 2
        assert buf.as_list() == [{"a": 1}, {"a": 2}]

    def test_ring_buffer_eviction(self):
        buf = HistoryBuffer(maxlen=3)
        for i in range(5):
            buf.append({"i": i})
        assert len(buf) == 3
        assert buf.as_list() == [{"i": 2}, {"i": 3}, {"i": 4}]


class TestAccountHistory:
    def test_record_and_get(self):
        hist = AccountHistory()
        hist.record("LOOT", "Got a drop", {"item": "Rune sword"})
        entries = hist.get("LOOT")
        assert len(entries) == 1
        assert entries[0]["summary"] == "Got a drop"
        assert entries[0]["event_type"] == "LOOT"
        assert "timestamp" in entries[0]

    def test_separate_event_types(self):
        hist = AccountHistory()
        hist.record("LOOT", "loot1", {})
        hist.record("DEATH", "death1", {})
        assert len(hist.get("LOOT")) == 1
        assert len(hist.get("DEATH")) == 1

    def test_default_limits(self):
        """LOOT should have limit of 100, DEATH should have 50."""
        hist = AccountHistory()
        for i in range(110):
            hist.record("LOOT", f"loot{i}", {})
        assert len(hist.get("LOOT")) == 100

        for i in range(60):
            hist.record("DEATH", f"death{i}", {})
        assert len(hist.get("DEATH")) == 50

    def test_all_entries_sorted(self):
        hist = AccountHistory()
        hist.record("LOOT", "loot1", {})
        hist.record("DEATH", "death1", {})
        hist.record("LOOT", "loot2", {})
        entries = hist.all_entries()
        assert len(entries) == 3
        # Should be sorted by timestamp
        timestamps = [e["timestamp"] for e in entries]
        assert timestamps == sorted(timestamps)

    def test_empty_get(self):
        hist = AccountHistory()
        assert hist.get("LOOT") == []

    def test_serialization_roundtrip(self):
        hist = AccountHistory()
        hist.record("LOOT", "loot1", {"item": "sword"})
        hist.record("DEATH", "death1", {"valueLost": 100})

        data = hist.to_dict()
        hist2 = AccountHistory()
        hist2.load_dict(data)

        assert len(hist2.get("LOOT")) == 1
        assert len(hist2.get("DEATH")) == 1
        assert hist2.get("LOOT")[0]["summary"] == "loot1"


class TestHistoryStore:
    def test_get_or_create(self):
        store = HistoryStore()
        hist = store.get_or_create("account1")
        assert hist is store.get_or_create("account1")

    def test_separate_accounts(self):
        store = HistoryStore()
        h1 = store.get_or_create("account1")
        h2 = store.get_or_create("account2")
        assert h1 is not h2

    def test_serialization_roundtrip(self):
        store = HistoryStore()
        h1 = store.get_or_create("account1")
        h1.record("LOOT", "loot1", {"item": "sword"})
        h1.record("DEATH", "death1", {"valueLost": 100})

        data = store.to_dict()
        store2 = HistoryStore()
        store2.load_dict(data)

        h1_restored = store2.get_or_create("account1")
        assert len(h1_restored.get("LOOT")) == 1
        assert len(h1_restored.get("DEATH")) == 1
        assert h1_restored.get("LOOT")[0]["summary"] == "loot1"


# ── History keyed by account key (storage 2.1 -> 2.2) ───────────────


import copy  # noqa: E402

from custom_components.osrs_data import _history_entries  # noqa: E402
from custom_components.osrs_data.account_store import AccountStore  # noqa: E402
from custom_components.osrs_data.storage import migrate_storage_data  # noqa: E402

HASH_A = "a" * 56
HASH_B = "b" * 56

STORED_2_1: dict = {
    "accounts": [
        # Legacy name-keyed account, renamed after it linked its hash
        {"account_hash": "zezima", "player_name": "Zezima Jr", "plugin_account_hash": HASH_A},
        {"account_hash": HASH_B, "player_name": "Bob", "plugin_account_hash": HASH_B},
        # Very old entry without a stored key
        {"player_name": "Legacy"},
    ],
    "history": {
        "Zezima Jr": {"DEATH": [{"timestamp": "2026-01-02", "summary": "z2"}]},
        "zezima jr": {"DEATH": [{"timestamp": "2026-01-01", "summary": "z1"}]},
        "Bob": {"LOOT": [{"timestamp": "2026-01-03", "summary": "b1"}]},
        "Legacy": {"DEATH": [{"timestamp": "2026-01-04", "summary": "l1"}]},
        # No account has this name any more; keep it as it was.
        "Gone": {"DEATH": [{"timestamp": "2026-01-05", "summary": "g1"}]},
    },
    "paired_devices": [{"device_id": "d1", "token_hash": "x"}],
}


class TestHistoryMigration:
    def test_history_rekeyed_to_account_keys(self):
        migrated = migrate_storage_data(2, 1, copy.deepcopy(STORED_2_1))
        assert set(migrated["history"]) == {"zezima", HASH_B, "legacy", "Gone"}
        deaths = migrated["history"]["zezima"]["DEATH"]
        assert [e["summary"] for e in deaths] == ["z1", "z2"]
        assert migrated["accounts"] == STORED_2_1["accounts"]
        assert migrated["paired_devices"] == STORED_2_1["paired_devices"]

    def test_version_1_data_is_migrated(self):
        migrated = migrate_storage_data(1, 1, copy.deepcopy(STORED_2_1))
        assert set(migrated["history"]) == {"zezima", HASH_B, "legacy", "Gone"}

    def test_migration_is_idempotent(self):
        once = migrate_storage_data(2, 1, copy.deepcopy(STORED_2_1))
        twice = migrate_storage_data(2, 1, copy.deepcopy(once))
        assert twice == once

    def test_newer_minor_version_left_alone(self):
        assert migrate_storage_data(2, 3, copy.deepcopy(STORED_2_1)) == STORED_2_1

    def test_migrated_history_reachable_from_accounts(self):
        migrated = migrate_storage_data(2, 1, copy.deepcopy(STORED_2_1))
        accounts = AccountStore()
        accounts.load_dict(migrated["accounts"])
        history = HistoryStore()
        history.load_dict(migrated["history"])
        acct = accounts.get_or_create(None, "?", plugin_hash=HASH_A)
        assert len(history.get_or_create(acct.account_hash).get("DEATH")) == 2


class TestHistoryService:
    """``osrs_data.get_history`` takes and returns display names."""

    def _stores(self):
        accounts = AccountStore()
        alice = accounts.get_or_create(None, "Alice", plugin_hash=HASH_A)
        bob = accounts.get_or_create(None, "Bob", plugin_hash=HASH_B)
        history = HistoryStore()
        history.get_or_create(alice.account_hash).record("DEATH", "a1", {}, timestamp="2026-01-01")
        history.get_or_create(bob.account_hash).record("LOOT", "b1", {}, timestamp="2026-01-02")
        history.get_or_create("Gone").record("DEATH", "g1", {}, timestamp="2026-01-03")
        return accounts, history

    def test_filter_by_current_name(self):
        accounts, history = self._stores()
        entries = _history_entries(accounts, history, "alice", None, 20)
        assert [(e["summary"], e["account_name"]) for e in entries] == [("a1", "Alice")]

    def test_all_accounts_newest_first(self):
        accounts, history = self._stores()
        entries = _history_entries(accounts, history, None, None, 20)
        assert [(e["summary"], e["account_name"]) for e in entries] == [
            ("b1", "Bob"), ("a1", "Alice"),
        ]

    def test_event_type_and_limit(self):
        accounts, history = self._stores()
        assert _history_entries(accounts, history, None, "LOOT", 20)[0]["summary"] == "b1"
        assert len(_history_entries(accounts, history, None, None, 1)) == 1

    def test_history_without_account_found_by_old_name(self):
        accounts, history = self._stores()
        entries = _history_entries(accounts, history, "Gone", None, 20)
        assert [(e["summary"], e["account_name"]) for e in entries] == [("g1", "Gone")]
