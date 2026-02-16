"""In-memory multi-account state store for OSRS Data."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def _normalize_player_name(name: str) -> str:
    """Normalize an RSN to a stable key (lowercase, collapse whitespace)."""
    return re.sub(r"\s+", " ", name.strip().lower())


class AccountState:
    """Per-account event details and detail sensors."""

    # Event types that get their own "Last <Type>" sensor
    TYPED_EVENT_TYPES: tuple[str, ...] = (
        "LOOT",
        "DEATH",
        "PET",
        "QUEST",
        "COMBAT_ACHIEVEMENT",
        "ACHIEVEMENT_DIARY",
        "COLLECTION",
    )

    def __init__(self, account_hash: str, player_name: str) -> None:
        self.account_hash: str = account_hash
        self.player_name: str = player_name

        # Last event (any type)
        self.last_event_type: str | None = None
        self.last_event_summary: str | None = None
        self.last_event_data: dict[str, Any] = {}
        self.last_update: str | None = None

        # Per-type last event: type → {summary, data, last_update}
        self.last_typed_events: dict[str, dict[str, Any]] = {}

        # Detail sensors: key → {value, attributes, last_update}
        # Only LEVEL events produce detail sensors (per-skill + combat level)
        self.detail_sensors: dict[str, dict[str, Any]] = {}

    def _update_detail_sensors(
        self, event_type: str, data: dict[str, Any]
    ) -> None:
        """Extract detail sensor entries from parsed event data.

        Only LEVEL events produce detail sensors (individual skills and
        combat level).  All other event types use per-type last-event
        sensors instead.
        """
        if event_type != "LEVEL":
            return

        now = datetime.now(timezone.utc).isoformat()

        # Update all skills from the allSkills snapshot (full refresh)
        for skill, level in data.get("allSkills", {}).items():
            self.detail_sensors[skill] = {
                "value": level,
                "attributes": {"skill": skill},
                "last_update": now,
            }

        # Overlay levelled skills (may have the same values, but ensures
        # freshly-levelled skills are always present even without allSkills)
        for skill, level in data.get("levelledSkills", {}).items():
            self.detail_sensors[skill] = {
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

    def record_event(
        self,
        event_type: str,
        summary: str,
        data: dict[str, Any],
        player_name: str | None = None,
    ) -> None:
        """Record a parsed event and update detail sensors."""
        if player_name:
            self.player_name = player_name

        now = datetime.now(timezone.utc).isoformat()

        self.last_event_type = event_type
        self.last_event_summary = summary
        self.last_event_data = data
        self.last_update = now

        # Update per-type last event
        if event_type in self.TYPED_EVENT_TYPES:
            self.last_typed_events[event_type] = {
                "summary": summary,
                "data": data,
                "last_update": now,
            }

        self._update_detail_sensors(event_type, data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the account state to a dict for persistence."""
        return {
            "account_hash": self.account_hash,
            "player_name": self.player_name,
            "last_event_type": self.last_event_type,
            "last_event_summary": self.last_event_summary,
            "last_event_data": self.last_event_data,
            "last_update": self.last_update,
            "last_typed_events": self.last_typed_events,
            "detail_sensors": self.detail_sensors,
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        """Restore the account state from a persisted dict."""
        self.player_name = data.get("player_name", self.player_name)
        self.last_event_type = data.get("last_event_type")
        self.last_event_summary = data.get("last_event_summary")
        self.last_event_data = data.get("last_event_data", {})
        self.last_update = data.get("last_update")
        self.last_typed_events = data.get("last_typed_events", {})
        self.detail_sensors = data.get("detail_sensors", {})


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
