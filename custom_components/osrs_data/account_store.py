"""In-memory multi-account state store for OSRS Data."""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Import tick constants for timeout calculation
from .const import PRESENCE_TIMEOUT, TICK_DURATION, TICK_TIMEOUT_MULTIPLIER


def _normalize_player_name(name: str) -> str:
    """Normalize an RSN to a stable key (lowercase, collapse whitespace)."""
    return re.sub(r"\s+", " ", name.strip().lower())


class AccountState:
    """Per-account player state and detail sensors."""

    def __init__(
        self,
        account_hash: str,
        player_name: str,
        presence_timeout: float = PRESENCE_TIMEOUT,
    ) -> None:
        self.account_hash: str = account_hash
        self.player_name: str = player_name
        self.account_type: str | None = None
        self.world: str | None = None

        # Fallback presence timeout (seconds) used when no tickDelay known.
        self._presence_timeout_fallback: float = presence_timeout

        # Skills: {skill_name: {"xp": ..., "level": ...}}
        self.skills: dict[str, dict[str, Any]] = {}

        # Inventory: list of item dicts (max 28 slots)
        self.inventory: list[dict[str, Any]] = []

        # Equipment: {slot: item_dict or {}}
        self.equipment: dict[str, dict[str, Any]] = {}

        # Health: {current: int, max: int}
        self.health: dict[str, int] = {"current": 0, "max": 0}

        # Prayer Points: {current: int, max: int}
        self.prayer_points: dict[str, int] = {"current": 0, "max": 0}

        # Location: {x: int, y: int, plane: int}
        self.location: dict[str, int] = {"x": 0, "y": 0, "plane": 0}

        # Spellbook: {id: int, name: str}
        self.spellbook: dict[str, Any] = {"id": 0, "name": ""}

        # Events: list (future use, initially empty)
        self.events: list[Any] = []

        # Game state: current RuneLite client state (e.g. LOGGED_IN)
        self.game_state: str = "UNKNOWN"

        # Detail sensors: key → {value, attributes, last_update}
        self.detail_sensors: dict[str, dict[str, Any]] = {}

        self.last_update: str | None = None

        # Presence tracking
        self.last_seen: datetime | None = None
        self.is_online: bool = False
        self.offline_reason: str | None = None

        # Tick-based dynamic timeout (set from tickDelay in payload)
        self.tick_delay: int | None = None

        # Event totals: {event_type: {"count": int, "last_fired": iso_str}}
        self.event_totals: dict[str, dict[str, Any]] = {}

        # Most recent rich event payloads (data + timestamp), empty until seen
        self.last_death: dict[str, Any] = {}
        self.last_loot: dict[str, Any] = {}

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
        self.last_seen = datetime.now(timezone.utc)

        self.account_type = parsed.get("accountType", self.account_type)
        self.world = parsed.get("world", self.world)
        self.events = parsed.get("events", [])

        # Update tick delay if provided in this payload
        new_tick_delay = parsed.get("tickDelay")
        if new_tick_delay is not None:
            self.tick_delay = new_tick_delay

        # Update game state
        self.game_state = parsed.get("state", "UNKNOWN")

        self.inventory = parsed.get("inventory", [])
        self.equipment = parsed.get("equipment", {})
        self.health = parsed.get("health", {"current": 0, "max": 0})
        self.prayer_points = parsed.get("prayerPoints", {"current": 0, "max": 0})
        self.location = parsed.get("location", {"x": 0, "y": 0, "plane": 0})
        self.spellbook = parsed.get("spellbook", {"id": 0, "name": ""})

        # Determine presence: default to online (heartbeat), then let
        # events override.  This block runs BEFORE skill processing so
        # an exception in skill parsing can never prevent a shutdown /
        # logout event from being honoured.
        self.is_online = True
        self.offline_reason = "online"

        for event in self.events:
            if isinstance(event, dict):
                etype = event.get("type", "")
                etype_upper = etype.upper()
                if etype_upper == "LOGOUT":
                    self.is_online = False
                    self.offline_reason = "logout"
                    _LOGGER.debug(
                        "Account %s marked offline (logout event)",
                        self.player_name,
                    )
                elif etype_upper == "CLIENTSHUTDOWN":
                    self.is_online = False
                    self.offline_reason = event.get("data", "shutdown")
                    _LOGGER.debug(
                        "Account %s marked offline (ClientShutdown: %s)",
                        self.player_name,
                        self.offline_reason,
                    )
                elif etype_upper == "LOGIN":
                    self.is_online = True
                    self.offline_reason = "online"

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
                self.detail_sensors[skill_name] = {
                    "value": new_level,
                    "attributes": {"xp": new_xp},
                    "last_update": now,
                }

            self.skills[skill_name] = {"xp": new_xp, "level": new_level}

    def record_event(self, event_type: str) -> None:
        """Increment the counter for *event_type* and update last_fired."""
        now = datetime.now(timezone.utc).isoformat()
        entry = self.event_totals.get(event_type)
        if entry is None:
            self.event_totals[event_type] = {"count": 1, "last_fired": now}
        else:
            entry["count"] = entry.get("count", 0) + 1
            entry["last_fired"] = now

    def record_game_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Record a game event: bump its counter and stash the rich payload.

        DEATH/LOOT/PKLOOT payloads are stored (with a timestamp) so the
        corresponding "Last …" sensors can surface killer, value lost,
        loot total, etc.  All event types still bump the counter.
        """
        self.record_event(event_type)
        if not isinstance(data, dict):
            return
        stamped = {**data, "timestamp": datetime.now(timezone.utc).isoformat()}
        if event_type == "DEATH":
            self.last_death = stamped
        elif event_type in ("LOOT", "PKLOOT"):
            self.last_loot = stamped

    # ── Computed aggregates ─────────────────────────────────────────

    @staticmethod
    def _item_value(item: dict[str, Any], price_key: str) -> int:
        """Value of a single item = unit price × quantity (0 if missing)."""
        if not isinstance(item, dict):
            return 0
        return int(item.get(price_key, 0) or 0) * int(item.get("quantity", 0) or 0)

    def inventory_value(self, price_key: str = "gePrice") -> int:
        """Total value of the inventory for *price_key* (gePrice/haPrice)."""
        return sum(self._item_value(item, price_key) for item in self.inventory)

    def equipment_value(self, price_key: str = "gePrice") -> int:
        """Total value of worn equipment for *price_key* (gePrice/haPrice)."""
        return sum(
            self._item_value(item, price_key)
            for item in self.equipment.values()
            if item
        )

    @property
    def total_level(self) -> int:
        """Sum of all skill levels."""
        return sum(skill.get("level", 0) for skill in self.skills.values())

    @property
    def total_xp(self) -> int:
        """Sum of all skill XP."""
        return sum(skill.get("xp", 0) for skill in self.skills.values())

    @property
    def combat_level(self) -> int | None:
        """OSRS combat level from combat skill levels.

        Returns ``None`` until the combat skills have been received.
        """
        if not self.skills:
            return None

        def lvl(name: str) -> int:
            return self.skills.get(name, {}).get("level", 1)

        base = 0.25 * (lvl("Defence") + lvl("Hitpoints") + math.floor(lvl("Prayer") / 2))
        melee = 0.325 * (lvl("Attack") + lvl("Strength"))
        ranged = 0.325 * math.floor(lvl("Ranged") * 3 / 2)
        magic = 0.325 * math.floor(lvl("Magic") * 3 / 2)
        return math.floor(base + max(melee, ranged, magic))

    @property
    def presence_timeout(self) -> float:
        """Compute the presence timeout in seconds.

        When ``tick_delay`` is known, returns
        ``floor(tick_delay * 1.5 * 0.6)``.
        Otherwise falls back to the global ``PRESENCE_TIMEOUT`` (25 min).
        """
        if self.tick_delay is not None and self.tick_delay > 0:
            return math.floor(
                self.tick_delay * TICK_TIMEOUT_MULTIPLIER * TICK_DURATION
            )
        return self._presence_timeout_fallback

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
            "prayerPoints": self.prayer_points,
            "location": self.location,
            "spellbook": self.spellbook,
            "events": self.events,
            "game_state": self.game_state,
            "detail_sensors": self.detail_sensors,
            "last_update": self.last_update,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_online": self.is_online,
            "offline_reason": self.offline_reason,
            "tick_delay": self.tick_delay,
            "event_totals": self.event_totals,
            "last_death": self.last_death,
            "last_loot": self.last_loot,
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
        self.prayer_points = data.get("prayerPoints", {"current": 0, "max": 0})
        self.location = data.get("location", {"x": 0, "y": 0, "plane": 0})
        self.spellbook = data.get("spellbook", {"id": 0, "name": ""})
        self.events = data.get("events", [])
        self.game_state = data.get("game_state", "UNKNOWN")
        self.detail_sensors = data.get("detail_sensors", {})
        self.last_update = data.get("last_update")

        # Presence tracking
        last_seen_raw = data.get("last_seen")
        if last_seen_raw:
            self.last_seen = datetime.fromisoformat(last_seen_raw)
        self.is_online = data.get("is_online", False)
        self.offline_reason = data.get("offline_reason")
        self.tick_delay = data.get("tick_delay")
        self.event_totals = data.get("event_totals", {})
        self.last_death = data.get("last_death", {})
        self.last_loot = data.get("last_loot", {})


class AccountStore:
    """In-memory store keyed by account identifier (fallback: playerName)."""

    def __init__(self, presence_timeout: float = PRESENCE_TIMEOUT) -> None:
        self._by_hash: dict[str, AccountState] = {}
        self._by_name: dict[str, AccountState] = {}
        self._presence_timeout = presence_timeout

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
        state = AccountState(
            account_hash=key,
            player_name=player_name,
            presence_timeout=self._presence_timeout,
        )
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
