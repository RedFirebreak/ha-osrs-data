"""Per-account sensor entities for the OSRS Data integration."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .account_store import AccountState
from .const import DOMAIN, DATA_ACCOUNT_STORE, SIGNAL_ACCOUNT_UPDATED
from .parser.base import EQUIPMENT_SLOTS

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

            new_entities.append(OsrsPlayerInfoSensor(entry, state, slug))
            new_entities.append(OsrsInventorySensor(entry, state, slug))
            new_entities.append(OsrsEquipmentSensor(entry, state, slug))
            new_entities.append(OsrsHealthSensor(entry, state, slug))
            new_entities.append(OsrsPrayerSensor(entry, state, slug))

        # Create detail sensors for any new keys (skill xp & level)
        for key in state.detail_sensors:
            if key not in known_detail_keys[account_hash]:
                known_detail_keys[account_hash].add(key)
                new_entities.append(
                    OsrsAccountDetailSensor(entry, state, slug, key)
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


# ── Prayer sensor ────────────────────────────────────────────────────


class OsrsPrayerSensor(SensorEntity):
    """Sensor whose state is current prayer points, attributes hold current/max."""

    _attr_has_entity_name = True
    _attr_name = "Prayer"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_prayer"

    @property
    def native_value(self) -> int:
        """Current prayer points."""
        return self._state.prayer.get("current", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "current": self._state.prayer.get("current", 0),
            "max": self._state.prayer.get("max", 0),
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
