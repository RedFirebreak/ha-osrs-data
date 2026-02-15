"""Tests for the parser subsystem – dispatcher + individual parsers."""

from __future__ import annotations

import os
import sys
from typing import Any
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
    "homeassistant.helpers.webhook",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_webhook.parser.dispatcher import (  # noqa: E402
    dispatch,
    SUPPORTED_TYPES,
)


# ── Dispatcher ───────────────────────────────────────────────────────


class TestDispatcher:
    def test_supported_types(self):
        expected = {
            "LEVEL", "LOOT", "DEATH", "PET",
            "QUEST", "COMBAT_ACHIEVEMENT", "ACHIEVEMENT_DIARY",
        }
        assert SUPPORTED_TYPES == expected

    def test_unsupported_type_returns_none(self):
        assert dispatch("LOGIN", {}, "Player") is None

    def test_case_insensitive(self):
        result = dispatch("level", {"levelledSkills": {"Attack": 50}}, "P")
        assert result is not None


# ── LEVEL parser ─────────────────────────────────────────────────────


class TestLevelParser:
    def test_basic_level(self):
        extra: dict[str, Any] = {
            "levelledSkills": {"Attack": 70},
            "allSkills": {"Attack": 70, "Strength": 60},
            "combatLevel": {"value": 85, "increased": True},
        }
        result = dispatch("LEVEL", extra, "PlayerOne")
        assert result is not None
        assert "Attack" in result["summary"]
        assert result["data"]["levelledSkills"] == {"Attack": 70}
        assert result["data"]["combatLevel"] == 85
        assert result["data"]["combatLevelIncreased"] is True

    def test_multiple_skills(self):
        extra: dict[str, Any] = {
            "levelledSkills": {"Attack": 70, "Defence": 65},
            "combatLevel": {"value": 85, "increased": False},
        }
        result = dispatch("LEVEL", extra, "Player")
        assert result is not None
        assert "Attack" in result["summary"]
        assert "Defence" in result["summary"]

    def test_no_combat_level(self):
        extra: dict[str, Any] = {
            "levelledSkills": {"Fishing": 50},
        }
        result = dispatch("LEVEL", extra, "Player")
        assert result is not None
        assert "combatLevel" not in result["data"]

    def test_empty_extra(self):
        result = dispatch("LEVEL", {}, "Player")
        assert result is not None
        assert result["data"]["levelledSkills"] == {}


# ── LOOT parser ──────────────────────────────────────────────────────


class TestLootParser:
    def test_basic_loot(self):
        extra: dict[str, Any] = {
            "items": [
                {"id": 1234, "quantity": 1, "priceEach": 42069, "name": "Dragon scimitar", "rarity": 0.01, "criteria": ["VALUE"]},
            ],
            "source": "Chambers of Xeric",
            "category": "EVENT",
            "killCount": 60,
        }
        result = dispatch("LOOT", extra, "Player")
        assert result is not None
        assert "Dragon scimitar" in result["summary"]
        assert "Chambers of Xeric" in result["summary"]
        assert result["data"]["source"] == "Chambers of Xeric"
        assert result["data"]["totalValue"] == 42069
        assert result["data"]["category"] == "EVENT"
        assert result["data"]["killCount"] == 60
        assert result["data"]["items"][0]["rarity"] == 0.01
        assert result["data"]["items"][0]["criteria"] == ["VALUE"]

    def test_multiple_items(self):
        extra: dict[str, Any] = {
            "items": [
                {"id": 1, "quantity": 10, "priceEach": 100, "name": "Item A"},
                {"id": 2, "quantity": 5, "priceEach": 200, "name": "Item B"},
            ],
            "source": "Boss",
        }
        result = dispatch("LOOT", extra, "Player")
        assert result is not None
        assert result["data"]["totalValue"] == 10 * 100 + 5 * 200

    def test_no_items(self):
        result = dispatch("LOOT", {"source": "Empty"}, "Player")
        assert result is not None
        assert result["data"]["items"] == []
        assert result["data"]["totalValue"] == 0
        assert "received loot" in result["summary"]

    def test_no_kill_count(self):
        result = dispatch("LOOT", {"items": [], "source": "Test"}, "Player")
        assert result is not None
        assert "killCount" not in result["data"]


# ── DEATH parser ─────────────────────────────────────────────────────


class TestDeathParser:
    def test_basic_death(self):
        extra: dict[str, Any] = {
            "valueLost": 300,
            "isPvp": False,
            "keptItems": [],
            "lostItems": [{"id": 314, "quantity": 100, "priceEach": 3, "name": "Feather"}],
            "location": {"regionId": 10546, "plane": 0, "instanced": False},
        }
        result = dispatch("DEATH", extra, "Player")
        assert result is not None
        assert "300" in result["summary"]
        assert result["data"]["valueLost"] == 300
        assert result["data"]["isPvp"] is False
        assert len(result["data"]["lostItems"]) == 1
        assert result["data"]["location"]["regionId"] == 10546

    def test_pvp_death(self):
        extra: dict[str, Any] = {
            "valueLost": 5000,
            "isPvp": True,
            "killerName": "PKer123",
            "keptItems": [],
            "lostItems": [],
        }
        result = dispatch("DEATH", extra, "Victim")
        assert result is not None
        assert "PKer123" in result["summary"]
        assert "PvP" in result["summary"]
        assert result["data"]["killerName"] == "PKer123"

    def test_npc_death(self):
        extra: dict[str, Any] = {
            "valueLost": 1000,
            "isPvp": False,
            "killerName": "Vorkath",
            "killerNpcId": 8061,
            "keptItems": [],
            "lostItems": [],
        }
        result = dispatch("DEATH", extra, "Player")
        assert result is not None
        assert "Vorkath" in result["summary"]
        assert result["data"]["killerNpcId"] == 8061

    def test_minimal_death(self):
        result = dispatch("DEATH", {"valueLost": 0, "isPvp": False}, "Player")
        assert result is not None
        assert result["data"]["valueLost"] == 0


