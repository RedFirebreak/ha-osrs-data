"""Tests for the OSRS Data sensor module."""

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
    "homeassistant.components.http",
    "homeassistant.components.sensor",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

# Provide a minimal real SensorEntity so the class can be instantiated.
# Use sys.modules[...] = (not setdefault) to ensure it takes effect even
# when another test file has already injected a plain MagicMock.
_sensor_mod = MagicMock()


class _SensorEntity:
    """Minimal stand-in for homeassistant.components.sensor.SensorEntity."""

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

# Force re-import of sensor module so it picks up our _SensorEntity
sys.modules.pop("custom_components.osrs_data.sensor", None)

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.account_store import AccountState  # noqa: E402
from custom_components.osrs_data.sensor import (  # noqa: E402
    OsrsStatusSensor,
    OsrsPlayerInfoSensor,
    OsrsInventorySensor,
    OsrsEquipmentSensor,
    OsrsAccountDetailSensor,
    OsrsGameStateSensor,
    OsrsTotalLevelSensor,
    OsrsCombatLevelSensor,
    OsrsLastDeathSensor,
    OsrsLastLootSensor,
)


def _make_entry():
    entry = MagicMock()
    entry.entry_id = "entry_1"
    entry.data = {}
    return entry


class TestOsrsStatusSensor:
    """Tests for the OsrsStatusSensor entity."""

    def test_status_value_is_ready(self):
        entry = _make_entry()
        sensor = OsrsStatusSensor(entry)
        assert sensor.native_value == "ready"

    def test_extra_state_attributes_contains_events_endpoint(self):
        entry = _make_entry()
        sensor = OsrsStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert attrs["events_endpoint"] == "/api/osrs-data/events"

    def test_extra_state_attributes_contains_pair_endpoint(self):
        entry = _make_entry()
        sensor = OsrsStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert attrs["pair_endpoint"] == "/api/osrs-data/pair"

    def test_no_webhook_attributes(self):
        """Ensure no legacy webhook attributes are exposed."""
        entry = _make_entry()
        sensor = OsrsStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert "webhook_id" not in attrs
        assert "webhook_url" not in attrs

    def test_unique_id(self):
        entry = _make_entry()
        sensor = OsrsStatusSensor(entry)
        assert sensor.unique_id == "entry_1_status"


class TestOsrsPlayerInfoSensor:
    """Tests for the OsrsPlayerInfoSensor entity."""

    def test_player_name_as_state(self):
        entry = _make_entry()
        state = AccountState("hash1", "PlayerOne")
        state.update_player_data({"accountType": "normal", "world": "302"})
        sensor = OsrsPlayerInfoSensor(entry, state, "hash1")
        assert sensor.native_value == "PlayerOne"

    def test_attributes_contain_account_type(self):
        entry = _make_entry()
        state = AccountState("hash1", "PlayerOne")
        state.update_player_data({"accountType": "iron", "world": "303"})
        sensor = OsrsPlayerInfoSensor(entry, state, "hash1")
        attrs = sensor.extra_state_attributes
        assert attrs["account_type"] == "iron"
        assert attrs["world"] == "303"

    def test_unique_id(self):
        entry = _make_entry()
        state = AccountState("hash1", "PlayerOne")
        sensor = OsrsPlayerInfoSensor(entry, state, "hash1")
        assert sensor.unique_id == "hash1_player_info"


class TestOsrsInventorySensor:
    """Tests for the OsrsInventorySensor entity."""

    def test_state_is_item_count(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "inventory": [
                {"name": "Shark", "quantity": 10},
                {"name": "Lobster", "quantity": 5},
            ],
        })
        sensor = OsrsInventorySensor(entry, state, "hash1")
        assert sensor.native_value == 2

    def test_attributes_contain_items(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "inventory": [{"name": "Shark", "quantity": 10}],
        })
        sensor = OsrsInventorySensor(entry, state, "hash1")
        attrs = sensor.extra_state_attributes
        assert attrs["items"] == [{"name": "Shark", "quantity": 10}]
        assert attrs["slots_used"] == 1
        assert attrs["slots_total"] == 28

    def test_unique_id(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsInventorySensor(entry, state, "hash1")
        assert sensor.unique_id == "hash1_inventory"


class TestOsrsEquipmentSensor:
    """Tests for the OsrsEquipmentSensor entity."""

    def test_state_is_equipped_count(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "equipment": {
                "HEAD": {"name": "Helm"},
                "CAPE": {"name": "Fire cape"},
                "WEAPON": {},
            },
        })
        sensor = OsrsEquipmentSensor(entry, state, "hash1")
        assert sensor.native_value == 2  # HEAD and CAPE only

    def test_attributes_include_all_slots(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "equipment": {"HEAD": {"name": "Helm"}},
        })
        sensor = OsrsEquipmentSensor(entry, state, "hash1")
        attrs = sensor.extra_state_attributes
        from custom_components.osrs_data.parser.base import EQUIPMENT_SLOTS
        for slot in EQUIPMENT_SLOTS:
            assert slot in attrs

    def test_missing_slot_is_empty(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({"equipment": {}})
        sensor = OsrsEquipmentSensor(entry, state, "hash1")
        attrs = sensor.extra_state_attributes
        assert attrs["HEAD"] == {}
        assert attrs["WEAPON"] == {}

    def test_unique_id(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsEquipmentSensor(entry, state, "hash1")
        assert sensor.unique_id == "hash1_equipment"


class TestOsrsAccountDetailSensor:
    """Tests for the per-skill detail sensor."""

    def test_skill_sensor(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 737627, "level": 60}},
        })
        sensor = OsrsAccountDetailSensor(entry, state, "hash1", "Attack")
        assert sensor.native_value == 60
        assert sensor.extra_state_attributes["xp"] == 737627

    def test_unique_id(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 100, "level": 10}},
        })
        sensor = OsrsAccountDetailSensor(entry, state, "hash1", "Attack")
        assert "hash1_detail_attack" == sensor.unique_id

    def test_no_dink_in_device_info(self):
        """Ensure no Dink references in device info."""
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsPlayerInfoSensor(entry, state, "hash1")
        info = sensor.device_info
        assert "Dink" not in str(info)


