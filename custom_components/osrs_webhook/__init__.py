from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .account_store import AccountStore
from .const import DOMAIN, DATA_ACCOUNT_STORE, DATA_HISTORY_STORE, DATA_DEDUPE_CACHE
from .dedupe import DedupeCache
from .history import HistoryStore
from .storage import get_store
from .webhook import async_register_webhook

PLATFORMS: list[str] = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the OSRS Webhook component."""
    # Config entry setup is used, so just return True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OSRS Webhook from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    history_store = HistoryStore()

    # Restore persisted history
    store = get_store(hass)
    stored = await store.async_load()
    if stored and isinstance(stored, dict):
        history_store.load_dict(stored.get("history", {}))

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_ACCOUNT_STORE: AccountStore(),
        DATA_HISTORY_STORE: history_store,
        DATA_DEDUPE_CACHE: DedupeCache(),
    }

    async_register_webhook(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        # Persist history on unload
        if entry_data and isinstance(entry_data, dict):
            history_store = entry_data.get(DATA_HISTORY_STORE)
            if history_store is not None:
                store = get_store(hass)
                await store.async_save({"history": history_store.to_dict()})
    return unload_ok
