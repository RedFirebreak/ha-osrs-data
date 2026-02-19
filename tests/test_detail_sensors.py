"""Tests for detail sensor creation and updates via AccountState."""

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
)
from custom_components.osrs_data.sensor import (  # noqa: E402
    _slugify_detail_key,
)


class TestDetailSensorsSkills:
    """Tests for skill sensor population from player data updates."""

    def test_creates_xp_and_level_sensors(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 737627, "level": 60}},
        })
        assert "Attack XP" in state.detail_sensors
        assert "Attack Level" in state.detail_sensors
        assert state.detail_sensors["Attack XP"]["value"] == 737627
        assert state.detail_sensors["Attack Level"]["value"] == 60
        assert state.detail_sensors["Attack XP"]["attributes"]["skill"] == "Attack"

    def test_creates_sensors_for_multiple_skills(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {
                "Attack": {"xp": 1000, "level": 10},
                "Defence": {"xp": 2000, "level": 20},
            },
        })
        assert "Attack XP" in state.detail_sensors
        assert "Attack Level" in state.detail_sensors
        assert "Defence XP" in state.detail_sensors
        assert "Defence Level" in state.detail_sensors
        assert state.detail_sensors["Attack XP"]["value"] == 1000
        assert state.detail_sensors["Defence Level"]["value"] == 20

    def test_updates_existing_skill_sensor(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })
        state.update_player_data({
            "skills": {"Attack": {"xp": 2000, "level": 11}},
        })
        assert state.detail_sensors["Attack XP"]["value"] == 2000
        assert state.detail_sensors["Attack Level"]["value"] == 11

    def test_no_skills_no_detail_sensors(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({"skills": {}})
        assert len(state.detail_sensors) == 0

    def test_no_skills_key_no_detail_sensors(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({})
        assert len(state.detail_sensors) == 0

    def test_all_skills_creates_all_sensors(self):
        """Multiple skills should create pairs of XP + Level sensors."""
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {
                "Attack": {"xp": 100, "level": 10},
                "Defence": {"xp": 200, "level": 20},
                "Strength": {"xp": 300, "level": 30},
                "Magic": {"xp": 400, "level": 40},
            },
        })
        # 4 skills × 2 sensors each = 8 detail sensors
        assert len(state.detail_sensors) == 8
        assert state.detail_sensors["Magic XP"]["value"] == 400
        assert state.detail_sensors["Magic Level"]["value"] == 40

    def test_unchanged_skill_not_refreshed(self):
        """If XP and level are the same, the sensor should not be refreshed."""
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })
        first_ts = state.detail_sensors["Attack XP"]["last_update"]

        import time
        time.sleep(0.01)
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })
        assert state.detail_sensors["Attack XP"]["last_update"] == first_ts

    def test_xp_change_triggers_refresh(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "skills": {"Attack": {"xp": 1000, "level": 10}},
        })
        first_ts = state.detail_sensors["Attack XP"]["last_update"]

        import time
        time.sleep(0.01)
        state.update_player_data({
            "skills": {"Attack": {"xp": 1500, "level": 10}},
        })
        assert state.detail_sensors["Attack XP"]["value"] == 1500
        assert state.detail_sensors["Attack XP"]["last_update"] != first_ts


class TestInventoryAndEquipment:
    """Tests for inventory and equipment state tracking."""

    def test_inventory_stored(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "inventory": [
                {"name": "Shark", "gePrice": 800, "quantity": 10},
            ],
        })
        assert len(state.inventory) == 1
        assert state.inventory[0]["name"] == "Shark"

    def test_equipment_stored(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "equipment": {
                "HEAD": {"name": "Helm", "gePrice": 5000},
                "CAPE": {},
            },
        })
        assert state.equipment["HEAD"]["name"] == "Helm"
        assert state.equipment["CAPE"] == {}

    def test_events_stored(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({"events": []})
        assert state.events == []

    def test_inventory_does_not_create_detail_sensors(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "inventory": [{"name": "Shark", "quantity": 10}],
        })
        assert len(state.detail_sensors) == 0

    def test_equipment_does_not_create_detail_sensors(self):
        state = AccountState("hash1", "Player")
        state.update_player_data({
            "equipment": {"HEAD": {"name": "Helm"}},
        })
        assert len(state.detail_sensors) == 0


class TestSlugifyDetailKey:
    """Tests for the _slugify_detail_key helper."""

    def test_simple_key(self):
        assert _slugify_detail_key("Attack XP") == "attack_xp"

    def test_key_with_spaces(self):
        assert _slugify_detail_key("Attack Level") == "attack_level"

    def test_key_with_special_chars(self):
        assert _slugify_detail_key("Quest - Cook's Assistant") == "quest_cook_s_assistant"

    def test_truncation(self):
        long_key = "A" * 100
        result = _slugify_detail_key(long_key)
        assert len(result) <= 64
