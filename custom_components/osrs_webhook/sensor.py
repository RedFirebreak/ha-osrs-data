"""Per-account sensor entities for the OSRS Webhook integration."""

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
from .const import DOMAIN, CONF_WEBHOOK_ID, DATA_ACCOUNT_STORE, SIGNAL_ACCOUNT_UPDATED

_LOGGER = logging.getLogger(__name__)


_MAX_SLUG_LENGTH = 48

# Per-type last event sensors: (event_type, suffix, friendly label)
_TYPED_LAST_EVENT_SENSORS: list[tuple[str, str, str]] = [
    ("LOOT", "last_loot", "Last Loot"),
    ("DEATH", "last_death", "Last Death"),
    ("PET", "last_pet", "Last Pet"),
    ("QUEST", "last_quest", "Last Quest"),
    ("COMBAT_ACHIEVEMENT", "last_combat_achievement", "Last Combat Achievement"),
    ("ACHIEVEMENT_DIARY", "last_achievement_diary", "Last Achievement Diary"),
    ("COLLECTION", "last_collection_log", "Last Collection Log"),
]


def _slugify_account(account_hash: str) -> str:
    """Create a short, entity-safe slug from an account identifier."""
    return re.sub(r"[^a-z0-9]+", "_", account_hash.lower()).strip("_")[:_MAX_SLUG_LENGTH]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OSRS Webhook sensors from a config entry."""
    async_add_entities([OsrsWebhookStatusSensor(entry)])

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

            new_entities.append(OsrsAccountLastEventSensor(entry, state, slug))

            # Create per-type last event sensors
            for event_type, suffix, label in _TYPED_LAST_EVENT_SENSORS:
                new_entities.append(
                    OsrsAccountTypedLastEventSensor(
                        entry, state, slug, event_type, suffix, label
                    )
                )

        # Create detail sensors for any new keys (only LEVEL skills)
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


# ── Original status sensor (kept for backward compat) ──────────────


class OsrsWebhookStatusSensor(SensorEntity):
    """Simple status sensor for the webhook integration."""

    _attr_has_entity_name = True
    _attr_name = "Status"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_native_value = "ready"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return webhook_id and webhook_url for easy integration setup."""
        webhook_id = self._entry.data.get(CONF_WEBHOOK_ID, "")
        return {
            "webhook_id": webhook_id,
            "webhook_url": f"/api/webhook/{webhook_id}",
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OSRS Webhook",
            "manufacturer": "Custom",
            "model": "Webhook Receiver",
        }


# ── Per-account device helpers ──────────────────────────────────────


def _account_device_info(entry: ConfigEntry, state: AccountState) -> dict[str, Any]:
    """Build device_info for a per-account device."""
    return {
        "identifiers": {(DOMAIN, state.account_hash)},
        "name": f"OSRS {state.player_name}",
        "manufacturer": "RuneLite / Dink",
        "model": "OSRS Account",
        "via_device": (DOMAIN, entry.entry_id),
    }


# ── Last-event sensor ───────────────────────────────────────────────


class OsrsAccountLastEventSensor(SensorEntity):
    """String sensor whose state is the last event type, attributes hold details."""

    _attr_has_entity_name = True
    _attr_name = "Last Event"

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_last_event"

    @property
    def native_value(self) -> str | None:
        return self._state.last_event_type

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._state.last_event_summary:
            attrs["summary"] = self._state.last_event_summary
        if self._state.last_event_data:
            attrs.update(self._state.last_event_data)
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


# ── Per-type last event sensors ─────────────────────────────────────


class OsrsAccountTypedLastEventSensor(SensorEntity):
    """Sensor that tracks the latest event of a specific type.

    Each supported event type (LOOT, DEATH, PET, QUEST, etc.) gets its
    own sensor whose state is the summary and attributes hold all the
    event data.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        state: AccountState,
        slug: str,
        event_type: str,
        suffix: str,
        label: str,
    ) -> None:
        self._entry = entry
        self._state = state
        self._event_type = event_type
        self._attr_unique_id = f"{state.account_hash}_{suffix}"
        self._attr_name = label

    @property
    def native_value(self) -> str | None:
        typed = self._state.last_typed_events.get(self._event_type)
        if typed is None:
            return None
        return typed.get("summary")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        typed = self._state.last_typed_events.get(self._event_type)
        if typed is None:
            return {}
        attrs: dict[str, Any] = {}
        if typed.get("data"):
            attrs.update(typed["data"])
        if typed.get("last_update"):
            attrs["last_update"] = typed["last_update"]
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
    """Dynamic sensor for a specific event detail (skill level, loot source, etc.)."""

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
