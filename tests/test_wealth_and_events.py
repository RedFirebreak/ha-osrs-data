"""Tests for skill aggregates, rich event state, and history recording."""

from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

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

# Provide a minimal HomeAssistantView mock (mirrors test_event_firing.py)
_http_mod = sys.modules["homeassistant.components.http"]


class _MockView:
    requires_auth = True

    def json(self, data, status_code=200):
        from aiohttp.web import json_response

        return json_response(data, status=status_code)


_http_mod.HomeAssistantView = _MockView
# NOTE: deliberately do NOT pop/re-import custom_components.osrs_data.api here.
# Re-importing it would replace the module object other test files already
# bound their OsrsEventsView / patch targets to, breaking their isolation.

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.account_store import (  # noqa: E402
    AccountState,
    AccountStore,
    _level_from_xp,
)
from custom_components.osrs_data.api import OsrsEventsView  # noqa: E402
from custom_components.osrs_data.const import (  # noqa: E402
    DATA_ACCOUNT_STORE,
    DATA_DEDUPE_CACHE,
    DATA_EVENT_DEDUPE_CACHE,
    DATA_HISTORY_STORE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    DOMAIN,
)
from custom_components.osrs_data.dedupe import (  # noqa: E402
    DedupeCache,
    EventDedupeCache,
)
from custom_components.osrs_data.history import HistoryStore  # noqa: E402
from custom_components.osrs_data.pairing import PairingStore  # noqa: E402


# ── Computed aggregates ─────────────────────────────────────────────


# Well-known OSRS XP → level anchors.
_XP_L1 = 0
_XP_L2 = 83
_XP_L10 = 1154
_XP_L92 = 6_517_253
_XP_L99 = 13_034_431


class TestLevelFromXp:
    def test_known_anchors(self):
        assert _level_from_xp(_XP_L1) == 1
        assert _level_from_xp(-5) == 1
        assert _level_from_xp(_XP_L2) == 2
        assert _level_from_xp(_XP_L10) == 10
        assert _level_from_xp(_XP_L92) == 92
        assert _level_from_xp(_XP_L99) == 99
        # Virtual levels are capped at 99.
        assert _level_from_xp(200_000_000) == 99


