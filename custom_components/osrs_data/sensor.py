"""Per-account sensor entities for the OSRS Data integration."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .account_store import AccountState
from .const import (
    DOMAIN,
    DATA_ACCOUNT_STORE,
    DATA_HISTORY_STORE,
    SIGNAL_ACCOUNT_UPDATED,
)
from .parser.base import EQUIPMENT_SLOTS

# Number of recent history entries surfaced on the "Last …" sensors.
_RECENT_HISTORY_LIMIT = 10

_LOGGER = logging.getLogger(__name__)


_MAX_SLUG_LENGTH = 48


def _slugify_account(account_hash: str) -> str:
    """Create a short, entity-safe slug from an account identifier."""
    return re.sub(r"[^a-z0-9]+", "_", account_hash.lower()).strip("_")[:_MAX_SLUG_LENGTH]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OSRS Data sensors from a config entry."""
    async_add_entities([OsrsStatusSensor(entry)])

    known_accounts: set[str] = set()
    known_detail_keys: dict[str, set[str]] = {}
    known_event_total_keys: dict[str, set[str]] = {}

    @callback
    def _handle_account_update(account_hash: str) -> None:
        """Create entities for a new account, or update existing ones."""
        store = hass.data[DOMAIN][entry.entry_id][DATA_ACCOUNT_STORE]
        state = store.get_by_hash(account_hash)
        if state is None:
            return

        slug = _slugify_account(account_hash)
        new_entities: list[SensorEntity] = []

        if account_hash not in known_accounts:
            known_accounts.add(account_hash)
            known_detail_keys[account_hash] = set()
            known_event_total_keys[account_hash] = set()

            new_entities.append(OsrsPlayerInfoSensor(entry, state, slug))
            new_entities.append(OsrsInventorySensor(entry, state, slug))
            new_entities.append(OsrsEquipmentSensor(entry, state, slug))
            new_entities.append(OsrsHealthSensor(entry, state, slug))
            new_entities.append(OsrsPrayerPointsSensor(entry, state, slug))
            new_entities.append(OsrsLocationSensor(entry, state, slug))
            new_entities.append(OsrsSpellbookSensor(entry, state, slug))
            new_entities.append(OsrsGameStateSensor(entry, state, slug))
            new_entities.append(OsrsTotalLevelSensor(entry, state, slug))
            new_entities.append(OsrsCombatLevelSensor(entry, state, slug))
            new_entities.append(OsrsLastDeathSensor(entry, state, slug))
            new_entities.append(OsrsLastLootSensor(entry, state, slug))

        # Create detail sensors for any new keys (skill xp & level)
        for key in state.detail_sensors:
            if key not in known_detail_keys[account_hash]:
                known_detail_keys[account_hash].add(key)
                new_entities.append(
                    OsrsAccountDetailSensor(entry, state, slug, key)
                )

        # Create event total sensors for any new event types
        for ev_key in state.event_totals:
            if ev_key not in known_event_total_keys[account_hash]:
                known_event_total_keys[account_hash].add(ev_key)
                new_entities.append(
                    OsrsEventTotalSensor(entry, state, slug, ev_key)
                )

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ACCOUNT_UPDATED, _handle_account_update)
    )


# ── Status sensor ──────────────────────────────────────────────────


