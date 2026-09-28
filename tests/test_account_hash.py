"""Tests for plugin accountHash as a stable account alias."""

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

from custom_components.osrs_data.account_store import AccountStore  # noqa: E402

HASH_A = "a" * 56
HASH_B = "b" * 56


class TestLegacyMigration:
    def test_name_keyed_account_binds_hash_without_rekey(self):
        store = AccountStore()
        legacy = store.get_or_create(None, "Zezima")
        assert legacy.account_hash == "zezima"

        same = store.get_or_create(None, "Zezima", plugin_hash=HASH_A)
        assert same is legacy
        assert same.account_hash == "zezima"  # unique_id basis unchanged
        assert same.plugin_account_hash == HASH_A
        assert len(store.accounts) == 1

    def test_rename_after_binding_keeps_state_and_key(self):
        store = AccountStore()
        acct = store.get_or_create(None, "Zezima")
        store.get_or_create(None, "Zezima", plugin_hash=HASH_A)
        acct.update_player_data({}, player_name="Zezima")

        renamed = store.get_or_create(None, "Zezima Jr", plugin_hash=HASH_A)
        renamed.update_player_data({}, player_name="Zezima Jr")

        assert renamed is acct
        assert renamed.account_hash == "zezima"
        assert renamed.player_name == "Zezima Jr"
        assert renamed.previous_names == ["Zezima"]
        # Dispatcher lookups by key still resolve after the rename
        assert store.get_by_hash("zezima") is acct
        # Name index follows the new name; old name no longer resolves
        assert store.get_or_create(None, "zezima jr") is acct
        assert len(store.accounts) == 1
        # A different (hashless) player taking the freed name gets a new,
        # non-colliding key so unique_ids never clash.
        other = store.get_or_create(None, "Zezima")
        assert other is not acct
        assert other.account_hash == "zezima_2"
        assert store.get_by_hash("zezima") is acct
        assert store.get_by_hash("zezima_2") is other
        assert len(store.accounts) == 2


class TestHashedAccounts:
    def test_new_hashed_account_keyed_by_hash(self):
        store = AccountStore()
        acct = store.get_or_create(None, "Newbie", plugin_hash=HASH_A)
        assert acct.account_hash == HASH_A
        assert acct.plugin_account_hash == HASH_A

    def test_new_hashed_account_survives_rename(self):
        store = AccountStore()
        acct = store.get_or_create(None, "Newbie", plugin_hash=HASH_A)
        acct.update_player_data({}, player_name="Newbie")
        renamed = store.get_or_create(None, "Veteran", plugin_hash=HASH_A)
        renamed.update_player_data({}, player_name="Veteran")
        assert renamed is acct
        assert renamed.account_hash == HASH_A
        assert store.get_by_hash(HASH_A) is acct

    def test_name_reused_by_different_account(self):
        store = AccountStore()
        a = store.get_or_create(None, "Bob", plugin_hash=HASH_A)
        b = store.get_or_create(None, "Bob", plugin_hash=HASH_B)
        assert a is not b
        assert a.account_hash != b.account_hash
        assert b.account_hash == HASH_B
        # "Bob" now resolves to the latest owner
        assert store.get_or_create(None, "Bob") is b
        # A is still reachable by its hash
        assert store.get_or_create(None, "Alice", plugin_hash=HASH_A) is a

    def test_hash_lookup_does_not_reindex_name(self):
        store = AccountStore()
        acct = store.get_or_create(None, "Old", plugin_hash=HASH_A)
        store.get_or_create(None, "New", plugin_hash=HASH_A).update_player_data(
            {}, player_name="New"
        )
        # A late resend with the old name is looked up but not applied.
        assert store.get_or_create(None, "Old", plugin_hash=HASH_A) is acct
        assert acct.player_name == "New"

        assert store.get_or_create(None, "New") is acct
        assert store.get_or_create(None, "Old") is not acct
        assert len(store.accounts) == 2

    def test_name_index_follows_rename_back(self):
        store = AccountStore()
        acct = store.get_or_create(None, "Old", plugin_hash=HASH_A)
        acct.update_player_data({}, player_name="New")
        acct.update_player_data({}, player_name="Old")  # applied snapshot
        assert store.get_or_create(None, "Old") is acct
        assert store.get_or_create(None, "New") is not acct

    def test_hashless_payload_still_resolves_bound_account(self):
        store = AccountStore()
        acct = store.get_or_create(None, "Bob", plugin_hash=HASH_A)
        assert store.get_or_create(None, "Bob") is acct

    def test_capitalization_change_is_not_a_rename(self):
        store = AccountStore()
        acct = store.get_or_create(None, "Bob", plugin_hash=HASH_A)
        acct.update_player_data({}, player_name="Bob")
        acct.update_player_data({}, player_name="bob")
        assert acct.previous_names == []

    def test_previous_names_capped(self):
        store = AccountStore()
        acct = store.get_or_create(None, "N0", plugin_hash=HASH_A)
        for i in range(1, 15):
            acct.update_player_data({}, player_name=f"N{i}")
        assert len(acct.previous_names) == 10
        assert acct.previous_names[-1] == "N13"


class TestPersistence:
    def test_keys_and_aliases_roundtrip(self):
        store = AccountStore()
        legacy = store.get_or_create(None, "Zezima")
        store.get_or_create(None, "Zezima", plugin_hash=HASH_A)
        legacy.update_player_data({}, player_name="Zezima")
        store.get_or_create(None, "Renamed", plugin_hash=HASH_A).update_player_data(
            {}, player_name="Renamed"
        )
        store.get_or_create(None, "Fresh", plugin_hash=HASH_B)

        store2 = AccountStore()
        store2.load_dict(store.to_dict())
        assert len(store2.accounts) == 2

        restored = store2.get_or_create(None, "Whatever", plugin_hash=HASH_A)
        assert restored.account_hash == "zezima"
        assert restored.player_name == "Renamed"
        assert restored.previous_names == ["Zezima"]
        assert store2.get_by_hash("zezima") is restored

        fresh = store2.get_or_create(None, "Fresh")
        assert fresh.account_hash == HASH_B
        assert fresh.plugin_account_hash == HASH_B

    def test_legacy_storage_without_new_fields(self):
        store = AccountStore()
        store.load_dict([{"account_hash": "zezima", "player_name": "Zezima"}])
        acct = store.get_or_create(None, "Zezima", plugin_hash=HASH_A)
        assert acct.account_hash == "zezima"
        assert acct.plugin_account_hash == HASH_A
        assert acct.previous_names == []

