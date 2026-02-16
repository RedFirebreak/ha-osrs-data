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

from custom_components.osrs_data.account_store import (  # noqa: E402
    AccountState,
)
from custom_components.osrs_data.sensor import (  # noqa: E402
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

    def test_level_allskills_creates_all_skill_sensors(self):
        """allSkills section should create sensors for every skill."""
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled Sailing", {
            "levelledSkills": {"Sailing": 68},
            "allSkills": {
                "Thieving": 71,
                "Runecraft": 80,
                "Cooking": 71,
                "Sailing": 68,
                "Attack": 94,
                "Defence": 93,
            },
            "combatLevel": 120,
        })
        # All skills from allSkills should be present
        assert state.detail_sensors["Thieving"]["value"] == 71
        assert state.detail_sensors["Runecraft"]["value"] == 80
        assert state.detail_sensors["Attack"]["value"] == 94
        assert state.detail_sensors["Defence"]["value"] == 93
        # Levelled skill is also present
        assert state.detail_sensors["Sailing"]["value"] == 68
        # Combat level
        assert state.detail_sensors["Combat Level"]["value"] == 120
        # Total: 6 skills + 1 combat level
        assert len(state.detail_sensors) == 7

    def test_level_allskills_without_levelled_skills(self):
        """allSkills alone should populate sensors even without levelledSkills."""
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled", {
            "levelledSkills": {},
            "allSkills": {"Attack": 50, "Strength": 60},
        })
        assert state.detail_sensors["Attack"]["value"] == 50
        assert state.detail_sensors["Strength"]["value"] == 60
        assert len(state.detail_sensors) == 2

    def test_level_levelled_overrides_allskills(self):
        """levelledSkills should overlay allSkills if both present."""
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled Attack", {
            "levelledSkills": {"Attack": 71},
            "allSkills": {"Attack": 70, "Strength": 60},
        })
        # levelledSkills value wins (applied after allSkills)
        assert state.detail_sensors["Attack"]["value"] == 71
        assert state.detail_sensors["Strength"]["value"] == 60