class TestAggregates:
    def test_total_level_is_derived_from_xp(self):
        state = AccountState("h", "P")
        # Deliberately give a boosted/wrong `level` field to prove it is
        # ignored — levels come from XP.
        state.skills = {
            "Attack": {"xp": _XP_L99, "level": 120},
            "Strength": {"xp": _XP_L92, "level": 120},
            "Defence": {"xp": _XP_L10, "level": 120},
            "Cooking": {"xp": _XP_L1, "level": 120},
        }
        assert state.total_level == 99 + 92 + 10 + 1
        assert state.total_xp == _XP_L99 + _XP_L92 + _XP_L10 + _XP_L1

    def test_combat_level_maxed(self):
        state = AccountState("h", "P")
        state.skills = {
            s: {"xp": _XP_L99}
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
        # All 99s -> max combat level 126.
        assert state.combat_level == 126

    def test_combat_level_ignores_boosted_level_field(self):
        # 99 Att/Str/Def/HP/Range/Magic + 92 Prayer.
        # base=0.25*(99+99+46)=61.0, melee=0.325*198=64.35 -> floor(125.35)=125.
        # The inflated `level` fields must be ignored (XP wins).
        state = AccountState("h", "P")
        levels_xp = {
            "Attack": _XP_L99,
            "Strength": _XP_L99,
            "Defence": _XP_L99,
            "Hitpoints": _XP_L99,
            "Ranged": _XP_L99,
            "Magic": _XP_L99,
            "Prayer": _XP_L92,
        }
        state.skills = {k: {"xp": v, "level": 130} for k, v in levels_xp.items()}
        assert state.combat_level == 125

    def test_combat_level_none_without_skills(self):
        assert AccountState("h", "P").combat_level is None


# ── Rich event state ────────────────────────────────────────────────


class TestRecordGameEvent:
    def test_death_stores_last_death_and_counter(self):
        state = AccountState("h", "P")
        state.record_game_event(
            "DEATH", {"killerName": "Guard", "valueLost": 88}
        )
        assert state.last_death["killerName"] == "Guard"
        assert state.last_death["valueLost"] == 88
        assert "timestamp" in state.last_death
        assert state.event_totals["DEATH"]["count"] == 1

    def test_loot_and_pkloot_store_last_loot(self):
        state = AccountState("h", "P")
        state.record_game_event("LOOT", {"totalValue": 35})
        assert state.last_loot["totalValue"] == 35
        state.record_game_event("PKLOOT", {"totalValue": 999})
        assert state.last_loot["totalValue"] == 999

    def test_non_rich_event_only_bumps_counter(self):
        state = AccountState("h", "P")
        state.record_game_event("LEVELUP", {"value": [{"skill": "Attack"}]})
        assert state.event_totals["LEVELUP"]["count"] == 1
        assert state.last_death == {}
        assert state.last_loot == {}

    def test_persistence_round_trip(self):
        state = AccountState("h", "P")
        state.record_game_event("DEATH", {"killerName": "Guard"})
        state.record_game_event("LOOT", {"totalValue": 500})
        restored = AccountState("h", "P")
        restored.load_dict(state.to_dict())
        assert restored.last_death["killerName"] == "Guard"
        assert restored.last_loot["totalValue"] == 500


# ── History recording through the events endpoint ───────────────────


def _setup_hass_and_token():
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    store = AccountStore()
    history = HistoryStore()
    pairing_store = PairingStore()
    hass.data = {
        DOMAIN: {
            "test_entry": {
                DATA_ACCOUNT_STORE: store,
                DATA_HISTORY_STORE: history,
                DATA_DEDUPE_CACHE: DedupeCache(),
                DATA_EVENT_DEDUPE_CACHE: EventDedupeCache(),
                DATA_PAIRING_STORE: pairing_store,
                DATA_STORE: MagicMock(),
            }
        }
    }
    token = pairing_store.consume_pairing_code(
        pairing_store.create_pairing_code()
    )["token"]
    return hass, store, history, token


def _make_request(hass, payload, token):
    request = MagicMock()
    request.app = {"hass": hass}
    request.headers = {"Content-Type": "application/json", "X-Osrs-Token": token}
    request.json = AsyncMock(return_value=payload)
    return request


_PAYLOAD: dict[str, Any] = {
    "player": {
        "name": "TestPlayer",
        "accountType": "normal",
        "world": "302",
        "stats": {"skills": {}},
        "inventory": {"items": []},
        "equipment": {"items": []},
    },
    "events": [
        {"type": "death", "data": {"killerName": "Guard", "valueLost": 88}},
        {"type": "loot", "data": {"totalValue": 35, "source": {"text": "Goblin"}}},
    ],
}


class TestConfigurableOptions:
    def test_history_limits_are_applied(self):
        store = HistoryStore(limits={"DEATH": 2}, default_limit=3)
        hist = store.get_or_create("P")
        for i in range(5):
            hist.record("DEATH", f"d{i}", {"i": i})
        for i in range(5):
            hist.record("LOOT", f"l{i}", {"i": i})  # uses default_limit=3
        assert len(hist.get("DEATH")) == 2
        assert len(hist.get("LOOT")) == 3

    def test_presence_timeout_fallback_threads_to_state(self):
        store = AccountStore(presence_timeout=42)
        state = store.get_or_create(None, "Zezima")
        # No tickDelay yet -> uses the configured fallback.
        assert state.presence_timeout == 42


class TestHistoryRecording:
    @pytest.mark.asyncio
    async def test_events_recorded_into_typed_buffers(self):
        hass, _store, history, token = _setup_hass_and_token()
        view = OsrsEventsView()
        await view.post(_make_request(hass, _PAYLOAD, token))

        hist = history.get_or_create("TestPlayer")
        deaths = hist.get("DEATH")
        loot = hist.get("LOOT")
        assert len(deaths) == 1
        assert deaths[0]["data"]["killerName"] == "Guard"
        assert "Guard" in deaths[0]["summary"]
        assert len(loot) == 1
        assert loot[0]["data"]["totalValue"] == 35
        # The old generic DATA_UPDATE buffer must no longer be written.
        assert hist.get("DATA_UPDATE") == []