class OsrsStatusSensor(SensorEntity):
    """Simple status sensor for the integration."""

    _attr_has_entity_name = True
    _attr_name = "Status"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_native_value = "ready"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return API endpoints for setup."""
        return {
            "events_endpoint": "/api/osrs-data/events",
            "pair_endpoint": "/api/osrs-data/pair",
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OSRS Data",
            "manufacturer": "Custom",
            "model": "Event Receiver",
        }


# ── Per-account device helpers ──────────────────────────────────────


def _account_device_info(entry: ConfigEntry, state: AccountState) -> dict[str, Any]:
    """Build device_info for a per-account device."""
    return {
        "identifiers": {(DOMAIN, state.account_hash)},
        "name": f"OSRS {state.player_name}",
        "manufacturer": "RuneLite",
        "model": "OSRS Account",
        "via_device": (DOMAIN, entry.entry_id),
    }


# ── Player info sensor ──────────────────────────────────────────────


class OsrsPlayerInfoSensor(SensorEntity):
    """Sensor whose state is the player name, attributes hold account info."""

    _attr_has_entity_name = True
    _attr_name = "Player Info"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_player_info"

    @property
    def native_value(self) -> str | None:
        return self._state.player_name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._state.account_type:
            attrs["account_type"] = self._state.account_type
        if self._state.world is not None:
            attrs["world"] = self._state.world
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        if self._state.events:
            attrs["events"] = self._state.events
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Inventory sensor ────────────────────────────────────────────────


class OsrsInventorySensor(SensorEntity):
    """Single sensor whose attributes hold the entire inventory dump."""

    _attr_has_entity_name = True
    _attr_name = "Inventory"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_inventory"

    @property
    def native_value(self) -> int:
        """Number of occupied inventory slots."""
        return len(self._state.inventory)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "items": self._state.inventory,
            "slots_used": len(self._state.inventory),
            "slots_total": 28,
        }
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Spellbook sensor ─────────────────────────────────────────────────


class OsrsSpellbookSensor(SensorEntity):
    """Sensor whose state is the spellbook name, attribute holds the id."""

    _attr_has_entity_name = True
    _attr_name = "Spellbook"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_spellbook"

    @property
    def native_value(self) -> str:
        """Active spellbook name."""
        return self._state.spellbook.get("name", "")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "id": self._state.spellbook.get("id", 0),
        }
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Location sensor ──────────────────────────────────────────────────


class OsrsLocationSensor(SensorEntity):
    """Sensor whose state is the tile coordinates, attributes hold x/y/plane."""

    _attr_has_entity_name = True
    _attr_name = "Location"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_location"

    @property
    def native_value(self) -> str:
        """Tile coordinates as 'x, y'."""
        loc = self._state.location
        return f"{loc.get('x', 0)}, {loc.get('y', 0)}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        loc = self._state.location
        attrs: dict[str, Any] = {
            "x": loc.get("x", 0),
            "y": loc.get("y", 0),
            "plane": loc.get("plane", 0),
        }
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Prayer Points sensor ─────────────────────────────────────────────


class OsrsPrayerPointsSensor(SensorEntity):
    """Sensor whose state is current prayer points, attributes hold current/max."""

    _attr_has_entity_name = True
    _attr_name = "Prayer Points"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_prayer_points"

    @property
    def native_value(self) -> int:
        """Current prayer points."""
        return self._state.prayer_points.get("current", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "current": self._state.prayer_points.get("current", 0),
            "max": self._state.prayer_points.get("max", 0),
        }
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Health sensor ────────────────────────────────────────────────────


class OsrsHealthSensor(SensorEntity):
    """Sensor whose state is current HP, attributes hold current/max."""

    _attr_has_entity_name = True
    _attr_name = "Health"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_health"

    @property
    def native_value(self) -> int:
        """Current hitpoints."""
        return self._state.health.get("current", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "current": self._state.health.get("current", 0),
            "max": self._state.health.get("max", 0),
        }
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Equipment sensor ────────────────────────────────────────────────


class OsrsEquipmentSensor(SensorEntity):
    """Single sensor whose attributes hold per-slot equipment data."""

    _attr_has_entity_name = True
    _attr_name = "Equipment"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_equipment"

    @property
    def native_value(self) -> int:
        """Number of equipped slots."""
        return sum(1 for v in self._state.equipment.values() if v)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Always include all known slots; missing slots are empty dicts
        attrs: dict[str, Any] = {}
        for slot in EQUIPMENT_SLOTS:
            attrs[slot] = self._state.equipment.get(slot, {})
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Game State sensor ───────────────────────────────────────────────


class OsrsGameStateSensor(SensorEntity):
    """Sensor whose state is the RuneLite client game state."""

    _attr_has_entity_name = True
    _attr_name = "Game State"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_game_state"

    @property
    def native_value(self) -> str:
        """Current game state."""
        return self._state.game_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Total Level sensor ──────────────────────────────────────────────


class OsrsTotalLevelSensor(SensorEntity):
    """Sum of all skill levels; total XP in an attribute."""

    _attr_has_entity_name = True
    _attr_name = "Total Level"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_total_level"

    @property
    def native_value(self) -> int:
        return self._state.total_level

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "total_xp": self._state.total_xp,
            "skill_count": len(self._state.skills),
        }
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Combat Level sensor ─────────────────────────────────────────────


class OsrsCombatLevelSensor(SensorEntity):
    """OSRS combat level computed from combat skill levels."""

    _attr_has_entity_name = True
    _attr_name = "Combat Level"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_combat_level"

    @property
    def native_value(self) -> int | None:
        return self._state.combat_level

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._state.last_update:
            attrs["last_update"] = self._state.last_update
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Last Death / Last Loot sensors ──────────────────────────────────


def _recent_history(
    sensor: SensorEntity, account_key: str, event_type: str
) -> list[dict[str, Any]]:
    """Return the most recent history entries for an account + event type."""
    hass = getattr(sensor, "hass", None)
    if hass is None:
        return []
    entry_data = hass.data.get(DOMAIN, {}).get(sensor._entry.entry_id)  # type: ignore[attr-defined]
    if not isinstance(entry_data, dict):
        return []
    history_store = entry_data.get(DATA_HISTORY_STORE)
    if history_store is None:
        return []
    entries = history_store.get_or_create(account_key).get(event_type)
    return list(reversed(entries[-_RECENT_HISTORY_LIMIT:]))


class OsrsLastDeathSensor(SensorEntity):
    """Details of the player's most recent death."""

    _attr_has_entity_name = True
    _attr_name = "Last Death"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_last_death"

    @property
    def native_value(self) -> str | None:
        death = self._state.last_death
        if not death:
            return None
        return death.get("killerName") or "Unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        death = self._state.last_death
        attrs: dict[str, Any] = {}
        if death:
            attrs.update(
                {
                    "value_lost": death.get("valueLost", 0),
                    "danger": death.get("danger"),
                    "killer_name": death.get("killerName"),
                    "killer_npc_id": death.get("killerNpcId"),
                    "kept_items": death.get("keptItems", []),
                    "lost_items": death.get("lostItems", []),
                    "location": death.get("location"),
                    "timestamp": death.get("timestamp"),
                }
            )
        attrs["recent"] = _recent_history(self, self._state.player_name, "DEATH")
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


