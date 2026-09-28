"""Tests for the parser subsystem – base JSON parser."""

from __future__ import annotations

import copy
import os
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

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
        # Sections that weren't sent are left out (not defaulted to empty)
        assert "inventory" not in result
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
        assert "inventory" not in result

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
        result = parse({"player": {"name": "P", "equipment": {"items": []}}})
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


class TestPluginCompatParsing:
    """HA Exporter #29/#33 widened values to long; #35+ events must pass through."""

    def test_large_values_intact(self):
        payload = {
            "player": {
                "name": "P",
                "inventory": {"items": [{"name": "Twisted bow", "gePrice": 3_000_000_000, "quantity": 1}]},
            },
            "events": [{"type": "death", "data": {"valueLost": 3_000_000_000}}],
        }
        result = parse(payload)
        assert result["inventory"][0]["gePrice"] == 3_000_000_000
        assert result["events"][0]["data"]["valueLost"] == 3_000_000_000

    def test_malformed_events_dropped(self):
        payload = {
            "player": {"name": "P"},
            "events": ["junk", {"data": {}}, {"type": 5}, {"type": "collectionLog", "data": {}}],
        }
        assert parse(payload)["events"] == [{"type": "collectionLog", "data": {}}]


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


# ── state parsing ───────────────────────────────────────────────────


class TestStateParsing:
    def test_state_present(self):
        result = parse({"player": {"name": "P"}, "state": "LOGGED_IN"})
        assert result is not None
        assert result["state"] == "LOGGED_IN"

    def test_state_absent_defaults_to_unknown(self):
        result = parse({"player": {"name": "P"}})
        assert result is not None
        assert result["state"] == "UNKNOWN"

    def test_state_case_insensitive(self):
        result = parse({"player": {"name": "P"}, "state": "logged_in"})
        assert result is not None
        assert result["state"] == "LOGGED_IN"

    def test_state_login_screen(self):
        result = parse({"player": {"name": "P"}, "state": "LOGIN_SCREEN"})
        assert result is not None
        assert result["state"] == "LOGIN_SCREEN"

    def test_state_login_screen_authenticator(self):
        result = parse({"player": {"name": "P"}, "state": "LOGIN_SCREEN_AUTHENTICATOR"})
        assert result is not None
        assert result["state"] == "LOGIN_SCREEN_AUTHENTICATOR"

    def test_state_connection_lost(self):
        result = parse({"player": {"name": "P"}, "state": "CONNECTION_LOST"})
        assert result is not None
        assert result["state"] == "CONNECTION_LOST"

    def test_state_hopping(self):
        result = parse({"player": {"name": "P"}, "state": "HOPPING"})
        assert result is not None
        assert result["state"] == "HOPPING"

    def test_state_starting(self):
        result = parse({"player": {"name": "P"}, "state": "STARTING"})
        assert result is not None
        assert result["state"] == "STARTING"

    def test_state_loading(self):
        result = parse({"player": {"name": "P"}, "state": "LOADING"})
        assert result is not None
        assert result["state"] == "LOADING"

    def test_state_logging_in(self):
        result = parse({"player": {"name": "P"}, "state": "LOGGING_IN"})
        assert result is not None
        assert result["state"] == "LOGGING_IN"

    def test_invalid_state_defaults_to_unknown(self):
        result = parse({"player": {"name": "P"}, "state": "INVALID_STATE"})
        assert result is not None
        assert result["state"] == "UNKNOWN"

    def test_state_non_string_defaults_to_unknown(self):
        result = parse({"player": {"name": "P"}, "state": 123})
        assert result is not None
        assert result["state"] == "UNKNOWN"

    def test_state_empty_string_defaults_to_unknown(self):
        result = parse({"player": {"name": "P"}, "state": ""})
        assert result is not None
        assert result["state"] == "UNKNOWN"


# ── Optional fields from newer plugin versions ──────────────────────


