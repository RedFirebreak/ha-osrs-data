"""In-memory multi-account state store for OSRS Data."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def _normalize_player_name(name: str) -> str:
    """Normalize an RSN to a stable key (lowercase, collapse whitespace)."""
    return re.sub(r"\s+", " ", name.strip().lower())


class AccountState:
    """Per-account player state and detail sensors."""

    def __init__(self, account_hash: str, player_name: str) -> None:
        self.account_hash: str = account_hash
        self.player_name: str = player_name
        self.account_type: str | None = None
        self.world: str | None = None

        # Skills: {skill_name: {"xp": ..., "level": ...}}
        self.skills: dict[str, dict[str, Any]] = {}

        # Inventory: list of item dicts (max 28 slots)
        self.inventory: list[dict[str, Any]] = []

        # Equipment: {slot: item_dict or {}}
        self.equipment: dict[str, dict[str, Any]] = {}

        # Health: {current: int, max: int}
        self.health: dict[str, int] = {"current": 0, "max": 0}

        # Prayer: {current: int, max: int}
        self.prayer: dict[str, int] = {"current": 0, "max": 0}

        # Events: list (future use, initially empty)
        self.events: list[Any] = []

        # Detail sensors: key → {value, attributes, last_update}
        self.detail_sensors: dict[str, dict[str, Any]] = {}

        self.last_update: str | None = None

    def update_player_data(
        self,
        parsed: dict[str, Any],
        player_name: str | None = None,
    ) -> None:
        """Update from parsed base JSON player data."""
        if player_name:
            self.player_name = player_name

        now = datetime.now(timezone.utc).isoformat()
        self.last_update = now

        self.account_type = parsed.get("accountType", self.account_type)
        self.world = parsed.get("world", self.world)
        self.events = parsed.get("events", [])
        self.inventory = parsed.get("inventory", [])
        self.equipment = parsed.get("equipment", {})
        self.health = parsed.get("health", {"current": 0, "max": 0})
        self.prayer = parsed.get("prayer", {"current": 0, "max": 0})

        # Update skills and detail sensors
        new_skills = parsed.get("skills", {})
        for skill_name, skill_data in new_skills.items():
            new_xp = skill_data.get("xp", 0)
            new_level = skill_data.get("level", 1)
            old = self.skills.get(skill_name, {})

            if (
                old.get("xp") != new_xp
                or old.get("level") != new_level
                or skill_name not in self.skills
            ):
                self.detail_sensors[f"{skill_name} XP"] = {
                    "value": new_xp,
                    "attributes": {"skill": skill_name},
                    "last_update": now,
                }
                self.detail_sensors[f"{skill_name} Level"] = {
                    "value": new_level,
                    "attributes": {"skill": skill_name},
                    "last_update": now,
                }

            self.skills[skill_name] = {"xp": new_xp, "level": new_level}

    def to_dict(self) -> dict[str, Any]:
        """Serialize the account state to a dict for persistence."""
        return {
            "account_hash": self.account_hash,
            "player_name": self.player_name,
            "account_type": self.account_type,
            "world": self.world,
            "skills": self.skills,
            "inventory": self.inventory,
            "equipment": self.equipment,
            "health": self.health,
            "prayer": self.prayer,
            "events": self.events,
            "detail_sensors": self.detail_sensors,
            "last_update": self.last_update,
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        """Restore the account state from a persisted dict."""
        self.player_name = data.get("player_name", self.player_name)
        self.account_type = data.get("account_type")
        self.world = data.get("world")
        self.skills = data.get("skills", {})
        self.inventory = data.get("inventory", [])
        self.equipment = data.get("equipment", {})
        self.health = data.get("health", {"current": 0, "max": 0})
        self.prayer = data.get("prayer", {"current": 0, "max": 0})
        self.events = data.get("events", [])
        self.detail_sensors = data.get("detail_sensors", {})
        self.last_update = data.get("last_update")


class AccountStore:
    """In-memory store keyed by account identifier (fallback: playerName)."""

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

    def to_dict(self) -> list[dict[str, Any]]:
        """Serialize all account states for persistence."""
        return [acct.to_dict() for acct in self.accounts]

    def load_dict(self, data: list[dict[str, Any]]) -> None:
        """Restore account states from persisted data."""
        for acct_data in data:
            account_hash = acct_data.get("account_hash", "")
            player_name = acct_data.get("player_name", "Unknown")
            state = self.get_or_create(account_hash, player_name)
            state.load_dict(acct_data)