class TestTypedLastEventSensors:
    """Tests for per-type last event tracking (LOOT, DEATH, PET, QUEST, etc.)."""

    def test_loot_updates_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("LOOT", "Looted Chambers of Xeric", {
            "source": "Chambers of Xeric",
            "totalValue": 42069,
            "items": [{"name": "Dragon scimitar", "quantity": 1}],
            "category": "EVENT",
            "killCount": 60,
        })
        assert "LOOT" in state.last_typed_events
        assert state.last_typed_events["LOOT"]["summary"] == "Looted Chambers of Xeric"
        assert state.last_typed_events["LOOT"]["data"]["source"] == "Chambers of Xeric"
        assert state.last_typed_events["LOOT"]["data"]["totalValue"] == 42069
        assert len(state.detail_sensors) == 0

    def test_death_updates_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("DEATH", "Died to Vorkath", {
            "killerName": "Vorkath",
            "valueLost": 5000,
            "isPvp": False,
        })
        assert "DEATH" in state.last_typed_events
        assert state.last_typed_events["DEATH"]["summary"] == "Died to Vorkath"
        assert state.last_typed_events["DEATH"]["data"]["killerName"] == "Vorkath"
        assert len(state.detail_sensors) == 0

    def test_pet_updates_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("PET", "Got pet", {
            "petName": "Ikkle hydra",
            "duplicate": False,
            "milestone": "5,000 killcount",
        })
        assert "PET" in state.last_typed_events
        assert state.last_typed_events["PET"]["summary"] == "Got pet"
        assert state.last_typed_events["PET"]["data"]["petName"] == "Ikkle hydra"
        assert len(state.detail_sensors) == 0

    def test_quest_updates_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("QUEST", "Completed Dragon Slayer I", {
            "questName": "Dragon Slayer I",
            "completedQuests": 22,
            "totalQuests": 156,
            "questPoints": 44,
            "totalQuestPoints": 293,
        })
        assert "QUEST" in state.last_typed_events
        assert state.last_typed_events["QUEST"]["summary"] == "Completed Dragon Slayer I"
        assert state.last_typed_events["QUEST"]["data"]["questName"] == "Dragon Slayer I"
        assert state.last_typed_events["QUEST"]["data"]["questPoints"] == 44
        assert len(state.detail_sensors) == 0

    def test_combat_achievement_updates_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("COMBAT_ACHIEVEMENT", "Completed Peach Conjurer", {
            "tier": "GRANDMASTER",
            "task": "Peach Conjurer",
            "taskPoints": 6,
            "totalPoints": 1337,
        })
        assert "COMBAT_ACHIEVEMENT" in state.last_typed_events
        typed = state.last_typed_events["COMBAT_ACHIEVEMENT"]
        assert typed["summary"] == "Completed Peach Conjurer"
        assert typed["data"]["tier"] == "GRANDMASTER"
        assert typed["data"]["taskPoints"] == 6
        assert len(state.detail_sensors) == 0

    def test_achievement_diary_updates_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("ACHIEVEMENT_DIARY", "Completed Varrock Hard", {
            "area": "Varrock",
            "difficulty": "HARD",
            "total": 15,
            "tasksCompleted": 152,
            "tasksTotal": 492,
        })
        assert "ACHIEVEMENT_DIARY" in state.last_typed_events
        typed = state.last_typed_events["ACHIEVEMENT_DIARY"]
        assert typed["summary"] == "Completed Varrock Hard"
        assert typed["data"]["area"] == "Varrock"
        assert typed["data"]["difficulty"] == "HARD"
        assert len(state.detail_sensors) == 0

    def test_collection_updates_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("COLLECTION", "Added Zamorak chaps", {
            "itemName": "Zamorak chaps",
            "itemId": 10372,
            "price": 500812,
            "completedEntries": 420,
            "totalEntries": 1443,
            "dropperName": "Clue Scroll (Hard)",
        })
        assert "COLLECTION" in state.last_typed_events
        typed = state.last_typed_events["COLLECTION"]
        assert typed["summary"] == "Added Zamorak chaps"
        assert typed["data"]["itemName"] == "Zamorak chaps"
        assert typed["data"]["completedEntries"] == 420
        assert typed["data"]["dropperName"] == "Clue Scroll (Hard)"
        assert len(state.detail_sensors) == 0

    def test_typed_last_event_overwrites_previous(self):
        state = AccountState("hash1", "Player")
        state.record_event("LOOT", "First loot", {"source": "Goblin", "totalValue": 10})
        state.record_event("LOOT", "Second loot", {"source": "Zulrah", "totalValue": 9999})
        assert state.last_typed_events["LOOT"]["summary"] == "Second loot"
        assert state.last_typed_events["LOOT"]["data"]["source"] == "Zulrah"

    def test_level_does_not_create_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled", {"levelledSkills": {"Attack": 70}})
        assert "LEVEL" not in state.last_typed_events

    def test_unsupported_type_no_typed_last_event(self):
        state = AccountState("hash1", "Player")
        state.record_event("LOGIN", "Logged in", {})
        assert len(state.last_typed_events) == 0


class TestDetailSensorsInitState:
    """Tests that detail_sensors dict is properly initialized."""

    def test_initial_detail_sensors_empty(self):
        state = AccountState("hash1", "Player")
        assert state.detail_sensors == {}
        assert state.last_typed_events == {}

    def test_unsupported_event_no_detail_sensors(self):
        state = AccountState("hash1", "Player")
        state.record_event("LOGIN", "Logged in", {})
        assert len(state.detail_sensors) == 0

    def test_level_and_loot_separate_tracking(self):
        """LEVEL creates detail sensors; LOOT creates typed last event."""
        state = AccountState("hash1", "Player")
        state.record_event("LEVEL", "Levelled", {
            "levelledSkills": {"Attack": 70},
        })
        state.record_event("LOOT", "Looted", {
            "source": "Zulrah",
            "totalValue": 500,
            "items": [],
        })
        assert "Attack" in state.detail_sensors
        assert len(state.detail_sensors) == 1
        assert "LOOT" in state.last_typed_events


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
