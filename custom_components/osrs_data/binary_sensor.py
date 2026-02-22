"""Per-account online binary sensor for the OSRS Data integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .account_store import AccountState
from .const import DOMAIN, DATA_ACCOUNT_STORE, SIGNAL_ACCOUNT_UPDATED
from .sensor import _account_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OSRS Data binary sensors from a config entry."""
    known_accounts: set[str] = set()

    @callback
    def _handle_account_update(account_hash: str) -> None:
        """Create entities for a new account, or update existing ones."""
        store = hass.data[DOMAIN][entry.entry_id][DATA_ACCOUNT_STORE]
        state = store.get_by_hash(account_hash)
        if state is None:
            return

        if account_hash not in known_accounts:
            known_accounts.add(account_hash)
            async_add_entities([OsrsOnlineBinarySensor(entry, state)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ACCOUNT_UPDATED, _handle_account_update)
    )


class OsrsOnlineBinarySensor(BinarySensorEntity):
    """Binary sensor that tracks whether an OSRS account is online."""

    _attr_has_entity_name = True
    _attr_name = "Online"

    def __init__(self, entry: ConfigEntry, state: AccountState) -> None:
        self._entry = entry
        self._state = state
        self._attr_unique_id = f"{state.account_hash}_online"

    @property
    def is_on(self) -> bool:
        """Return True if the account is online."""
        return self._state.is_online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._state.last_seen is not None:
            attrs["last_seen"] = self._state.last_seen.isoformat()
        if self._state.offline_reason is not None:
            attrs["status"] = self._state.offline_reason
        if self._state.tick_delay is not None:
            attrs["tick_delay"] = self._state.tick_delay
        attrs["presence_timeout"] = self._state.presence_timeout
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
