"""Tests that load JSON fixtures from samples/ and assert correct parsing."""

from __future__ import annotations

import json
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
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.parser.dispatcher import dispatch  # noqa: E402

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "samples")


def _load_fixture(name: str) -> dict[str, Any]:
    path = os.path.join(SAMPLES_DIR, name)
    with open(path) as f:
        return json.load(f)


class TestLevelFixture:
    def test_dispatcher_routes_level(self):
        fixture = _load_fixture("level.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result is not None

    def test_level_fields(self):
        fixture = _load_fixture("level.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result["data"]["levelledSkills"] == {"Attack": 70}
        assert result["data"]["combatLevel"] == 85
        assert result["data"]["combatLevelIncreased"] is True
        assert "Attack" in result["summary"]
        assert fixture["playerName"] in result["summary"]


class TestLootFixture:
    def test_dispatcher_routes_loot(self):
        fixture = _load_fixture("loot.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result is not None

    def test_loot_fields(self):
        fixture = _load_fixture("loot.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result["data"]["source"] == "Chambers of Xeric"
        assert result["data"]["totalValue"] == 42069
        assert result["data"]["category"] == "EVENT"
        assert result["data"]["killCount"] == 60
        assert len(result["data"]["items"]) == 1
        assert result["data"]["items"][0]["name"] == "Dragon scimitar"
        assert result["data"]["items"][0]["rarity"] == 0.01


class TestDeathFixture:
    def test_dispatcher_routes_death(self):
        fixture = _load_fixture("death.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result is not None

    def test_death_fields(self):
        fixture = _load_fixture("death.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result["data"]["valueLost"] == 5000
        assert result["data"]["isPvp"] is True
        assert result["data"]["killerName"] == "PKer123"
        assert len(result["data"]["lostItems"]) == 1
        assert "PKer123" in result["summary"]
        assert "PvP" in result["summary"]


class TestPetFixture:
    def test_dispatcher_routes_pet(self):
        fixture = _load_fixture("pet.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result is not None

    def test_pet_fields(self):
        fixture = _load_fixture("pet.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result["data"]["petName"] == "Ikkle hydra"
        assert result["data"]["milestone"] == "5,000 killcount"
        assert result["data"]["duplicate"] is False
        assert "Ikkle hydra" in result["summary"]


class TestQuestFixture:
    def test_dispatcher_routes_quest(self):
        fixture = _load_fixture("quest.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result is not None

    def test_quest_fields(self):
        fixture = _load_fixture("quest.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result["data"]["questName"] == "Dragon Slayer I"
        assert result["data"]["completedQuests"] == 22
        assert result["data"]["totalQuests"] == 156
        assert result["data"]["questPoints"] == 44
        assert "Dragon Slayer I" in result["summary"]


class TestCombatAchievementFixture:
    def test_dispatcher_routes_combat_achievement(self):
        fixture = _load_fixture("combat_achievement.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result is not None

    def test_combat_achievement_fields(self):
        fixture = _load_fixture("combat_achievement.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result["data"]["tier"] == "GRANDMASTER"
        assert result["data"]["task"] == "Peach Conjurer"
        assert result["data"]["taskPoints"] == 6
        assert result["data"]["totalPoints"] == 1337
        assert "Peach Conjurer" in result["summary"]


class TestAchievementDiaryFixture:
    def test_dispatcher_routes_achievement_diary(self):
        fixture = _load_fixture("achievement_diary.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result is not None

    def test_achievement_diary_fields(self):
        fixture = _load_fixture("achievement_diary.json")
        result = dispatch(fixture["type"], fixture["extra"], fixture["playerName"])
        assert result["data"]["area"] == "Varrock"
        assert result["data"]["difficulty"] == "HARD"
        assert result["data"]["total"] == 15
        assert result["data"]["tasksCompleted"] == 152
        assert "Varrock" in result["summary"]
        assert "HARD" in result["summary"]
