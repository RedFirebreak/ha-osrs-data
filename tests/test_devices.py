"""The integration's devices: the "OSRS Data" receiver and one per account.

Every account device is connected via the receiver device. Home Assistant
2026.8 added ``via_device_id`` (the receiver's device registry id) to
``DeviceInfo`` for that link. 2026.9 logs a deprecation for the older
``via_device`` (the receiver's identifier), which stops working in 2027.8.
Versions before 2026.8 only know ``via_device``; the oldest supported
version is 2026.2.2 (``hacs.json``).
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock homeassistant before imports
for mod_name in (
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

# Minimal entity stand-ins, so the entity classes can be instantiated
# (the same ones as in test_presence.py).
_bs_mod = MagicMock()


class _BinarySensorEntity:
    """Minimal stand-in for homeassistant.components.binary_sensor.BinarySensorEntity."""

    _attr_has_entity_name: bool = False
    _attr_name: str | None = None
    _attr_unique_id: str | None = None

    @property
    def unique_id(self):
        return self._attr_unique_id


_bs_mod.BinarySensorEntity = _BinarySensorEntity
sys.modules["homeassistant.components.binary_sensor"] = _bs_mod

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

# Force re-import so our stand-ins are used
sys.modules.pop("custom_components.osrs_data.sensor", None)
sys.modules.pop("custom_components.osrs_data.binary_sensor", None)

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

import custom_components.osrs_data as integration  # noqa: E402
from custom_components.osrs_data.account_store import AccountState  # noqa: E402
from custom_components.osrs_data.binary_sensor import OsrsOnlineBinarySensor  # noqa: E402
from custom_components.osrs_data.const import CONF_ICONS_BASE_URL, DOMAIN  # noqa: E402
from custom_components.osrs_data.sensor import (  # noqa: E402
    OsrsPlayerInfoSensor,
    OsrsStatusSensor,
)

# What ``from homeassistant.helpers import device_registry`` gives the
# integration in these tests.
_ha_device_registry = sys.modules["homeassistant.helpers"].device_registry

ENTRY_ID = "entry_1"
RECEIVER = (DOMAIN, ENTRY_ID)


# ── Home Assistant stand-ins ─────────────────────────────────────────
# Only what decides how a device is linked, taken from
# homeassistant/helpers/device_registry.py of the named versions.


class _DeviceInfo2026_2(TypedDict, total=False):
    """``DeviceInfo`` of Home Assistant 2026.2.2 up to 2026.7."""

    identifiers: set[tuple[str, str]]
    manufacturer: str | None
    model: str | None
    name: str | None
    sw_version: str | None
    via_device: tuple[str, str]


class _DeviceInfo2026_8(_DeviceInfo2026_2, total=False):
    """Home Assistant 2026.8 has both keys (and rejects getting both)."""

    via_device_id: str


class _DeviceInfo2026_9(TypedDict, total=False):
    """Home Assistant 2026.9 has ``via_device_id`` only."""

    identifiers: set[tuple[str, str]]
    manufacturer: str | None
    model: str | None
    name: str | None
    sw_version: str | None
    via_device_id: str


class _DeviceRegistry:
    """The devices in a device registry, by registry id."""

    def __init__(self) -> None:
        self.devices: dict[str, SimpleNamespace] = {}

    def device(self, identifier: tuple[str, str]) -> SimpleNamespace | None:
        for device in self.devices.values():
            if identifier in device.identifiers:
                return device
        return None

    def _get_or_create(
        self, identifiers: set[tuple[str, str]], **fields: Any
    ) -> SimpleNamespace:
        (identifier,) = identifiers
        device = self.device(identifier)
        if device is None:
            device = SimpleNamespace(
                id=f"registry-id-{len(self.devices) + 1}",
                identifiers=set(identifiers),
                via_device_id=None,
            )
            self.devices[device.id] = device
        # A value that is not given keeps what the device has.
        vars(device).update({k: v for k, v in fields.items() if v is not None})
        return device


class _DeviceRegistry2026_2(_DeviceRegistry):
    """``async_get_or_create`` of Home Assistant 2026.2.2 up to 2026.7.

    It has no ``**kwargs``: a key it does not know, such as
    ``via_device_id``, is a ``TypeError`` and the entity is not added.
    """

    def async_get_or_create(
        self,
        *,
        config_entry_id: str,
        config_subentry_id: str | None = None,
        identifiers: set[tuple[str, str]],
        manufacturer: str | None = None,
        model: str | None = None,
        name: str | None = None,
        sw_version: str | None = None,
        via_device: tuple[str, str] | None = None,
    ) -> SimpleNamespace:
        via = self.device(via_device) if via_device else None
        return self._get_or_create(
            identifiers,
            manufacturer=manufacturer,
            model=model,
            name=name,
            sw_version=sw_version,
            via_device_id=via.id if via else None,
        )


class _DeviceRegistry2026_9(_DeviceRegistry):
    """``async_get_or_create`` of Home Assistant 2026.9."""

    def __init__(self) -> None:
        super().__init__()
        # What Home Assistant logs as "calls `device_registry.
        # async_get_or_create` with a deprecated `…` parameter".
        self.deprecated: list[str] = []

    def async_get_or_create(
        self,
        *,
        config_entry_id: str,
        config_subentry_id: str | None = None,
        identifiers: set[tuple[str, str]],
        manufacturer: str | None = None,
        model: str | None = None,
        name: str | None = None,
        sw_version: str | None = None,
        via_device_id: str | None = None,
        **kwargs: Any,
    ) -> SimpleNamespace:
        if "via_device" in kwargs:
            self.deprecated.append("via_device")
            via = self.device(kwargs.pop("via_device"))
            via_device_id = via.id if via else None
        if kwargs:
            raise TypeError(f"unexpected keyword arguments {sorted(kwargs)}")
        if via_device_id is not None and via_device_id not in self.devices:
            # DeviceInfoError in Home Assistant: the entity is not added.
            raise ValueError(f"via_device_id {via_device_id} is not a registered device id")
        return self._get_or_create(
            identifiers,
            manufacturer=manufacturer,
            model=model,
            name=name,
            sw_version=sw_version,
            via_device_id=via_device_id,
        )


@contextmanager
def _home_assistant(device_info: type, registry: _DeviceRegistry):
    """Run the integration against this ``DeviceInfo`` and device registry."""
    with patch.object(_ha_device_registry, "DeviceInfo", device_info), \
            patch.object(_ha_device_registry, "async_get", return_value=registry):
        yield


def _make_entry(entry_id: str = ENTRY_ID) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = "OSRS Data"
    entry.data = {}
    # Icons off: their refresh is not what these tests check.
    entry.options = {CONF_ICONS_BASE_URL: ""}
    return entry


async def _set_up(entry: MagicMock, forward: Any = None) -> MagicMock:
    """Run ``async_setup_entry`` and return ``hass``."""
    hass = MagicMock()
    # Views are out of scope here; skip registering them.
    hass.data = {DOMAIN: {"_views_registered": True, "_pair_view_registered": True}}
    hass.config_entries.async_forward_entry_setups = AsyncMock(side_effect=forward)
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    with patch.dict(sys.modules, {"homeassistant.helpers.event": MagicMock()}), \
            patch.object(integration, "get_store", return_value=store):
        assert await integration.async_setup_entry(hass, entry) is True
    return hass


def _add(registry: _DeviceRegistry, entry: MagicMock, entity: Any) -> SimpleNamespace:
    """Register an entity's device the way the entity platform does."""
    return registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=None,
        **entity.device_info,
    )


