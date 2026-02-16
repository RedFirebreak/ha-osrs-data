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
)
from custom_components.osrs_webhook.sensor import (  # noqa: E402
    _slugify_detail_key,
)


class TestDetailSensorsLevel:
    """Tests for LEVEL event detail sensor population."""

    def test_level_creates_skill_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled Attack", {
            "levelledSkills": {"Attack": 70},
        })
        assert "Attack" in state.detail_sensors
        assert state.detail_sensors["Attack"]["value"] == 70
        assert state.detail_sensors["Attack"]["attributes"]["skill"] == "Attack"
        assert "last_update" in state.detail_sensors["Attack"]

    def test_level_creates_multiple_skill_sensors(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled", {
            "levelledSkills": {"Attack": 70, "Defence": 65},
        })
        assert "Attack" in state.detail_sensors
        assert "Defence" in state.detail_sensors
        assert state.detail_sensors["Attack"]["value"] == 70
        assert state.detail_sensors["Defence"]["value"] == 65

    def test_level_creates_combat_level_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled", {
            "levelledSkills": {"Attack": 70},
            "combatLevel": 85,
            "combatLevelIncreased": True,
        })
        assert "Combat Level" in state.detail_sensors
        assert state.detail_sensors["Combat Level"]["value"] == 85
        assert state.detail_sensors["Combat Level"]["attributes"]["increased"] is True

    def test_level_updates_existing_skill_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled Attack", {
            "levelledSkills": {"Attack": 70},
        })
        state.record_event("LEVEL", "Levelled Attack again", {
            "levelledSkills": {"Attack": 71},
        })
        assert state.detail_sensors["Attack"]["value"] == 71

    def test_level_no_combat_level_no_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled", {
            "levelledSkills": {"Fishing": 50},
        })
        assert "Combat Level" not in state.detail_sensors

    def test_level_empty_skills_no_detail_sensors(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled", {
            "levelledSkills": {},
        })
        assert len(state.detail_sensors) == 0


class TestDetailSensorsLoot:
    """Tests for LOOT event detail sensor population."""

    def test_loot_creates_source_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("LOOT", "Looted", {
            "source": "Chambers of Xeric",
            "totalValue": 42069,
            "items": [{"name": "Dragon scimitar", "quantity": 1}],
            "category": "EVENT",
            "killCount": 60,
        })
        key = "Loot - Chambers of Xeric"
        assert key in state.detail_sensors
        assert state.detail_sensors[key]["value"] == 42069
        assert state.detail_sensors[key]["attributes"]["source"] == "Chambers of Xeric"
        assert state.detail_sensors[key]["attributes"]["killCount"] == 60

    def test_loot_unknown_source(self):
        state = AccountState("hash1", "Player")
        state.record_event("LOOT", "Looted", {
            "totalValue": 100,
            "items": [],
        })
        assert "Loot - Unknown" in state.detail_sensors


class TestDetailSensorsDeath:
    """Tests for DEATH event — updates Last Event only, no detail sensor."""

    def test_death_no_detail_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("DEATH", "Died", {
            "killerName": "Vorkath",
            "valueLost": 5000,
            "isPvp": False,
        })
        assert len(state.detail_sensors) == 0
        assert state.last_event_type == "DEATH"
        assert state.last_event_summary == "Died"


class TestDetailSensorsPet:
    """Tests for PET event — updates Last Event only, no detail sensor."""

    def test_pet_no_detail_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("PET", "Got pet", {
            "petName": "Ikkle hydra",
            "duplicate": False,
            "milestone": "5,000 killcount",
        })
        assert len(state.detail_sensors) == 0
        assert state.last_event_type == "PET"
        assert state.last_event_summary == "Got pet"


class TestDetailSensorsQuest:
    """Tests for QUEST event detail sensor population."""

    def test_quest_creates_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("QUEST", "Completed quest", {
            "questName": "Dragon Slayer I",
            "completedQuests": 22,
            "totalQuests": 156,
            "questPoints": 44,
            "totalQuestPoints": 293,
        })
        key = "Quest - Dragon Slayer I"
        assert key in state.detail_sensors
        assert state.detail_sensors[key]["value"] == "Dragon Slayer I"
        assert state.detail_sensors[key]["attributes"]["completedQuests"] == 22
        assert state.detail_sensors[key]["attributes"]["totalQuestPoints"] == 293


class TestDetailSensorsCombatAchievement:
    """Tests for COMBAT_ACHIEVEMENT event detail sensor population."""

    def test_combat_achievement_creates_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("COMBAT_ACHIEVEMENT", "Completed task", {
            "tier": "GRANDMASTER",
            "task": "Peach Conjurer",
            "taskPoints": 6,
            "totalPoints": 1337,
        })
        key = "Combat Achievement - Peach Conjurer"
        assert key in state.detail_sensors
        assert state.detail_sensors[key]["value"] == "Peach Conjurer"
        assert state.detail_sensors[key]["attributes"]["tier"] == "GRANDMASTER"
        assert state.detail_sensors[key]["attributes"]["taskPoints"] == 6


class TestDetailSensorsAchievementDiary:
    """Tests for ACHIEVEMENT_DIARY event detail sensor population."""

    def test_diary_creates_sensor(self):
        state = AccountState("hash1", "Player")
        state.record_event("ACHIEVEMENT_DIARY", "Completed diary", {
            "area": "Varrock",
            "difficulty": "HARD",
            "total": 15,
            "tasksCompleted": 152,
            "tasksTotal": 492,
        })
        key = "Achievement Diary - Varrock"
        assert key in state.detail_sensors
        assert state.detail_sensors[key]["value"] == "HARD"
        assert state.detail_sensors[key]["attributes"]["area"] == "Varrock"
        assert state.detail_sensors[key]["attributes"]["tasksCompleted"] == 152


class TestDetailSensorsInitState:
    """Tests that detail_sensors dict is properly initialized."""

    def test_initial_detail_sensors_empty(self):
        state = AccountState("hash1", "Player")
        assert state.detail_sensors == {}

    def test_unsupported_event_no_detail_sensors(self):
        state = AccountState("hash1", "Player")
        state.record_event("LOGIN", "Logged in", {})
        assert len(state.detail_sensors) == 0

    def test_multiple_event_types_accumulate(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled", {
            "levelledSkills": {"Attack": 70},
        })
        state.record_event("LOOT", "Looted", {
            "source": "Zulrah",
            "totalValue": 500,
            "items": [],
        })
        state.record_event("QUEST", "Quest", {
            "questName": "Cook's Assistant",
        })
        assert "Attack" in state.detail_sensors
        assert "Loot - Zulrah" in state.detail_sensors
        assert "Quest - Cook's Assistant" in state.detail_sensors
        assert len(state.detail_sensors) == 3


class TestSlugifyDetailKey:
    """Tests for the _slugify_detail_key helper."""

    def test_simple_key(self):
        assert _slugify_detail_key("Attack") == "attack"

    def test_key_with_spaces(self):
        assert _slugify_detail_key("Loot - Chambers of Xeric") == "loot_chambers_of_xeric"

    def test_key_with_special_chars(self):
        assert _slugify_detail_key("Quest - Cook's Assistant") == "quest_cook_s_assistant"

    def test_truncation(self):
        long_key = "A" * 100
        result = _slugify_detail_key(long_key)
        assert len(result) <= 64
