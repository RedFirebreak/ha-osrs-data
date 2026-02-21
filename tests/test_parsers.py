"""Tests for the parser subsystem – base JSON parser."""

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

from custom_components.osrs_data.parser.base import (  # noqa: E402
    parse,
    EQUIPMENT_SLOTS,
)


# ── Valid payloads ──────────────────────────────────────────────────


class TestBaseParser:
    def test_valid_full_payload(self):
        payload: dict[str, Any] = {
            "player": {
                "name": "PlayerOne",
                "accountType": "normal",
                "world": "302",
                "stats": {
                    "skills": {
                        "Attack": {"xp": 737627, "level": 60},
                        "Defence": {"xp": 123456, "level": 50},
                    }
                },
                "inventory": {
                    "items": [
                        {"name": "Shark", "gePrice": 800, "haPrice": 600, "quantity": 10},
                    ]
                },
                "equipment": {
                    "items": [
                        {"name": "Fire cape", "gePrice": 0, "haPrice": 0, "quantity": 1, "equipmentSlot": "CAPE"},
                    ]
                },
                "events": [],
            }
        }
        result = parse(payload)
        assert result is not None
        assert result["name"] == "PlayerOne"
        assert result["accountType"] == "normal"
        assert result["world"] == "302"
        assert "Attack" in result["skills"]
        assert result["skills"]["Attack"]["xp"] == 737627
        assert result["skills"]["Attack"]["level"] == 60
        assert len(result["inventory"]) == 1
        assert result["inventory"][0]["name"] == "Shark"
        assert result["equipment"]["CAPE"]["name"] == "Fire cape"
        assert result["events"] == []

    def test_missing_player_returns_none(self):
        assert parse({}) is None
        assert parse({"something": "else"}) is None

    def test_player_not_dict_returns_none(self):
        assert parse({"player": "invalid"}) is None
        assert parse({"player": None}) is None

    def test_minimal_player(self):
        result = parse({"player": {"name": "Test"}})
        assert result is not None
        assert result["name"] == "Test"
        assert result["accountType"] == "normal"
        assert result["world"] is None
        assert result["skills"] == {}
        assert result["inventory"] == []
        assert result["events"] == []

    def test_missing_name_returns_none(self):
        assert parse({"player": {}}) is None
        assert parse({"player": {"accountType": "normal"}}) is None


# ── Skills parsing ──────────────────────────────────────────────────


class TestSkillsParsing:
    def test_multiple_skills(self):
        payload: dict[str, Any] = {
            "player": {
                "name": "P",
                "stats": {
                    "skills": {
                        "Attack": {"xp": 100, "level": 10},
                        "Strength": {"xp": 200, "level": 20},
                        "Magic": {"xp": 300, "level": 30},
                    }
                },
            }
        }
        result = parse(payload)
        assert result is not None
        assert len(result["skills"]) == 3
        assert result["skills"]["Magic"]["xp"] == 300
        assert result["skills"]["Magic"]["level"] == 30

    def test_empty_skills(self):
        result = parse({"player": {"name": "P", "stats": {"skills": {}}}})
        assert result is not None
        assert result["skills"] == {}

    def test_no_stats_section(self):
        result = parse({"player": {"name": "P"}})
        assert result is not None
        assert result["skills"] == {}

    def test_skill_defaults(self):
        result = parse({"player": {"name": "P", "stats": {"skills": {"Attack": {}}}}})
        assert result is not None
        assert result["skills"]["Attack"]["xp"] == 0
        assert result["skills"]["Attack"]["level"] == 1

    def test_invalid_skill_data_skipped(self):
        result = parse({"player": {"name": "P", "stats": {"skills": {"Attack": "invalid"}}}})
        assert result is not None
        assert "Attack" not in result["skills"]


# ── Inventory parsing ───────────────────────────────────────────────


class TestInventoryParsing:
    def test_inventory_items(self):
        payload: dict[str, Any] = {
            "player": {
                "name": "P",
                "inventory": {
                    "items": [
                        {"name": "Shark", "gePrice": 800, "haPrice": 600, "quantity": 10},
                        {"name": "Lobster", "gePrice": 200, "haPrice": 150, "quantity": 5},
                    ]
                },
            }
        }
        result = parse(payload)
        assert result is not None
        assert len(result["inventory"]) == 2
        assert result["inventory"][0]["name"] == "Shark"
        assert result["inventory"][1]["gePrice"] == 200

    def test_max_28_items(self):
        items = [{"name": f"Item{i}", "quantity": 1} for i in range(35)]
        result = parse({"player": {"name": "P", "inventory": {"items": items}}})
        assert result is not None
        assert len(result["inventory"]) == 28

    def test_empty_inventory(self):
        result = parse({"player": {"name": "P", "inventory": {"items": []}}})
        assert result is not None
        assert result["inventory"] == []

    def test_no_inventory_section(self):
        result = parse({"player": {"name": "P"}})
        assert result is not None
        assert result["inventory"] == []

    def test_item_defaults(self):
        result = parse({"player": {"name": "P", "inventory": {"items": [{}]}}})
        assert result is not None
        assert result["inventory"][0]["name"] == ""
        assert result["inventory"][0]["gePrice"] == 0
        assert result["inventory"][0]["haPrice"] == 0
        assert result["inventory"][0]["quantity"] == 0


