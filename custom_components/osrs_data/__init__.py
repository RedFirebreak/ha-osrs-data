from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .account_store import AccountStore
from .api import OsrsDeviceRevokeView, OsrsDevicesView, OsrsEventsView, OsrsPairView
from .const import (
    DOMAIN,
    CONF_WEBHOOK_ID,
    DATA_ACCOUNT_STORE,
    DATA_HISTORY_STORE,
    DATA_DEDUPE_CACHE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    SIGNAL_ACCOUNT_UPDATED,
)
from .dedupe import DedupeCache
from .history import HistoryStore
from .pairing import PairingStore
from .storage import get_store
from .webhook import async_register_webhook

PLATFORMS: list[str] = ["sensor"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the OSRS Data component from configuration.yaml.
    
    This integration uses config entries exclusively, so this function
    exists only to satisfy Home Assistant's integration requirements.
    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OSRS Data from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    history_store = HistoryStore()
    account_store = AccountStore()
    pairing_store = PairingStore()

    # Restore persisted data
    store = get_store(hass)
    stored = await store.async_load()
    if stored and isinstance(stored, dict):
        history_store.load_dict(stored.get("history", {}))
        account_store.load_dict(stored.get("accounts") or [])
        pairing_store.load_dict(stored.get("paired_devices") or [])

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_ACCOUNT_STORE: account_store,
        DATA_HISTORY_STORE: history_store,
        DATA_DEDUPE_CACHE: DedupeCache(),
        DATA_PAIRING_STORE: pairing_store,
        DATA_STORE: store,
    }

    # Register legacy webhook endpoint (backward compatibility)
    async_register_webhook(hass, entry)

    # Register new API views for pairing flow
    hass.http.register_view(OsrsPairView())
    hass.http.register_view(OsrsEventsView())
    hass.http.register_view(OsrsDevicesView())
    hass.http.register_view(OsrsDeviceRevokeView())

    webhook_id = entry.data.get(CONF_WEBHOOK_ID, "")
    _LOGGER.info("OSRS Data registered at /api/webhook/%s", webhook_id)
    _LOGGER.info("OSRS Data events endpoint at /api/osrs-data/events")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Fire dispatcher signals for restored accounts so sensor entities
    # are re-created with their persisted values.
    for acct in account_store.accounts:
        async_dispatcher_send(hass, SIGNAL_ACCOUNT_UPDATED, acct.account_hash)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        # Immediate final flush of history and account state to disk
        if entry_data and isinstance(entry_data, dict):
            store = entry_data.get(DATA_STORE)
            if store is not None:
                from .webhook import _build_save_payload
                await store.async_save(_build_save_payload(entry_data))
    return unload_ok
