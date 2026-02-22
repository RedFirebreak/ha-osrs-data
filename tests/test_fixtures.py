"""Tests that verify the base parser handles realistic payloads."""

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

from custom_components.osrs_data.parser.base import parse, EQUIPMENT_SLOTS  # noqa: E402


# A realistic full payload matching the new Runelite plugin structure.
FULL_PAYLOAD: dict[str, Any] = {
    "player": {
        "name": "PlayerOne",
        "accountType": "normal",
        "world": "302",
        "stats": {
            "skills": {
                "Attack": {"xp": 737627, "level": 60},
                "Defence": {"xp": 123456, "level": 50},
                "Strength": {"xp": 900000, "level": 70},
                "Hitpoints": {"xp": 1234567, "level": 75},
                "Ranged": {"xp": 500000, "level": 55},
                "Prayer": {"xp": 200000, "level": 43},
                "Magic": {"xp": 400000, "level": 59},
            }
        },
        "inventory": {
            "items": [
                {"name": "Shark", "gePrice": 800, "haPrice": 600, "quantity": 10},
                {"name": "Super combat potion(4)", "gePrice": 12000, "haPrice": 5000, "quantity": 3},
            ]
        },
        "equipment": {
            "items": [
                {"name": "Neitiznot faceguard", "gePrice": 3500000, "haPrice": 60000, "quantity": 1, "equipmentSlot": "HEAD"},
                {"name": "Fire cape", "gePrice": 0, "haPrice": 0, "quantity": 1, "equipmentSlot": "CAPE"},
                {"name": "Abyssal whip", "gePrice": 1500000, "haPrice": 72000, "quantity": 1, "equipmentSlot": "WEAPON"},
                {"name": "Dragon boots", "gePrice": 200000, "haPrice": 30000, "quantity": 1, "equipmentSlot": "BOOTS"},
            ]
        },
        "events": [],
    },
    "state": "LOGGED_IN",
}


class TestFullPayload:
    def test_parse_succeeds(self):
        result = parse(FULL_PAYLOAD)
        assert result is not None

    def test_player_info(self):
        result = parse(FULL_PAYLOAD)
        assert result["name"] == "PlayerOne"
        assert result["accountType"] == "normal"
        assert result["world"] == "302"

    def test_skills_count(self):
        result = parse(FULL_PAYLOAD)
        assert len(result["skills"]) == 7
        assert result["skills"]["Attack"]["xp"] == 737627
        assert result["skills"]["Attack"]["level"] == 60

    def test_inventory_items(self):
        result = parse(FULL_PAYLOAD)
        assert len(result["inventory"]) == 2
        assert result["inventory"][0]["name"] == "Shark"
        assert result["inventory"][0]["quantity"] == 10

    def test_equipment_filled_slots(self):
        result = parse(FULL_PAYLOAD)
        assert result["equipment"]["HEAD"]["name"] == "Neitiznot faceguard"
        assert result["equipment"]["CAPE"]["name"] == "Fire cape"
        assert result["equipment"]["WEAPON"]["name"] == "Abyssal whip"
        assert result["equipment"]["BOOTS"]["name"] == "Dragon boots"

    def test_equipment_empty_slots(self):
        result = parse(FULL_PAYLOAD)
        # Slots not in the equipment items list should be empty
        assert result["equipment"]["BODY"] == {}
        assert result["equipment"]["LEGS"] == {}
        assert result["equipment"]["RING"] == {}
        assert result["equipment"]["SHIELD"] == {}

    def test_events_empty(self):
        result = parse(FULL_PAYLOAD)
        assert result["events"] == []

    def test_state(self):
        result = parse(FULL_PAYLOAD)
        assert result["state"] == "LOGGED_IN"

    def test_all_equipment_slots_present(self):
        result = parse(FULL_PAYLOAD)
        for slot in EQUIPMENT_SLOTS:
            assert slot in result["equipment"]
