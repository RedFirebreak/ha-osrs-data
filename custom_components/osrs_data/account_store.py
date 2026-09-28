"""In-memory multi-account state store for OSRS Data."""

from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Import tick constants for timeout calculation
from .const import (
    NON_MAIN_WORLD_TYPES,
    PRESENCE_TIMEOUT,
    TICK_DURATION,
    TICK_TIMEOUT_MULTIPLIER,
)


_MAX_PREVIOUS_NAMES = 10

# Snapshot sections (parsed key -> AccountState attribute).  The plugin's
# per-connection filters can leave any of them out; a missing section
# keeps its last known value.
SNAPSHOT_SECTIONS: dict[str, str] = {
    "inventory": "inventory",
    "equipment": "equipment",
    "health": "health",
    "prayerPoints": "prayer_points",
    "location": "location",
    "spellbook": "spellbook",
}


def _normalize_player_name(name: str) -> str:
    """Normalize an RSN to a stable key (lowercase, collapse whitespace)."""
    return re.sub(r"\s+", " ", name.strip().lower())


def _as_epoch_ms(value: Any) -> int | None:
    """Return *value* as positive epoch millis, or None if it isn't one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return int(value)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _snapshot_ts(value: Any) -> int | None:
    """Return a payload ``timestamp`` as epoch millis, clamped to now.

    The timestamp comes from the player's PC clock.  Clamping keeps a
    clock that runs ahead from storing a future time that would make
    every later snapshot look stale.
    """
    ts = _as_epoch_ms(value)
    if ts is None:
        return None
    return min(ts, _now_ms())


def _level_from_xp(xp: int) -> int:
    """Return the real (unboosted) skill level for a given total XP.

    Uses the standard OSRS experience formula, capped at level 99.
    Deriving levels from XP is exactly how the game computes total and
    combat level, so it is immune to boosted / virtual "levels" that a
    client may report in the ``level`` field.
    """
    if not xp or xp <= 0:
        return 1
    points = 0
    for level in range(1, 99):  # thresholds for levels 2..99
        points += math.floor(level + 300 * (2 ** (level / 7.0)))
        if math.floor(points / 4) > xp:
            return level
    return 99


class AccountState:
    """Per-account player state and detail sensors."""

    def __init__(
        self,
        account_hash: str,
        player_name: str,
        presence_timeout: float = PRESENCE_TIMEOUT,
    ) -> None:
        # Immutable entity key: basis for device identifiers and entity
        # unique_ids.  Never reassigned after creation.
        self.account_hash: str = account_hash
        self.player_name: str = player_name
        # Stable plugin-provided account hash (salted SHA-224 hex).  Used
        # only as a lookup alias so display-name changes resolve to the
        # same account; it never replaces ``account_hash``.
        self.plugin_account_hash: str | None = None
        # Earlier display names (most recent last), capped.
        self.previous_names: list[str] = []
        self.account_type: str | None = None
        self.world: str | None = None
        # World types of the current world (e.g. MEMBERS, SEASONAL)
        self.world_types: list[str] = []

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

        # SNAPSHOT_SECTIONS keys that the latest applied snapshot contained
        self.received_sections: set[str] = set()

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
        self.last_collection_log: dict[str, Any] = {}

        # Plugin version from the X-Osrs-Exporter-Version header
        self.plugin_version: str | None = None

        # Root ``timestamp`` (epoch ms, clamped to receive time) of the last
        # applied snapshot.
        self.last_payload_ts: int | None = None

        # Newest applied snapshot timestamp per paired device (device_id ->
        # epoch ms).  The plugin can resend queued payloads late; older ones
        # are not applied.  PC clocks differ, so a snapshot is only compared
        # with snapshots from the same device.
        self.device_payload_ts: dict[str, int] = {}

    def is_stale(self, payload_ts: Any, device_id: str | None = None) -> bool:
        """Return True if *payload_ts* is older than *device_id*'s last snapshot."""
        ts = _snapshot_ts(payload_ts)
        last = self.device_payload_ts.get(device_id or "")
        return ts is not None and last is not None and ts < last

    def mark_seen(self) -> None:
        """Record that this account's client is sending data.

        Called for every authenticated payload, including stale resends
        whose snapshot is skipped, so presence never times out while data
        is still arriving.  An explicit logout is not undone.
        """
        self.last_seen = datetime.now(timezone.utc)
        if not self.is_online and self.offline_reason == "timeout":
            self.is_online = True
            self.offline_reason = "online"

    def update_player_data(
        self,
        parsed: dict[str, Any],
        player_name: str | None = None,
        device_id: str | None = None,
    ) -> None:
        """Update from parsed base JSON player data."""
        if player_name:
            self._set_player_name(player_name)

        now = datetime.now(timezone.utc).isoformat()
        self.last_update = now
        self.last_seen = datetime.now(timezone.utc)

        payload_ts = _snapshot_ts(parsed.get("timestamp"))
        if payload_ts is not None:
            self.last_payload_ts = payload_ts
            key = device_id or ""
            self.device_payload_ts[key] = max(
                payload_ts, self.device_payload_ts.get(key, payload_ts)
            )

        self.account_type = parsed.get("accountType", self.account_type)
        self.world = parsed.get("world", self.world)
        self.world_types = parsed.get("worldTypes") or []
        self.events = parsed.get("events", [])

        # Update tick delay if provided in this payload
        new_tick_delay = parsed.get("tickDelay")
        if new_tick_delay is not None:
            self.tick_delay = new_tick_delay

        # Update game state
        self.game_state = parsed.get("state", "UNKNOWN")

        # A section the plugin left out keeps its last known value.
        self.received_sections = set()
        for section, attr in SNAPSHOT_SECTIONS.items():
            value = parsed.get(section)
            if value is not None:
                setattr(self, attr, value)
                self.received_sections.add(section)

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

        # Update skills and detail sensors — skipped on Leagues/DMM/etc.
        # worlds so their separate stats don't overwrite main-game values.
        if NON_MAIN_WORLD_TYPES.intersection(self.world_types):
            return
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

    def _set_player_name(self, player_name: str) -> None:
        """Set the display name, remembering the old one on a real rename."""
        old = self.player_name
        if old and _normalize_player_name(old) != _normalize_player_name(player_name):
            if old in self.previous_names:
                self.previous_names.remove(old)
            self.previous_names.append(old)
            del self.previous_names[:-_MAX_PREVIOUS_NAMES]
        self.player_name = player_name

    def record_event(self, event_type: str, occurred_at: str | None = None) -> None:
        """Increment the counter for *event_type* and update last_fired."""
        now = occurred_at or datetime.now(timezone.utc).isoformat()
        entry = self.event_totals.get(event_type)
        if entry is None:
            self.event_totals[event_type] = {"count": 1, "last_fired": now}
        else:
            entry["count"] = entry.get("count", 0) + 1
            entry["last_fired"] = now

    def record_game_event(
        self,
        event_type: str,
        data: dict[str, Any],
        occurred_at: str | None = None,
    ) -> None:
        """Record a game event: bump its counter and stash the rich payload.

        DEATH/LOOT/PKLOOT/COLLECTIONLOG payloads are stored (with a
        timestamp) so the corresponding "Last …" sensors can surface
        killer, value lost, loot total, etc.  All event types still bump
        the counter.  *occurred_at* is when the event happened in game
        (the plugin's event timestamp); defaults to now.
        """
        occurred_at = occurred_at or datetime.now(timezone.utc).isoformat()
        self.record_event(event_type, occurred_at)
        if not isinstance(data, dict):
            return
        stamped = {**data, "timestamp": occurred_at}
        if event_type == "DEATH":
            self.last_death = stamped
        elif event_type in ("LOOT", "PKLOOT"):
            self.last_loot = stamped
        elif event_type == "COLLECTIONLOG":
            self.last_collection_log = stamped

    # ── Computed aggregates ─────────────────────────────────────────

    @property
    def total_level(self) -> int:
        """Sum of all real skill levels (derived from XP, to match the game)."""
        return sum(_level_from_xp(skill.get("xp", 0)) for skill in self.skills.values())

    @property
    def total_xp(self) -> int:
        """Sum of all skill XP."""
        return sum(skill.get("xp", 0) for skill in self.skills.values())

    @property
    def combat_level(self) -> int | None:
        """OSRS combat level from real combat skill levels.

        Levels are derived from XP so the result matches the game exactly
        (boosted / virtual levels reported in the ``level`` field are
        ignored).  Returns ``None`` until any skill data has arrived.
        """
        if not self.skills:
            return None

        def lvl(name: str) -> int:
            skill = self.skills.get(name)
            if not skill:
                return 1
            return _level_from_xp(skill.get("xp", 0))

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
            "plugin_account_hash": self.plugin_account_hash,
            "player_name": self.player_name,
            "previous_names": self.previous_names,
            "account_type": self.account_type,
            "world": self.world,
            "world_types": self.world_types,
            "skills": self.skills,
            "inventory": self.inventory,
            "equipment": self.equipment,
            "health": self.health,
            "prayerPoints": self.prayer_points,
            "location": self.location,
            "spellbook": self.spellbook,
            "received_sections": sorted(self.received_sections),
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
            "last_collection_log": self.last_collection_log,
            "plugin_version": self.plugin_version,
            "last_payload_ts": self.last_payload_ts,
            "device_payload_ts": self.device_payload_ts,
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        """Restore the account state from a persisted dict."""
        self.player_name = data.get("player_name", self.player_name)
        self.plugin_account_hash = data.get("plugin_account_hash")
        self.previous_names = data.get("previous_names", [])
        self.account_type = data.get("account_type")
        self.world = data.get("world")
        self.world_types = data.get("world_types", [])
        self.skills = data.get("skills", {})
        self.inventory = data.get("inventory", [])
        self.equipment = data.get("equipment", {})
        self.health = data.get("health", {"current": 0, "max": 0})
        self.prayer_points = data.get("prayerPoints", {"current": 0, "max": 0})
        self.location = data.get("location", {"x": 0, "y": 0, "plane": 0})
        self.spellbook = data.get("spellbook", {"id": 0, "name": ""})
        received = data.get("received_sections")
        # Older versions replaced every section on each snapshot.
        self.received_sections = (
            {s for s in received if s in SNAPSHOT_SECTIONS}
            if isinstance(received, list)
            else set(SNAPSHOT_SECTIONS)
        )
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
        self.last_collection_log = data.get("last_collection_log", {})
        self.plugin_version = data.get("plugin_version")
        # Older versions stored the timestamp unclamped; drop any future
        # value so a PC clock that ran ahead can't block snapshots.
        now_ms = _now_ms()
        last_ts = _as_epoch_ms(data.get("last_payload_ts"))
        self.last_payload_ts = last_ts if last_ts is not None and last_ts <= now_ms else None
        self.device_payload_ts = {}
        raw_device_ts = data.get("device_payload_ts")
        if isinstance(raw_device_ts, dict):
            for device_id, raw_ts in raw_device_ts.items():
                ts = _as_epoch_ms(raw_ts)
                if isinstance(device_id, str) and ts is not None and ts <= now_ms:
                    self.device_payload_ts[device_id] = ts


