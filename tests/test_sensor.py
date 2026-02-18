"""Tests for the OSRS Data sensor module."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

# Mock homeassistant before imports
for mod_name in (
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.components.webhook",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

# Provide a minimal real SensorEntity so the class can be instantiated.
# Use sys.modules[...] = (not setdefault) to ensure it takes effect even
# when another test file has already injected a plain MagicMock.
_sensor_mod = MagicMock()


class _SensorEntity:
    """Minimal stand-in for homeassistant.components.sensor.SensorEntity."""

    _attr_has_entity_name: bool = False
    _attr_name: str | None = None
    _attr_unique_id: str | None = None
    _attr_native_value = None

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def unique_id(self):
        return self._attr_unique_id


_sensor_mod.SensorEntity = _SensorEntity
sys.modules["homeassistant.components.sensor"] = _sensor_mod

# Force re-import of sensor module so it picks up our _SensorEntity
sys.modules.pop("custom_components.osrs_data.sensor", None)

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.sensor import OsrsWebhookStatusSensor  # noqa: E402
from custom_components.osrs_data.const import CONF_WEBHOOK_ID  # noqa: E402


class TestOsrsWebhookStatusSensor:
    """Tests for the OsrsWebhookStatusSensor entity."""

    def _make_entry(self, webhook_id: str = "test-webhook-id-123"):
        entry = MagicMock()
        entry.entry_id = "entry_1"
        entry.data = {CONF_WEBHOOK_ID: webhook_id}
        return entry

    def test_status_value_is_ready(self):
        entry = self._make_entry()
        sensor = OsrsWebhookStatusSensor(entry)
        assert sensor.native_value == "ready"

    def test_extra_state_attributes_contains_webhook_id(self):
        entry = self._make_entry("my-webhook-id")
        sensor = OsrsWebhookStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert attrs["webhook_id"] == "my-webhook-id"

    def test_extra_state_attributes_contains_webhook_url(self):
        entry = self._make_entry("my-webhook-id")
        sensor = OsrsWebhookStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert attrs["webhook_url"] == "/api/webhook/my-webhook-id"

    def test_webhook_url_format(self):
        entry = self._make_entry("abc123")
        sensor = OsrsWebhookStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert attrs["webhook_url"].startswith("/api/webhook/")
        assert attrs["webhook_url"].endswith("abc123")

    def test_missing_webhook_id_defaults_to_empty(self):
        entry = MagicMock()
        entry.entry_id = "entry_1"
        entry.data = {}
        sensor = OsrsWebhookStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert attrs["webhook_id"] == ""
        assert attrs["webhook_url"] == "/api/webhook/"

    def test_unique_id(self):
        entry = self._make_entry()
        sensor = OsrsWebhookStatusSensor(entry)
        assert sensor.unique_id == "entry_1_status"

    def test_extra_state_attributes_contains_events_endpoint(self):
        entry = self._make_entry("my-webhook-id")
        sensor = OsrsWebhookStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert attrs["events_endpoint"] == "/api/osrs-data/events"

    def test_extra_state_attributes_contains_pair_endpoint(self):
        entry = self._make_entry("my-webhook-id")
        sensor = OsrsWebhookStatusSensor(entry)
        attrs = sensor.extra_state_attributes
        assert attrs["pair_endpoint"] == "/api/osrs-data/pair"
