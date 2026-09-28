from __future__ import annotations

import logging
import voluptuous as vol

from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .account_store import AccountStore
from .api import (
    OsrsDeviceRevokeView,
    OsrsDevicesView,
    OsrsEventsView,
    OsrsPairCodeView,
    OsrsPairView,
    _build_save_payload,
)
from .const import (
    DOMAIN,
    DATA_ACCOUNT_STORE,
    DATA_HISTORY_STORE,
    DATA_DEDUPE_CACHE,
    DATA_EVENT_DEDUPE_CACHE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    CONF_DEATH_LIMIT,
    CONF_LOOT_LIMIT,
    CONF_DEFAULT_LIMIT,
    CONF_DEDUPE_TTL,
    CONF_PRESENCE_TIMEOUT,
    DEFAULT_DEATH_LIMIT,
    DEFAULT_LOOT_LIMIT,
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_DEDUPE_TTL,
    PAIRING_CODE_TTL,
    PRESENCE_CHECK_INTERVAL,
    PRESENCE_TIMEOUT,
    SIGNAL_ACCOUNT_UPDATED,
)
from .dedupe import DedupeCache, EventDedupeCache
from .history import HistoryStore
from .pairing import PairingStore
from .storage import get_store

PLATFORMS: list[str] = ["sensor", "binary_sensor"]

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

    # Resolve configurable options (defaults preserve prior behavior).
    opts = entry.options
    history_limits = {
        "DEATH": opts.get(CONF_DEATH_LIMIT, DEFAULT_DEATH_LIMIT),
        "LOOT": opts.get(CONF_LOOT_LIMIT, DEFAULT_LOOT_LIMIT),
    }
    default_limit = opts.get(CONF_DEFAULT_LIMIT, DEFAULT_HISTORY_LIMIT)
    dedupe_ttl = opts.get(CONF_DEDUPE_TTL, DEFAULT_DEDUPE_TTL)
    presence_timeout = opts.get(CONF_PRESENCE_TIMEOUT, PRESENCE_TIMEOUT)

    history_store = HistoryStore(limits=history_limits, default_limit=default_limit)
    account_store = AccountStore(presence_timeout=presence_timeout)
    pairing_store = PairingStore()

    # Restore persisted data
    store = get_store(hass)
    stored = await store.async_load()
    if stored and isinstance(stored, dict):
        history_store.load_dict(stored.get("history", {}))
        account_store.load_dict(stored.get("accounts") or [])
        pairing_store.load_dict(stored.get("paired_devices") or [])
    else:
        # First run — load paired devices created during config flow
        import time as _time

        initial_devices = entry.data.get("initial_devices", [])
        if initial_devices:
            pairing_store.load_dict(initial_devices)
            _LOGGER.info("Loaded %d device(s) paired during setup", len(initial_devices))

        # If the user clicked Submit before RuneLite paired, inject
        # the pending code with a fresh TTL so they can still pair.
        initial_pair = entry.data.get("initial_pair")
        if initial_pair:
            pairing_store.inject_pending_code(
                code=initial_pair["code"],
                device_name=initial_pair.get("device_name", ""),
                expires_at=_time.time() + PAIRING_CODE_TTL,
            )
            _LOGGER.info(
                "Pairing code ready — enter it in RuneLite within %d minutes",
                PAIRING_CODE_TTL // 60,
            )

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_ACCOUNT_STORE: account_store,
        DATA_HISTORY_STORE: history_store,
        DATA_DEDUPE_CACHE: DedupeCache(ttl=dedupe_ttl),
        DATA_EVENT_DEDUPE_CACHE: EventDedupeCache(ttl=dedupe_ttl),
        DATA_PAIRING_STORE: pairing_store,
        DATA_STORE: store,
    }

    # Reload the entry when options change so new limits/TTLs take effect.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register API views (guarded — may already be registered by config flow)
    if not hass.data[DOMAIN].get("_views_registered"):
        hass.data[DOMAIN]["_views_registered"] = True
        hass.http.register_view(OsrsPairCodeView())
        hass.http.register_view(OsrsPairView())
        hass.http.register_view(OsrsEventsView())
        hass.http.register_view(OsrsDevicesView())
        hass.http.register_view(OsrsDeviceRevokeView())
    elif not hass.data[DOMAIN].get("_pair_view_registered"):
        # Config flow only registered the pair view — register the rest
        hass.data[DOMAIN]["_views_registered"] = True
        hass.http.register_view(OsrsPairCodeView())
        hass.http.register_view(OsrsEventsView())
        hass.http.register_view(OsrsDevicesView())
        hass.http.register_view(OsrsDeviceRevokeView())

    # Register services
    async def _handle_create_pairing_code(call: ServiceCall) -> ServiceResponse:
        """Handle the create_pairing_code service call."""
        device_name = call.data.get("device_name", "RuneLite Client")
        entry_data_svc = hass.data[DOMAIN].get(entry.entry_id)
        if entry_data_svc is None:
            raise ValueError("Integration not configured")
        pairing = entry_data_svc.get(DATA_PAIRING_STORE)
        if pairing is None:
            raise ValueError("Pairing store not available")
        code = pairing.create_pairing_code(device_name)

        # Fire a persistent notification so the user can see the code in the HA UI
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "OSRS Data — Pairing Code",
                "message": (
                    f"Enter this code in your RuneLite plugin to pair:\n\n"
                    f"## **{code}**\n\n"
                    f"Device name: *{device_name}*\n\n"
                    f"This code expires in 5 minutes."
                ),
                "notification_id": f"osrs_data_pairing_{code}",
            },
        )
        return {"code": code, "expires_in": PAIRING_CODE_TTL}

    if not hass.services.has_service(DOMAIN, "create_pairing_code"):
        hass.services.async_register(
            DOMAIN,
            "create_pairing_code",
            _handle_create_pairing_code,
            schema=vol.Schema(
                {
                    vol.Optional("device_name", default="RuneLite Client"): str,
                }
            ),
            supports_response=SupportsResponse.OPTIONAL,
        )

    async def _handle_get_history(call: ServiceCall) -> ServiceResponse:
        """Return recent event history, newest first.

        Optional filters: ``account_name`` (defaults to all accounts) and
        ``event_type`` (defaults to every type).  ``limit`` caps the
        number of returned entries.
        """
        entry_data_svc = hass.data[DOMAIN].get(entry.entry_id)
        if entry_data_svc is None:
            raise ValueError("Integration not configured")
        history_store = entry_data_svc.get(DATA_HISTORY_STORE)
        acct_store = entry_data_svc.get(DATA_ACCOUNT_STORE)
        if history_store is None or acct_store is None:
            return {"entries": []}

        account_name = call.data.get("account_name")
        event_type = call.data.get("event_type")
        if event_type:
            event_type = event_type.upper()
        limit = call.data.get("limit", 20)

        if account_name:
            keys = [account_name]
        else:
            keys = [acct.player_name for acct in acct_store.accounts]

        entries: list[dict] = []
        for key in keys:
            hist = history_store.get_or_create(key)
            items = hist.get(event_type) if event_type else hist.all_entries()
            for item in items:
                entries.append({**item, "account_name": key})

        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return {"entries": entries[:limit]}

    if not hass.services.has_service(DOMAIN, "get_history"):
        hass.services.async_register(
            DOMAIN,
            "get_history",
            _handle_get_history,
            schema=vol.Schema(
                {
                    vol.Optional("account_name"): str,
                    vol.Optional("event_type"): str,
                    vol.Optional("limit", default=20): vol.All(
                        int, vol.Range(min=1, max=500)
                    ),
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

    _LOGGER.info("OSRS Data events endpoint at /api/osrs-data/events")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Periodic presence check ─────────────────────────────────────
    from homeassistant.helpers.event import async_track_time_interval

    def _check_presence(_now: datetime) -> None:
        """Mark accounts offline if no data received within timeout.

        Uses the per-account dynamic timeout derived from ``tickDelay``
        when available, otherwise falls back to *PRESENCE_TIMEOUT*.
        """
        now = datetime.now(timezone.utc)
        for acct in account_store.accounts:
            if acct.is_online and acct.last_seen is not None:
                elapsed = (now - acct.last_seen).total_seconds()
                if elapsed > acct.presence_timeout:
                    acct.is_online = False
                    acct.offline_reason = "timeout"
                    _LOGGER.debug(
                        "Account %s timed out after %.1fs (limit %.1fs)",
                        acct.player_name,
                        elapsed,
                        acct.presence_timeout,
                    )
                    async_dispatcher_send(
                        hass, SIGNAL_ACCOUNT_UPDATED, acct.account_hash
                    )

    unsub_presence = async_track_time_interval(
        hass, _check_presence, timedelta(seconds=PRESENCE_CHECK_INTERVAL)
    )
    entry.async_on_unload(unsub_presence)

    # Fire dispatcher signals for restored accounts so sensor entities
    # are re-created with their persisted values.
    for acct in account_store.accounts:
        async_dispatcher_send(hass, SIGNAL_ACCOUNT_UPDATED, acct.account_hash)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when its options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        # Immediate final flush of history and account state to disk
        if entry_data and isinstance(entry_data, dict):
            store = entry_data.get(DATA_STORE)
            if store is not None:
                await store.async_save(_build_save_payload(entry_data))

        # If no more entries, clean up domain-level state so a fresh
        # install/re-add goes through a clean path.
        remaining = {
            k: v
            for k, v in hass.data.get(DOMAIN, {}).items()
            if not isinstance(k, str) or not k.startswith("_")
        }
        if not remaining:
            # Unregister the services
            if hass.services.has_service(DOMAIN, "create_pairing_code"):
                hass.services.async_remove(DOMAIN, "create_pairing_code")
            if hass.services.has_service(DOMAIN, "get_history"):
                hass.services.async_remove(DOMAIN, "get_history")
            # Clear all domain-level flags so views re-register on next setup
            hass.data.pop(DOMAIN, None)
            _LOGGER.debug("All OSRS Data entries removed — domain state cleaned up")

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal (deletion) of a config entry.

    This fires *after* async_unload_entry and removes persisted storage
    so the next install starts completely fresh.
    """
    store = get_store(hass)
    await store.async_remove()
    _LOGGER.info("OSRS Data storage removed for deleted entry")
