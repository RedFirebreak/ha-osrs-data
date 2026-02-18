from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, CONF_TITLE


class OsrsDataConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is None:
            schema = vol.Schema({
                vol.Optional(CONF_TITLE, default="OSRS Data"): str,
            })
            return self.async_show_form(step_id="user", data_schema=schema)

        title = user_input.get(CONF_TITLE, "OSRS Data")

        return self.async_create_entry(
            title=title,
            data={
                CONF_TITLE: title,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OsrsDataOptionsFlow()


class OsrsDataOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        # Keep empty for now; we'll add options later (history sizes, auto-add accounts, etc.)
        return self.async_create_entry(title="", data={})