# ── Equipment parsing ───────────────────────────────────────────────


class TestEquipmentParsing:
    def test_equipment_slots(self):
        payload: dict[str, Any] = {
            "player": {
                "name": "P",
                "equipment": {
                    "items": [
                        {"name": "Fire cape", "gePrice": 0, "haPrice": 0, "quantity": 1, "equipmentSlot": "CAPE"},
                        {"name": "Dragon boots", "gePrice": 200000, "haPrice": 30000, "quantity": 1, "equipmentSlot": "BOOTS"},
                    ]
                },
            }
        }
        result = parse(payload)
        assert result is not None
        assert result["equipment"]["CAPE"]["name"] == "Fire cape"
        assert result["equipment"]["BOOTS"]["name"] == "Dragon boots"

    def test_missing_slots_are_empty(self):
        result = parse({"player": {"name": "P", "equipment": {"items": []}}})
        assert result is not None
        for slot in EQUIPMENT_SLOTS:
            assert result["equipment"][slot] == {}

    def test_all_known_slots(self):
        result = parse({"player": {"name": "P"}})
        assert result is not None
        assert set(result["equipment"].keys()) == set(EQUIPMENT_SLOTS)

    def test_unknown_slot_ignored(self):
        payload: dict[str, Any] = {
            "player": {
                "name": "P",
                "equipment": {
                    "items": [
                        {"name": "Weird item", "equipmentSlot": "UNKNOWN_SLOT"},
                    ]
                },
            }
        }
        result = parse(payload)
        assert result is not None
        assert "UNKNOWN_SLOT" not in result["equipment"]

    def test_case_insensitive_slot(self):
        payload: dict[str, Any] = {
            "player": {
                "name": "P",
                "equipment": {
                    "items": [
                        {"name": "Cape", "equipmentSlot": "cape"},
                    ]
                },
            }
        }
        result = parse(payload)
        assert result is not None
        assert result["equipment"]["CAPE"]["name"] == "Cape"


# ── Events parsing ──────────────────────────────────────────────────


class TestEventsParsing:
    def test_empty_events(self):
        result = parse({"player": {"name": "P", "events": []}})
        assert result is not None
        assert result["events"] == []

    def test_no_events_key(self):
        result = parse({"player": {"name": "P"}})
        assert result is not None
        assert result["events"] == []

    def test_invalid_events_becomes_empty(self):
        result = parse({"player": {"name": "P", "events": "not_a_list"}})
        assert result is not None
        assert result["events"] == []

    def test_root_level_events(self):
        """Events at the root level (sibling of 'player') are parsed."""
        result = parse({
            "player": {"name": "P"},
            "events": [{"type": "ClientShutdown", "data": "Shutdown"}],
        })
        assert result is not None
        assert len(result["events"]) == 1
        assert result["events"][0]["type"] == "ClientShutdown"

    def test_root_level_events_take_precedence(self):
        """Root-level events take precedence over player-level events."""
        result = parse({
            "player": {
                "name": "P",
                "events": [{"type": "LOGIN"}],
            },
            "events": [{"type": "LOGOUT"}],
        })
        assert result is not None
        assert len(result["events"]) == 1
        assert result["events"][0]["type"] == "LOGOUT"

    def test_player_level_events_fallback(self):
        """Player-level events are used when root-level events are absent."""
        result = parse({
            "player": {
                "name": "P",
                "events": [{"type": "LOGIN"}],
            },
        })
        assert result is not None
        assert len(result["events"]) == 1
        assert result["events"][0]["type"] == "LOGIN"

    def test_root_level_empty_list_falls_back_to_player(self):
        """An empty root-level events list falls back to player-level."""
        result = parse({
            "player": {
                "name": "P",
                "events": [{"type": "LOGIN"}],
            },
            "events": [],
        })
        assert result is not None
        # Empty list is falsy, so player-level events are used
        assert len(result["events"]) == 1
        assert result["events"][0]["type"] == "LOGIN"


# ── tickDelay parsing ───────────────────────────────────────────────


class TestTickDelayParsing:
    def test_tick_delay_present(self):
        result = parse({"player": {"name": "P"}, "tickDelay": 20})
        assert result is not None
        assert result["tickDelay"] == 20

    def test_tick_delay_absent(self):
        result = parse({"player": {"name": "P"}})
        assert result is not None
        assert result["tickDelay"] is None

    def test_tick_delay_float_truncated(self):
        result = parse({"player": {"name": "P"}, "tickDelay": 15.7})
        assert result is not None
        assert result["tickDelay"] == 15

    def test_tick_delay_zero_ignored(self):
        result = parse({"player": {"name": "P"}, "tickDelay": 0})
        assert result is not None
        assert result["tickDelay"] is None

    def test_tick_delay_negative_ignored(self):
        result = parse({"player": {"name": "P"}, "tickDelay": -5})
        assert result is not None
        assert result["tickDelay"] is None

    def test_tick_delay_string_ignored(self):
        result = parse({"player": {"name": "P"}, "tickDelay": "20"})
        assert result is not None
        assert result["tickDelay"] is None
