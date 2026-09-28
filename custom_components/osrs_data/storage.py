from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_MINOR_VERSION, STORAGE_VERSION
from .history import rekey_history

_LOGGER = logging.getLogger(__name__)


def migrate_storage_data(
    old_major_version: int,
    old_minor_version: int,
    old_data: Any,
) -> Any:
    """Return data stored as *old_major*.*old_minor* in the current format.

    Minor versions stay readable by older releases (Home Assistant loads
    a newer minor version as is), so a downgrade keeps working.
    """
    if old_major_version > STORAGE_VERSION:
        raise NotImplementedError(
            f"Migration from version {old_major_version}.{old_minor_version} "
            f"is not supported"
        )
    if old_major_version == 1:
        # v1 → v2: data schema is unchanged, only the version was bumped.
        old_major_version, old_minor_version = 2, 1

    data = old_data
    if (old_major_version, old_minor_version) < (2, 2) and isinstance(data, dict):
        # 2.1 → 2.2: history is keyed by the immutable account key instead
        # of the display name, so it follows renames and can't merge.
        data = {
            **data,
            "history": rekey_history(
                data.get("history") or {}, data.get("accounts") or []
            ),
        }
    return data


class OsrsDataStore(Store):
    """Store subclass that handles schema migrations."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate stored data from an older version."""
        _LOGGER.info(
            "Migrating OSRS Data storage from %s.%s to %s.%s",
            old_major_version,
            old_minor_version,
            STORAGE_VERSION,
            STORAGE_MINOR_VERSION,
        )
        return migrate_storage_data(old_major_version, old_minor_version, old_data)


def get_store(hass: HomeAssistant) -> Store:
    return OsrsDataStore(
        hass, STORAGE_VERSION, STORAGE_KEY, minor_version=STORAGE_MINOR_VERSION
    )
