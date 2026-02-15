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

from custom_components.osrs_webhook.history import (  # noqa: E402
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
