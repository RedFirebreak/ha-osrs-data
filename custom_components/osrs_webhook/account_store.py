"""In-memory multi-account state store for OSRS Webhook."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def _normalize_player_name(name: str) -> str:
    """Normalize an RSN to a stable key (lowercase, collapse whitespace)."""
    return re.sub(r"\s+", " ", name.strip().lower())


class AccountState:
    """Per-account counters and last-event details."""

    def __init__(self, account_hash: str, player_name: str) -> None:
        self.account_hash: str = account_hash
        self.player_name: str = player_name

        # Counters
        self.levels_total: int = 0
        self.loot_events_total: int = 0
        self.deaths_total: int = 0
        self.pets_total: int = 0
        self.quests_total: int = 0
        self.combat_tasks_total: int = 0
        self.diaries_total: int = 0

        # Last event
        self.last_event_type: str | None = None
        self.last_event_summary: str | None = None
        self.last_event_data: dict[str, Any] = {}
        self.last_update: str | None = None

        # Detail sensors: key → {value, attributes, last_update}
        self.detail_sensors: dict[str, dict[str, Any]] = {}

    def _counter_attr(self, event_type: str) -> str | None:
        """Return the counter attribute name for a given event type."""
        mapping = {
            "LEVEL": "levels_total",
            "LOOT": "loot_events_total",
            "DEATH": "deaths_total",
            "PET": "pets_total",
            "QUEST": "quests_total",
            "COMBAT_ACHIEVEMENT": "combat_tasks_total",
            "ACHIEVEMENT_DIARY": "diaries_total",
        }
        return mapping.get(event_type)

    def _update_detail_sensors(
        self, event_type: str, data: dict[str, Any]
    ) -> None:
        """Extract detail sensor entries from parsed event data."""
        now = datetime.now(timezone.utc).isoformat()

        if event_type == "LEVEL":
            # Store each levelled skill as its own sensor
            for skill, level in data.get("levelledSkills", {}).items():
                key = skill
                self.detail_sensors[key] = {
                    "value": level,
                    "attributes": {"skill": skill},
                    "last_update": now,
                }
            # Store combat level
            if "combatLevel" in data:
                self.detail_sensors["Combat Level"] = {
                    "value": data["combatLevel"],
                    "attributes": {
                        "increased": data.get("combatLevelIncreased", False),
                    },
                    "last_update": now,
                }

        elif event_type == "LOOT":
            source = data.get("source", "Unknown")
            key = f"Loot - {source}"
            self.detail_sensors[key] = {
                "value": data.get("totalValue", 0),
                "attributes": {
                    "source": source,
                    "items": data.get("items", []),
                    "totalValue": data.get("totalValue", 0),
                    "category": data.get("category"),
                    "killCount": data.get("killCount"),
                },
                "last_update": now,
            }

        elif event_type == "DEATH":
            killer = data.get("killerName", "Unknown")
            key = f"Death - {killer}"
            self.detail_sensors[key] = {
                "value": data.get("valueLost", 0),
                "attributes": {
                    "killerName": killer,
                    "valueLost": data.get("valueLost", 0),
                    "isPvp": data.get("isPvp", False),
                },
                "last_update": now,
            }

        elif event_type == "PET":
            pet_name = data.get("petName") or "Unknown"
            key = f"Pet - {pet_name}"
            self.detail_sensors[key] = {
                "value": pet_name,
                "attributes": {
                    "petName": pet_name,
                    "duplicate": data.get("duplicate", False),
                    "milestone": data.get("milestone"),
                },
                "last_update": now,
            }

        elif event_type == "QUEST":
            quest_name = data.get("questName", "Unknown")
            key = f"Quest - {quest_name}"
            self.detail_sensors[key] = {
                "value": quest_name,
                "attributes": {
                    "questName": quest_name,
                    "completedQuests": data.get("completedQuests"),
                    "totalQuests": data.get("totalQuests"),
                    "questPoints": data.get("questPoints"),
                    "totalQuestPoints": data.get("totalQuestPoints"),
                },
                "last_update": now,
            }

        elif event_type == "COMBAT_ACHIEVEMENT":
            task = data.get("task", "Unknown")
            key = f"Combat Achievement - {task}"
            self.detail_sensors[key] = {
                "value": task,
                "attributes": {
                    "tier": data.get("tier"),
                    "task": task,
                    "taskPoints": data.get("taskPoints"),
                    "totalPoints": data.get("totalPoints"),
                    "currentTier": data.get("currentTier"),
                    "justCompletedTier": data.get("justCompletedTier"),
                },
                "last_update": now,
            }

        elif event_type == "ACHIEVEMENT_DIARY":
            area = data.get("area", "Unknown")
            key = f"Achievement Diary - {area}"
            self.detail_sensors[key] = {
                "value": data.get("difficulty", "Unknown"),
                "attributes": {
                    "area": area,
                    "difficulty": data.get("difficulty"),
                    "total": data.get("total"),
                    "tasksCompleted": data.get("tasksCompleted"),
                    "tasksTotal": data.get("tasksTotal"),
                    "areaTasksCompleted": data.get("areaTasksCompleted"),
                    "areaTasksTotal": data.get("areaTasksTotal"),
                },
                "last_update": now,
            }

    def record_event(
        self,
        event_type: str,
        summary: str,
        data: dict[str, Any],
        player_name: str | None = None,
    ) -> None:
        """Record a parsed event, incrementing the right counter."""
        attr = self._counter_attr(event_type)
        if attr:
            setattr(self, attr, getattr(self, attr) + 1)

        if player_name:
            self.player_name = player_name

        self.last_event_type = event_type
        self.last_event_summary = summary
        self.last_event_data = data
        self.last_update = datetime.now(timezone.utc).isoformat()

        self._update_detail_sensors(event_type, data)


class AccountStore:
    """In-memory store keyed by dinkAccountHash (fallback: playerName)."""

    def __init__(self) -> None:
        self._by_hash: dict[str, AccountState] = {}
        self._by_name: dict[str, AccountState] = {}

    def get_or_create(
        self, account_hash: str | None, player_name: str
    ) -> AccountState:
        """Look up an account by hash (preferred) or normalized name."""
        if account_hash:
            state = self._by_hash.get(account_hash)
            if state is not None:
                return state

        norm = _normalize_player_name(player_name)
        if norm in self._by_name:
            state = self._by_name[norm]
            # Upgrade: if we now have a hash, index by it too
            if account_hash and account_hash not in self._by_hash:
                self._by_hash[account_hash] = state
                state.account_hash = account_hash
            return state

        # Brand-new account
        key = account_hash or norm
        state = AccountState(account_hash=key, player_name=player_name)
        if account_hash:
            self._by_hash[account_hash] = state
        self._by_name[norm] = state
        return state

    def get_by_hash(self, account_hash: str) -> AccountState | None:
        """Look up an account by its hash directly."""
        state = self._by_hash.get(account_hash)
        if state is not None:
            return state
        # Fallback: check if the hash is a normalized-name key
        return self._by_name.get(account_hash)

    @property
    def accounts(self) -> list[AccountState]:
        """Return all known account states (deduplicated)."""
        seen: set[int] = set()
        result: list[AccountState] = []
        for state in list(self._by_hash.values()) + list(self._by_name.values()):
            if id(state) not in seen:
                seen.add(id(state))
                result.append(state)
        return result
