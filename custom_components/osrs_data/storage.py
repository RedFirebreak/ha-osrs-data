from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


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
            "Migrating OSRS Data storage from %s.%s to %s.1",
            old_major_version,
            old_minor_version,
            STORAGE_VERSION,
        )

        if old_major_version == 1:
            # v1 → v2: data schema is unchanged, only the version was bumped.
            return old_data

        raise NotImplementedError(
            f"Migration from version {old_major_version}.{old_minor_version} "
            f"is not supported"
        )


def get_store(hass: HomeAssistant) -> Store:
    return OsrsDataStore(hass, STORAGE_VERSION, STORAGE_KEY)