class TestNewPluginFields:
    HASH = "a" * 56  # salted SHA-224 hex digest

    def test_new_fields_parsed(self):
        result = parse({
            "timestamp": "2026-09-28T12:00:00Z",
            "player": {
                "name": "P",
                "accountHash": self.HASH,
                "worldTypes": ["MEMBERS", "seasonal"],
            },
            "events": [
                {
                    "type": "DEATH",
                    "eventId": "uuid-1",
                    "timestamp": "2026-09-28T11:59:59Z",
                    "data": {},
                }
            ],
        })
        assert result is not None
        assert result["timestamp"] == "2026-09-28T12:00:00Z"
        assert result["accountHash"] == self.HASH
        assert result["worldTypes"] == ["MEMBERS", "SEASONAL"]
        # Per-event fields pass through untouched
        assert result["events"][0]["eventId"] == "uuid-1"
        assert result["events"][0]["timestamp"] == "2026-09-28T11:59:59Z"

    def test_new_fields_absent_defaults(self):
        result = parse({"player": {"name": "P"}})
        assert result is not None
        assert result["timestamp"] is None
        assert result["accountHash"] is None
        assert result["worldTypes"] == []

    def test_malformed_world_types_ignored(self):
        for bad in ("SEASONAL", {"a": 1}, 5, None):
            result = parse({"player": {"name": "P", "worldTypes": bad}})
            assert result is not None
            assert result["worldTypes"] == []

    def test_non_string_world_type_entries_dropped(self):
        result = parse({"player": {"name": "P", "worldTypes": ["MEMBERS", 3, None, ""]}})
        assert result is not None
        assert result["worldTypes"] == ["MEMBERS"]

    def test_malformed_account_hash_ignored(self):
        for bad in ("", "   ", 12345, None, {"h": 1}):
            result = parse({"player": {"name": "P", "accountHash": bad}})
            assert result is not None
            assert result["accountHash"] is None


# ── Wrong types (valid JSON, wrong shape) ───────────────────────────


FUZZ_BASE: dict[str, Any] = {
    "player": {
        "name": "PlayerOne",
        "accountType": "0",
        "world": "302",
        "stats": {"skills": {"Attack": {"xp": 737627, "level": 60}}},
        "inventory": {"items": [
            {"id": 385, "name": "Shark", "gePrice": 800, "haPrice": 600, "quantity": 10},
        ]},
        "equipment": {"items": [
            {"id": 6570, "name": "Fire cape", "quantity": 1, "equipmentSlot": "CAPE"},
        ]},
        "health": {"current": 75, "max": 99},
        "prayerPoints": {"current": 43, "max": 43},
        "location": {"x": 3200, "y": 3200, "plane": 0},
        "spellbook": {"id": 0, "name": "standard"},
        "worldTypes": ["MEMBERS"],
        "accountHash": "e" * 56,
    },
    "events": [{
        "type": "death",
        "eventId": "fuzz-1",
        "timestamp": 1_700_000_000_000,
        "data": {"killerName": "Jad"},
    }],
    "tickDelay": 20,
    "state": "LOGGED_IN",
    "timestamp": 1_700_000_000_000,
}

_ITEM = ("player", "inventory", "items", 0)
_SLOT = ("player", "equipment", "items", 0)
FUZZ_PATHS: list[tuple] = [
    ("player", "accountType"), ("player", "world"),
    ("player", "stats"), ("player", "stats", "skills"),
    ("player", "stats", "skills", "Attack"),
    ("player", "stats", "skills", "Attack", "xp"),
    ("player", "stats", "skills", "Attack", "level"),
    ("player", "inventory"), ("player", "inventory", "items"), _ITEM,
    (*_ITEM, "id"), (*_ITEM, "name"), (*_ITEM, "gePrice"), (*_ITEM, "quantity"),
    ("player", "equipment"), ("player", "equipment", "items"), _SLOT,
    (*_SLOT, "equipmentSlot"), (*_SLOT, "name"),
    ("player", "health"), ("player", "health", "current"),
    ("player", "prayerPoints"), ("player", "prayerPoints", "max"),
    ("player", "location"), ("player", "location", "x"),
    ("player", "spellbook"), ("player", "spellbook", "id"), ("player", "spellbook", "name"),
    ("player", "worldTypes"), ("player", "accountHash"),
    ("events",), ("events", 0), ("events", 0, "type"), ("events", 0, "data"),
    ("events", 0, "eventId"), ("events", 0, "timestamp"),
    ("tickDelay",), ("state",), ("timestamp",),
]
FUZZ_VALUES: list[Any] = [None, True, 7, -1.5, "junk", [], [1, "x"], {}, {"k": "v"}]