class AccountStore:
    """In-memory store of account states.

    Each state has an immutable *key* (``AccountState.account_hash``) that
    entity unique_ids and device identifiers are built from.  States are
    found by key, by the plugin's stable ``accountHash`` alias, or by the
    normalized display name.

    Keys are never rewritten: accounts first seen by name keep the
    normalized name as their key even after the plugin starts sending an
    ``accountHash``, so existing entities are never re-keyed.  Accounts
    first seen *with* a hash use it as their key.
    """

    def __init__(self, presence_timeout: float = PRESENCE_TIMEOUT) -> None:
        self._by_key: dict[str, AccountState] = {}
        self._by_name: dict[str, AccountState] = {}
        self._by_plugin_hash: dict[str, AccountState] = {}
        self._presence_timeout = presence_timeout

    def get_or_create(
        self,
        account_hash: str | None,
        player_name: str,
        plugin_hash: str | None = None,
    ) -> AccountState:
        """Look up (or create) an account.

        *account_hash* is an explicit entity key (e.g. from persistence).
        *plugin_hash* is the plugin-provided stable account hash; it is
        matched first so a renamed account resolves to its existing state.
        """
        norm = _normalize_player_name(player_name)

        if account_hash and account_hash in self._by_key:
            return self._by_key[account_hash]

        if plugin_hash:
            state = self._by_plugin_hash.get(plugin_hash)
            if state is not None:
                # No name indexing here: the payload may be a late resend
                # that is never applied.  The display name (and so the
                # name lookup) only changes when a snapshot is applied.
                return state

        state = self._find_by_name(norm)
        if state is not None:
            if plugin_hash:
                if state.plugin_account_hash is None:
                    # Legacy name-keyed account: bind the alias, keep the key.
                    state.plugin_account_hash = plugin_hash
                    self._by_plugin_hash[plugin_hash] = state
                    return state
                # Name is bound to a different account (name was reused
                # after a name change) -- fall through and create a new one.
            else:
                if account_hash:
                    # Extra key alias only; the state's own key is kept.
                    self._by_key[account_hash] = state
                return state

        # Brand-new account.  The name-based key may already belong to an
        # account that has since been renamed; suffix it so unique_ids
        # never collide.
        key = self._unused_key(plugin_hash or account_hash or norm)
        state = AccountState(
            account_hash=key,
            player_name=player_name,
            presence_timeout=self._presence_timeout,
        )
        self._by_key[key] = state
        self._by_name[norm] = state
        if plugin_hash:
            state.plugin_account_hash = plugin_hash
            self._by_plugin_hash[plugin_hash] = state
        return state

    def _unused_key(self, base: str) -> str:
        """Return *base*, or *base* with a numeric suffix if it's taken."""
        key = base
        n = 2
        while key in self._by_key:
            key = f"{base}_{n}"
            n += 1
        return key

    def find_by_name(self, player_name: str) -> AccountState | None:
        """Return the account currently named *player_name*, if any."""
        return self._find_by_name(_normalize_player_name(player_name))

    def _find_by_name(self, norm: str) -> AccountState | None:
        """Return the account whose *current* display name is *norm*.

        ``_by_name`` is only a cache: an entry for an account that has
        since been renamed is ignored, so lookups always follow the names
        of applied snapshots.  If two accounts share a name, the cached
        (most recently created or loaded) one wins.
        """
        state = self._by_name.get(norm)
        if state is not None and _normalize_player_name(state.player_name) == norm:
            return state
        for state in self.accounts:
            if _normalize_player_name(state.player_name) == norm:
                self._by_name[norm] = state
                return state
        self._by_name.pop(norm, None)
        return None

    def get_by_hash(self, account_hash: str) -> AccountState | None:
        """Look up an account by its entity key."""
        state = self._by_key.get(account_hash)
        if state is not None:
            return state
        # Fallback: check if the key is a normalized-name key
        return self._find_by_name(account_hash)

    @property
    def accounts(self) -> list[AccountState]:
        """Return all known account states (deduplicated)."""
        seen: set[int] = set()
        result: list[AccountState] = []
        for state in self._by_key.values():
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
            player_name = acct_data.get("player_name", "Unknown")
            key = acct_data.get("account_hash") or _normalize_player_name(player_name)
            state = self._by_key.get(key)
            if state is None:
                state = AccountState(
                    account_hash=key,
                    player_name=player_name,
                    presence_timeout=self._presence_timeout,
                )
                self._by_key[key] = state
            state.load_dict(acct_data)
            self._by_name[_normalize_player_name(state.player_name)] = state
            if state.plugin_account_hash:
                self._by_plugin_hash[state.plugin_account_hash] = state
