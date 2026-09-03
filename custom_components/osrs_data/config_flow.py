"""Config flow for the OSRS Data integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_TITLE,
    PAIRING_CODE_TTL,
    DATA_PAIRING_STORE,
    CONF_DEATH_LIMIT,
    CONF_LOOT_LIMIT,
    CONF_DEFAULT_LIMIT,
    CONF_DEDUPE_TTL,
    CONF_PRESENCE_TIMEOUT,
    DEFAULT_DEATH_LIMIT,
    DEFAULT_LOOT_LIMIT,
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_DEDUPE_TTL,
    PRESENCE_TIMEOUT,
)
from .pairing import _generate_pairing_code

_LOGGER = logging.getLogger(__name__)


class OsrsDataConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OSRS Data."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._device_name: str = "OSRS Data"
        self._pairing_code: str | None = None

    async def async_step_user(self, user_input=None):
        """Step 1: Ask for an integration / device name."""
        if user_input is None:
            schema = vol.Schema({
                vol.Optional(CONF_TITLE, default="OSRS Data"): str,
            })
            return self.async_show_form(step_id="user", data_schema=schema)

        self._device_name = user_input.get(CONF_TITLE, "OSRS Data")
        return await self.async_step_pair()

    async def async_step_pair(self, user_input=None):
        """Step 2: Show a pairing code for the RuneLite client.

        The pair API endpoint needs to be available for RuneLite to call
        while this step is displayed.  We register it here (guarded) and
        store a temporary PairingStore in hass.data so the endpoint can
        find the code.

        When the user clicks Submit we check whether pairing happened:
        - If yes  -> save paired-device data in the entry.
        - If no   -> save the pending code so async_setup_entry can
                     inject it with a fresh TTL (user can still pair).
        """
        if user_input is not None:
            # Check if RuneLite already consumed the code
            pending_pairings = (
                self.hass.data.get(DOMAIN, {}).get("_pending_pairings", {})
            )
            pending = pending_pairings.get(self.flow_id)

            data: dict = {CONF_TITLE: self._device_name}

            if pending and pending.get("result") is not None:
                # Pairing completed while the form was open
                data["initial_devices"] = pending["store"].to_dict()
            elif self._pairing_code:
                # Not yet paired — hand the code to async_setup_entry
                data["initial_pair"] = {
                    "code": self._pairing_code,
                    "device_name": self._device_name,
                }

            # Clean up temp state
            pending_pairings.pop(self.flow_id, None)

            return self.async_create_entry(title=self._device_name, data=data)

        # Generate code on first visit
        if self._pairing_code is None:
            self._pairing_code = _generate_pairing_code()

            # Store a temp PairingStore so the pair endpoint can validate
            from .pairing import PairingStore
            import time

            temp_store = PairingStore()
            temp_store.inject_pending_code(
                self._pairing_code,
                self._device_name,
                time.time() + PAIRING_CODE_TTL,
            )
            self.hass.data.setdefault(DOMAIN, {})
            self.hass.data[DOMAIN].setdefault("_pending_pairings", {})
            self.hass.data[DOMAIN]["_pending_pairings"][self.flow_id] = {
                "store": temp_store,
                "result": None,
            }

            # Ensure the pair endpoint is available during the first
            # config flow (before any entry exists).
            self._ensure_pair_view_registered()

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            description_placeholders={
                "code": self._pairing_code,
                "ttl_minutes": str(PAIRING_CODE_TTL // 60),
            },
        )

    def _ensure_pair_view_registered(self) -> None:
        """Register the pair HTTP view once (idempotent)."""
        if self.hass.data.get(DOMAIN, {}).get("_pair_view_registered"):
            return
        try:
            from .api import OsrsPairView

            self.hass.http.register_view(OsrsPairView())
            self.hass.data[DOMAIN]["_pair_view_registered"] = True
            _LOGGER.debug("Registered OsrsPairView during config flow")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not register pair view in config flow", exc_info=True)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return OsrsDataOptionsFlow()


class OsrsDataOptionsFlow(config_entries.OptionsFlow):
    """Options flow — pair additional clients or edit integration settings."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._device_name: str = "RuneLite Client"
        self._pairing_code: str | None = None

    async def async_step_init(self, user_input=None):
        """Present a menu: pair a new client, or edit settings."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["pair_client", "settings"],
        )

    async def async_step_pair_client(self, user_input=None):
        """Ask for a device name for the new client."""
        if user_input is not None:
            self._device_name = user_input.get("device_name", "RuneLite Client")
            return await self.async_step_pair_code()

        schema = vol.Schema({
            vol.Optional("device_name", default="RuneLite Client"): str,
        })
        return self.async_show_form(step_id="pair_client", data_schema=schema)

    async def async_step_settings(self, user_input=None):
        """Edit configurable integration settings (stored in entry.options)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEATH_LIMIT,
                    default=opts.get(CONF_DEATH_LIMIT, DEFAULT_DEATH_LIMIT),
                ): vol.All(int, vol.Range(min=1, max=1000)),
                vol.Optional(
                    CONF_LOOT_LIMIT,
                    default=opts.get(CONF_LOOT_LIMIT, DEFAULT_LOOT_LIMIT),
                ): vol.All(int, vol.Range(min=1, max=1000)),
                vol.Optional(
                    CONF_DEFAULT_LIMIT,
                    default=opts.get(CONF_DEFAULT_LIMIT, DEFAULT_HISTORY_LIMIT),
                ): vol.All(int, vol.Range(min=1, max=1000)),
                vol.Optional(
                    CONF_DEDUPE_TTL,
                    default=opts.get(CONF_DEDUPE_TTL, DEFAULT_DEDUPE_TTL),
                ): vol.All(int, vol.Range(min=0, max=600)),
                vol.Optional(
                    CONF_PRESENCE_TIMEOUT,
                    default=opts.get(CONF_PRESENCE_TIMEOUT, PRESENCE_TIMEOUT),
                ): vol.All(int, vol.Range(min=30, max=86400)),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_pair_code(self, user_input=None):
        """Show the pairing code."""
        if user_input is not None:
            # User clicked Submit — close the options flow.
            return self.async_create_entry(title="", data=self.config_entry.options)

        # Generate code via the live PairingStore (views already registered)
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if entry_data:
            pairing_store = entry_data.get(DATA_PAIRING_STORE)
            if pairing_store:
                self._pairing_code = pairing_store.create_pairing_code(
                    self._device_name
                )

        return self.async_show_form(
            step_id="pair_code",
            data_schema=vol.Schema({}),
            description_placeholders={
                "code": self._pairing_code or "Error — integration not ready",
                "ttl_minutes": str(PAIRING_CODE_TTL // 60),
            },
        )