def _account_entities(entry: MagicMock, hass: MagicMock | None) -> list[Any]:
    """A sensor and the binary sensor of one account, as if added to hass."""
    state = AccountState("zezima", "Zezima")
    entities = [
        OsrsPlayerInfoSensor(entry, state, "zezima"),
        OsrsOnlineBinarySensor(entry, state),
    ]
    if hass is not None:
        for entity in entities:
            entity.hass = hass
    return entities


VERSIONS_WITH_VIA_DEVICE_ID = pytest.mark.parametrize(
    "device_info", [_DeviceInfo2026_8, _DeviceInfo2026_9], ids=["2026.8", "2026.9"]
)
ALL_VERSIONS = pytest.mark.parametrize(
    ("device_info", "registry_class"),
    [
        (_DeviceInfo2026_2, _DeviceRegistry2026_2),
        (_DeviceInfo2026_9, _DeviceRegistry2026_9),
    ],
    ids=["2026.2", "2026.9"],
)


class TestReceiverDevice:
    """The "OSRS Data" device, which the Status sensor belongs to."""

    def test_status_sensor_device_is_unchanged(self):
        assert OsrsStatusSensor(_make_entry()).device_info == {
            "identifiers": {("osrs_data", "entry_1")},
            "name": "OSRS Data",
            "manufacturer": "Custom",
            "model": "Event Receiver",
        }

    @ALL_VERSIONS
    @pytest.mark.asyncio
    async def test_registered_before_the_platforms_are_set_up(
        self, device_info, registry_class
    ):
        registry = registry_class()
        when_forwarded: dict[str, Any] = {}

        async def forward(entry, platforms):
            when_forwarded["receiver"] = registry.device(RECEIVER)

        with _home_assistant(device_info, registry):
            await _set_up(_make_entry(), forward)

        receiver = when_forwarded["receiver"]
        assert receiver is not None
        assert receiver.identifiers == {("osrs_data", "entry_1")}
        assert receiver.name == "OSRS Data"
        assert receiver.manufacturer == "Custom"
        assert receiver.model == "Event Receiver"

    @ALL_VERSIONS
    @pytest.mark.asyncio
    async def test_status_sensor_joins_the_registered_device(
        self, device_info, registry_class
    ):
        registry = registry_class()
        entry = _make_entry()
        with _home_assistant(device_info, registry):
            await _set_up(entry)
            registered = registry.device(RECEIVER)
            status_device = _add(registry, entry, OsrsStatusSensor(entry))

        assert registered is not None
        assert status_device is registered
        assert len(registry.devices) == 1

    @pytest.mark.asyncio
    async def test_duplicate_entry_gets_no_device(self):
        """A second entry is not set up, so it must not leave a device behind."""
        registry = _DeviceRegistry2026_9()
        hass = MagicMock()
        hass.data = {DOMAIN: {"first": {}, "_views_registered": True}}
        with _home_assistant(_DeviceInfo2026_9, registry), \
                patch.object(integration, "get_store"):
            assert await integration.async_setup_entry(hass, _make_entry("second")) is False

        assert registry.devices == {}


