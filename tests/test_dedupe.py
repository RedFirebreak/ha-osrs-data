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


PAYLOAD_A = {"player": {"name": "P", "skills": {"Attack": {"xp": 100, "level": 10}}}}
PAYLOAD_B = {"player": {"name": "P", "skills": {"Attack": {"xp": 200, "level": 11}}}}


class TestBuildSignature:
    def test_same_inputs_same_sig(self):
        sig1 = _build_signature("acc1", PAYLOAD_A)
        sig2 = _build_signature("acc1", PAYLOAD_A)
        assert sig1 == sig2

    def test_different_payload_different_sig(self):
        sig1 = _build_signature("acc1", PAYLOAD_A)
        sig2 = _build_signature("acc1", PAYLOAD_B)
        assert sig1 != sig2

    def test_different_account_different_sig(self):
        sig1 = _build_signature("acc1", PAYLOAD_A)
        sig2 = _build_signature("acc2", PAYLOAD_A)
        assert sig1 != sig2


class TestDedupeCache:
    def test_first_submission_not_duplicate(self):
        cache = DedupeCache(ttl=30)
        assert cache.is_duplicate("acc1", PAYLOAD_A) is False

    def test_immediate_replay_is_duplicate(self):
        cache = DedupeCache(ttl=30)
        cache.is_duplicate("acc1", PAYLOAD_A)
        assert cache.is_duplicate("acc1", PAYLOAD_A) is True

    def test_different_payload_not_duplicate(self):
        cache = DedupeCache(ttl=30)
        cache.is_duplicate("acc1", PAYLOAD_A)
        assert cache.is_duplicate("acc1", PAYLOAD_B) is False

    def test_ttl_expiry(self):
        """After TTL expires, same payload should pass again."""
        cache = DedupeCache(ttl=1)
        cache.is_duplicate("acc1", PAYLOAD_A)

        # Simulate time passing by manipulating the seen dict
        for key in cache._seen:
            cache._seen[key] = time.monotonic() - 2
        assert cache.is_duplicate("acc1", PAYLOAD_A) is False

    def test_different_accounts_not_duplicate(self):
        cache = DedupeCache(ttl=30)
        cache.is_duplicate("acc1", PAYLOAD_A)
        assert cache.is_duplicate("acc2", PAYLOAD_A) is False