def fuzzed(path: tuple, value: Any) -> dict[str, Any]:
    """Return a copy of FUZZ_BASE with the value at *path* replaced."""
    payload = copy.deepcopy(FUZZ_BASE)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return payload


class TestWrongTypesAreSkipped:
    """A wrong type skips that section or field; the parser never raises."""

    @pytest.mark.parametrize("path", FUZZ_PATHS, ids=lambda p: ".".join(map(str, p)))
    def test_parse_never_raises(self, path):
        for value in FUZZ_VALUES:
            result = parse(fuzzed(path, value))
            assert result is not None
            assert result["name"] == "PlayerOne"

    def test_null_equipment_slot_skips_only_that_item(self):
        result = parse({"player": {"name": "P", "equipment": {"items": [
            {"name": "Mystery", "equipmentSlot": None},
            {"name": "Fire cape", "equipmentSlot": "CAPE"},
        ]}}})
        assert result["equipment"]["CAPE"]["name"] == "Fire cape"
        assert sum(1 for item in result["equipment"].values() if item) == 1

    def test_skills_as_list_are_skipped(self):
        result = parse({"player": {"name": "P", "stats": {"skills": [{"xp": 1}]}}})
        assert result["skills"] == {}

    def test_non_numeric_skill_skipped(self):
        result = parse({"player": {"name": "P", "stats": {"skills": {
            "Attack": {"xp": "lots", "level": 60},
            "Strength": {"xp": 100, "level": None},
            "Defence": {"xp": 100, "level": 2},
        }}}})
        assert result["skills"] == {"Defence": {"xp": 100, "level": 2}}

    def test_inventory_items_as_object_skip_section(self):
        result = parse({"player": {"name": "P", "inventory": {"items": {"0": {"name": "Shark"}}}}})
        assert "inventory" not in result

    def test_wrong_item_fields_fall_back_to_defaults(self):
        result = parse({"player": {"name": "P", "inventory": {"items": [
            {"id": "385", "name": 5, "gePrice": "800", "haPrice": None, "quantity": True},
        ]}}})
        assert result["inventory"] == [
            {"id": None, "name": "", "gePrice": 0, "haPrice": 0, "quantity": 0}
        ]

    def test_section_of_wrong_type_is_skipped(self):
        for section in ("inventory", "equipment", "health", "prayerPoints", "location", "spellbook"):
            for bad in ("x", 5, [1], True):
                result = parse({"player": {"name": "P", section: bad}})
                assert section not in result, (section, bad)

    def test_wrong_field_type_skips_section(self):
        cases = {
            "health": {"current": "full", "max": 99},
            "prayerPoints": {"current": 1, "max": [1]},
            "location": {"x": 1, "y": None, "plane": 0},
            "spellbook": {"id": "3", "name": "arceuus"},
        }
        for section, bad in cases.items():
            assert section not in parse({"player": {"name": "P", section: bad}}), section

    def test_scalars_of_wrong_type_use_defaults(self):
        result = parse({
            "player": {"name": "P", "accountType": ["x"], "world": {"id": 1}},
            "tickDelay": True,
        })
        assert result["accountType"] == "normal"
        assert result["world"] is None
        assert result["tickDelay"] is None

    def test_name_must_be_a_non_blank_string(self):
        for bad in (7, True, ["P"], {"n": "P"}, "   "):
            assert parse({"player": {"name": bad}}) is None, bad



class TestAbsentSections:
    """A section the plugin leaves out is not in the result (not defaulted)."""

    SECTIONS = ("inventory", "equipment", "health", "prayerPoints", "location", "spellbook")

    def test_absent_sections_are_left_out(self):
        result = parse({"player": {"name": "P"}})
        for section in self.SECTIONS:
            assert section not in result, section

    def test_null_sections_are_left_out(self):
        result = parse({"player": {"name": "P", **{s: None for s in self.SECTIONS}}})
        for section in self.SECTIONS:
            assert section not in result, section

    def test_present_but_empty_sections_are_kept(self):
        result = parse({"player": {
            "name": "P",
            "inventory": {"items": []},
            "equipment": {},
        }})
        assert result["inventory"] == []
        assert result["equipment"] == {slot: {} for slot in EQUIPMENT_SLOTS}