class OsrsLastLootSensor(SensorEntity):
    """Details of the player's most recent loot drop."""

    _attr_has_entity_name = True
    _attr_name = "Last Loot"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_last_loot"

    @property
    def native_value(self) -> str | None:
        """The most notable item from the drop (not the NPC/source)."""
        loot = self._state.last_loot
        if not loot:
            return None
        highest = loot.get("highestValueItem")
        if isinstance(highest, dict) and highest.get("name"):
            return highest["name"]
        items = loot.get("items")
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict) and first.get("name"):
                return first["name"]
        source = loot.get("source")
        if isinstance(source, dict) and source.get("text"):
            return source["text"]
        return "Loot"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        loot = self._state.last_loot
        attrs: dict[str, Any] = {}
        if loot:
            attrs.update(
                {
                    "total_value": loot.get("totalValue", 0),
                    "highest_value_item": loot.get("highestValueItem"),
                    "items": loot.get("items", []),
                    "source": loot.get("source"),
                    "type": loot.get("type"),
                    "npc_id": loot.get("npcId"),
                    "timestamp": loot.get("timestamp"),
                }
            )
        attrs["recent"] = _recent_history(self, self._state.player_name, "LOOT")
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Detail sensors ──────────────────────────────────────────────────


_MAX_DETAIL_SLUG_LENGTH = 64


def _slugify_detail_key(key: str) -> str:
    """Create an entity-safe slug from a detail sensor key."""
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")[:_MAX_DETAIL_SLUG_LENGTH]


class OsrsAccountDetailSensor(SensorEntity):
    """Dynamic sensor for a specific detail (skill xp, skill level, etc.)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
        detail_key: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._detail_key = detail_key
        detail_slug = _slugify_detail_key(detail_key)
        self._attr_unique_id = f"{state.account_hash}_detail_{detail_slug}"
        self._attr_name = detail_key

    @property
    def native_value(self):
        detail = self._state.detail_sensors.get(self._detail_key)
        if detail is None:
            return None
        return detail.get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        detail = self._state.detail_sensors.get(self._detail_key)
        if detail is None:
            return {}
        attrs: dict[str, Any] = {}
        if detail.get("attributes"):
            attrs.update(detail["attributes"])
        if detail.get("last_update"):
            attrs["last_update"] = detail["last_update"]
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )


# ── Event total sensors ─────────────────────────────────────────────


class OsrsEventTotalSensor(SensorEntity):
    """Sensor that tracks the total count of a specific event type per account."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
        event_type: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._event_type = event_type
        event_slug = _slugify_detail_key(event_type)
        self._attr_unique_id = f"{state.account_hash}_event_{event_slug}_total"
        self._attr_name = f"{event_type} Total"

    @property
    def native_value(self) -> int:
        """Total number of events received."""
        entry = self._state.event_totals.get(self._event_type)
        if entry is None:
            return 0
        return entry.get("count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        entry = self._state.event_totals.get(self._event_type)
        if entry is None:
            return {}
        attrs: dict[str, Any] = {}
        if entry.get("last_fired"):
            attrs["last_fired"] = entry["last_fired"]
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        return _account_device_info(self._entry, self._state)

    @callback
    def _handle_update(self, account_hash: str) -> None:
        if account_hash == self._state.account_hash:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACCOUNT_UPDATED, self._handle_update
            )
        )