class TestAccountDeviceLink:
    """How an "OSRS <player>" device is connected via the receiver."""

    @VERSIONS_WITH_VIA_DEVICE_ID
    @pytest.mark.asyncio
    async def test_linked_by_registry_id(self, device_info):
        """Also on 2026.8, which still has ``via_device``: only the new key is sent."""
        registry = _DeviceRegistry2026_9()
        entry = _make_entry()
        with _home_assistant(device_info, registry):
            hass = await _set_up(entry)
            devices = [
                _add(registry, entry, entity)
                for entity in _account_entities(entry, hass)
            ]

        assert registry.deprecated == []
        receiver = registry.device(RECEIVER)
        assert receiver is not None
        assert [device.via_device_id for device in devices] == [receiver.id, receiver.id]
        # The receiver and one device for the account.
        assert len(registry.devices) == 2

    @pytest.mark.asyncio
    async def test_older_home_assistant_keeps_via_device(self):
        registry = _DeviceRegistry2026_2()
        entry = _make_entry()
        with _home_assistant(_DeviceInfo2026_2, registry):
            hass = await _set_up(entry)
            receiver = _add(registry, entry, OsrsStatusSensor(entry))
            entities = _account_entities(entry, hass)
            infos = [entity.device_info for entity in entities]
            # A key this registry does not know would be a TypeError here.
            devices = [_add(registry, entry, entity) for entity in entities]

        for info in infos:
            assert info["via_device"] == ("osrs_data", "entry_1")
            assert "via_device_id" not in info
        assert [device.via_device_id for device in devices] == [receiver.id, receiver.id]
        assert len(registry.devices) == 2

    @VERSIONS_WITH_VIA_DEVICE_ID
    def test_no_deprecated_key_while_the_receiver_is_unknown(self, device_info):
        """Without a known receiver there is no link, not a deprecated one."""
        entry = _make_entry()
        with _home_assistant(device_info, _DeviceRegistry2026_9()):
            infos = [entity.device_info for entity in _account_entities(entry, None)]

        for info in infos:
            assert "via_device" not in info
            assert "via_device_id" not in info
            assert info["identifiers"] == {("osrs_data", "zezima")}