class TestOsrsGameStateSensor:
    """Tests for the OsrsGameStateSensor entity."""

    def test_default_state_is_unknown(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsGameStateSensor(entry, state, "hash1")
        assert sensor.native_value == "UNKNOWN"

    def test_state_logged_in(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({"state": "LOGGED_IN"})
        sensor = OsrsGameStateSensor(entry, state, "hash1")
        assert sensor.native_value == "LOGGED_IN"

    def test_state_login_screen(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({"state": "LOGIN_SCREEN"})
        sensor = OsrsGameStateSensor(entry, state, "hash1")
        assert sensor.native_value == "LOGIN_SCREEN"

    def test_state_updates(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({"state": "LOGGED_IN"})
        sensor = OsrsGameStateSensor(entry, state, "hash1")
        assert sensor.native_value == "LOGGED_IN"
        state.update_player_data({"state": "CONNECTION_LOST"})
        assert sensor.native_value == "CONNECTION_LOST"

    def test_unique_id(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsGameStateSensor(entry, state, "hash1")
        assert sensor.unique_id == "hash1_game_state"

    def test_attributes_contain_last_update(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.update_player_data({"state": "LOGGED_IN"})
        sensor = OsrsGameStateSensor(entry, state, "hash1")
        attrs = sensor.extra_state_attributes
        assert "last_update" in attrs


class TestOsrsLevelSensors:
    """Tests for total level and combat level sensors (derived from XP)."""

    # All seven combat skills at exactly level 99 (13,034,431 XP each).
    _MAXED = {
        s: {"xp": 13_034_431}
        for s in (
            "Attack",
            "Strength",
            "Defence",
            "Hitpoints",
            "Ranged",
            "Prayer",
            "Magic",
        )
    }

    def test_total_level(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.skills = dict(self._MAXED)
        sensor = OsrsTotalLevelSensor(entry, state, "hash1")
        assert sensor.native_value == 99 * 7
        assert sensor.extra_state_attributes["skill_count"] == 7

    def test_combat_level(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.skills = dict(self._MAXED)
        sensor = OsrsCombatLevelSensor(entry, state, "hash1")
        assert sensor.native_value == 126  # max combat


class TestOsrsLastEventSensors:
    """Tests for the Last Death / Last Loot sensors."""

    def test_last_death_none_until_event(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        sensor = OsrsLastDeathSensor(entry, state, "hash1")
        assert sensor.native_value is None
        # recent falls back to empty list without an attached hass
        assert sensor.extra_state_attributes["recent"] == []

    def test_last_death_populated(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.record_game_event("DEATH", {"killerName": "Guard", "valueLost": 88})
        sensor = OsrsLastDeathSensor(entry, state, "hash1")
        assert sensor.native_value == "Guard"
        attrs = sensor.extra_state_attributes
        assert attrs["value_lost"] == 88
        assert sensor.unique_id == "hash1_last_death"

    def test_last_loot_prefers_highest_value_item(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.record_game_event(
            "LOOT",
            {
                "totalValue": 5_000_000,
                "source": {"text": "Zulrah"},
                "highestValueItem": {"name": "Tanzanite fang"},
                "items": [{"name": "Snakeskin"}],
            },
        )
        sensor = OsrsLastLootSensor(entry, state, "hash1")
        # The notable item, not the NPC/source.
        assert sensor.native_value == "Tanzanite fang"
        assert sensor.extra_state_attributes["total_value"] == 5_000_000
        # Source is still available as an attribute.
        assert sensor.extra_state_attributes["source"] == {"text": "Zulrah"}

    def test_last_loot_falls_back_to_item_then_source(self):
        entry = _make_entry()
        state = AccountState("hash1", "Player")
        state.record_game_event(
            "LOOT", {"items": [{"name": "Bones"}], "source": {"text": "Goblin"}}
        )
        sensor = OsrsLastLootSensor(entry, state, "hash1")
        assert sensor.native_value == "Bones"