# ── PET parser ───────────────────────────────────────────────────────


class TestPetParser:
    def test_basic_pet(self):
        extra: dict[str, Any] = {
            "petName": "Ikkle hydra",
            "milestone": "5,000 killcount",
            "duplicate": False,
        }
        result = dispatch("PET", extra, "Player")
        assert result is not None
        assert "Ikkle hydra" in result["summary"]
        assert result["data"]["petName"] == "Ikkle hydra"
        assert result["data"]["milestone"] == "5,000 killcount"
        assert result["data"]["duplicate"] is False

    def test_duplicate_pet(self):
        extra: dict[str, Any] = {"petName": "Baby mole", "duplicate": True}
        result = dispatch("PET", extra, "Player")
        assert result is not None
        assert "duplicate" in result["summary"]

    def test_no_pet_name(self):
        result = dispatch("PET", {}, "Player")
        assert result is not None
        assert "received a pet" in result["summary"]

    def test_no_milestone(self):
        result = dispatch("PET", {"petName": "Vorki"}, "Player")
        assert result is not None
        assert "milestone" not in result["data"]


# ── QUEST parser ─────────────────────────────────────────────────────


class TestQuestParser:
    def test_basic_quest(self):
        extra: dict[str, Any] = {
            "questName": "Dragon Slayer I",
            "completedQuests": 22,
            "totalQuests": 156,
            "questPoints": 44,
            "totalQuestPoints": 293,
        }
        result = dispatch("QUEST", extra, "Player")
        assert result is not None
        assert "Dragon Slayer I" in result["summary"]
        assert result["data"]["completedQuests"] == 22
        assert result["data"]["totalQuests"] == 156
        assert result["data"]["questPoints"] == 44
        assert result["data"]["totalQuestPoints"] == 293

    def test_minimal_quest(self):
        result = dispatch("QUEST", {"questName": "Cook's Assistant"}, "Player")
        assert result is not None
        assert "completedQuests" not in result["data"]


# ── COMBAT_ACHIEVEMENT parser ────────────────────────────────────────


class TestCombatAchievementParser:
    def test_basic_task(self):
        extra: dict[str, Any] = {
            "tier": "GRANDMASTER",
            "task": "Peach Conjurer",
            "taskPoints": 6,
            "totalPoints": 1337,
            "currentTier": "MASTER",
            "nextTier": "GRANDMASTER",
        }
        result = dispatch("COMBAT_ACHIEVEMENT", extra, "Player")
        assert result is not None
        assert "Peach Conjurer" in result["summary"]
        assert "GRANDMASTER" in result["summary"]
        assert result["data"]["tier"] == "GRANDMASTER"
        assert result["data"]["taskPoints"] == 6
        assert result["data"]["totalPoints"] == 1337
        assert result["data"]["currentTier"] == "MASTER"

    def test_just_completed_tier(self):
        extra: dict[str, Any] = {
            "tier": "GRANDMASTER",
            "task": "Peach Conjurer",
            "taskPoints": 6,
            "totalPoints": 1465,
            "nextTier": "GRANDMASTER",
            "justCompletedTier": "MASTER",
        }
        result = dispatch("COMBAT_ACHIEVEMENT", extra, "Player")
        assert result is not None
        assert "MASTER" in result["summary"]
        assert "completed" in result["summary"].lower()
        assert result["data"]["justCompletedTier"] == "MASTER"

    def test_minimal(self):
        result = dispatch("COMBAT_ACHIEVEMENT", {}, "Player")
        assert result is not None
        assert result["data"]["tier"] == "Unknown"


# ── ACHIEVEMENT_DIARY parser ────────────────────────────────────────


class TestAchievementDiaryParser:
    def test_basic_diary(self):
        extra: dict[str, Any] = {
            "area": "Varrock",
            "difficulty": "HARD",
            "total": 15,
            "tasksCompleted": 152,
            "tasksTotal": 492,
            "areaTasksCompleted": 37,
            "areaTasksTotal": 42,
        }
        result = dispatch("ACHIEVEMENT_DIARY", extra, "Player")
        assert result is not None
        assert "Varrock" in result["summary"]
        assert "HARD" in result["summary"]
        assert result["data"]["area"] == "Varrock"
        assert result["data"]["difficulty"] == "HARD"
        assert result["data"]["total"] == 15
        assert result["data"]["tasksCompleted"] == 152
        assert result["data"]["tasksTotal"] == 492
        assert result["data"]["areaTasksCompleted"] == 37
        assert result["data"]["areaTasksTotal"] == 42

    def test_minimal_diary(self):
        result = dispatch("ACHIEVEMENT_DIARY", {"area": "Lumbridge", "difficulty": "EASY"}, "Player")
        assert result is not None
        assert "total" not in result["data"]
