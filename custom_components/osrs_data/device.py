"""The integration's devices in Home Assistant's device registry.

A config entry has one "OSRS Data" receiver device. Every account gets an
"OSRS <player>" device of its own, which is connected via the receiver.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN


def receiver_device_info(entry: ConfigEntry) -> dict[str, Any]:
    """Device info of the config entry's receiver device."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "OSRS Data",
        "manufacturer": "Custom",
        "model": "Event Receiver",
    }


def _has_via_device_id() -> bool:
    """Whether this Home Assistant links a device with ``via_device_id``.

    Home Assistant 2026.8 added ``via_device_id`` (the device registry id
    of the device another one is connected via) to ``DeviceInfo``. From
    2026.9 it logs a deprecation for ``via_device`` (that device's
    identifier), which 2027.8 removes. Versions before 2026.8 only take
    ``via_device``.
    """
    # The keys of the TypedDict, read without evaluating its annotations.
    device_info = dr.DeviceInfo
    keys = getattr(device_info, "__required_keys__", frozenset()) | getattr(
        device_info, "__optional_keys__", frozenset()
    )
    return "via_device_id" in keys


def via_receiver_device(
    entry: ConfigEntry, receiver_device_id: str | None
) -> dict[str, Any]:
    """Device info that connects an account device via the receiver.

    ``receiver_device_id`` is the receiver's device registry id, which
    ``async_setup_entry`` keeps when it registers the receiver.
    """
    if not _has_via_device_id():
        return {"via_device": (DOMAIN, entry.entry_id)}
    if receiver_device_id is None:
        # No ``via_device`` as a fallback: Home Assistant would log the
        # deprecation. Without the key it keeps the link a device has.
        return {}
    return {"via_device_id": receiver_device_id}
