from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    # Placeholder entity so the integration shows up with at least one device/entity.
    async_add_entities([OsrsWebhookStatusSensor(entry)])


class OsrsWebhookStatusSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Status"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_native_value = "ready"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OSRS Webhook",
            "manufacturer": "Custom",
            "model": "Webhook Receiver",
        }
