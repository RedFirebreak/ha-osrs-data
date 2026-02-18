"""Tests for TTL-based deduplication."""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock, patch

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

from custom_components.osrs_data.dedupe import (  # noqa: E402
    DedupeCache,
    _build_signature,
)


class TestBuildSignature:
    def test_same_inputs_same_sig(self):
        sig1 = _build_signature("acc1", "LOOT", {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"})
        sig2 = _build_signature("acc1", "LOOT", {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"})
        assert sig1 == sig2

    def test_different_items_different_sig(self):
        sig1 = _build_signature("acc1", "LOOT", {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"})
        sig2 = _build_signature("acc1", "LOOT", {"items": [{"name": "Shield", "quantity": 1}], "source": "Boss"})
        assert sig1 != sig2

    def test_different_quantity_different_sig(self):
        sig1 = _build_signature("acc1", "LOOT", {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"})
        sig2 = _build_signature("acc1", "LOOT", {"items": [{"name": "Sword", "quantity": 2}], "source": "Boss"})
        assert sig1 != sig2

    def test_different_account_different_sig(self):
        sig1 = _build_signature("acc1", "LOOT", {"items": [], "source": "Boss"})
        sig2 = _build_signature("acc2", "LOOT", {"items": [], "source": "Boss"})
        assert sig1 != sig2

    def test_level_signature(self):
        sig1 = _build_signature("acc1", "LEVEL", {"levelledSkills": {"Attack": 70}})
        sig2 = _build_signature("acc1", "LEVEL", {"levelledSkills": {"Attack": 70}})
        assert sig1 == sig2

    def test_level_different_skill_different_sig(self):
        sig1 = _build_signature("acc1", "LEVEL", {"levelledSkills": {"Attack": 70}})
        sig2 = _build_signature("acc1", "LEVEL", {"levelledSkills": {"Defence": 70}})
        assert sig1 != sig2

    def test_death_signature(self):
        sig1 = _build_signature("acc1", "DEATH", {"valueLost": 5000, "isPvp": True, "killerName": "PKer"})
        sig2 = _build_signature("acc1", "DEATH", {"valueLost": 5000, "isPvp": True, "killerName": "PKer"})
        assert sig1 == sig2

    def test_quest_signature(self):
        sig1 = _build_signature("acc1", "QUEST", {"questName": "Dragon Slayer I"})
        sig2 = _build_signature("acc1", "QUEST", {"questName": "Dragon Slayer I"})
        assert sig1 == sig2

    def test_pet_signature(self):
        sig1 = _build_signature("acc1", "PET", {"petName": "Vorki", "duplicate": False})
        sig2 = _build_signature("acc1", "PET", {"petName": "Vorki", "duplicate": False})
        assert sig1 == sig2


class TestDedupeCache:
    def test_first_event_not_duplicate(self):
        cache = DedupeCache(ttl=30)
        assert cache.is_duplicate("acc1", "LOOT", {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"}) is False

    def test_immediate_replay_is_duplicate(self):
        cache = DedupeCache(ttl=30)
        extra = {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"}
        cache.is_duplicate("acc1", "LOOT", extra)
        assert cache.is_duplicate("acc1", "LOOT", extra) is True

    def test_different_loot_not_duplicate(self):
        """Different items at the same time should not be considered duplicates."""
        cache = DedupeCache(ttl=30)
        cache.is_duplicate("acc1", "LOOT", {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"})
        assert cache.is_duplicate("acc1", "LOOT", {"items": [{"name": "Shield", "quantity": 1}], "source": "Boss"}) is False

    def test_ttl_expiry(self):
        """After TTL expires, same event should pass again."""
        cache = DedupeCache(ttl=1)
        extra = {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"}
        cache.is_duplicate("acc1", "LOOT", extra)

        # Simulate time passing by manipulating the seen dict
        for key in cache._seen:
            cache._seen[key] = time.monotonic() - 2
        assert cache.is_duplicate("acc1", "LOOT", extra) is False

    def test_different_event_types_not_duplicate(self):
        cache = DedupeCache(ttl=30)
        cache.is_duplicate("acc1", "LOOT", {"items": [], "source": "Boss"})
        assert cache.is_duplicate("acc1", "DEATH", {"valueLost": 100, "isPvp": False}) is False

    def test_different_accounts_not_duplicate(self):
        cache = DedupeCache(ttl=30)
        extra = {"items": [{"name": "Sword", "quantity": 1}], "source": "Boss"}
        cache.is_duplicate("acc1", "LOOT", extra)
        assert cache.is_duplicate("acc2", "LOOT", extra) is False
