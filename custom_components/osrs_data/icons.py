"""OSRS game icons from the icon CDN (https://icons.scapekeeper.com).

URL contract (see the osrs-icons README):

- ``/items/{id}.webp``: item icon, including noted, placeholder and
  stack variants (coins 995–1004).
- ``/skills/{skill}.png``: lowercase skill name; there is no "overall".
- ``/slots/{slot}.png``: empty equipment-slot silhouette, RuneLite's
  ``EquipmentInventorySlot`` in lowercase.
- ``/data/stacks.json``: ``{"995": [[2, 996], ..., [10000, 1004]]}``,
  quantity breakpoints and the variant item id, sorted by breakpoint.

A 404 means "no icon". The resolver never checks whether an image
exists: it only builds URLs. Based on the reference resolver in
osrs-icons (``clients/osrs_icons.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import aiohttp

from .const import DEFAULT_ICONS_BASE_URL

_LOGGER = logging.getLogger(__name__)

# How long a stacks.json request may take before it is given up.
STACKS_TIMEOUT = 30  # seconds

# Lowercase skill names the CDN has an icon for (no "overall").
SKILLS: frozenset[str] = frozenset({
    "attack", "strength", "defence", "ranged", "prayer", "magic",
    "hitpoints", "agility", "herblore", "thieving", "crafting",
    "fletching", "mining", "smithing", "fishing", "cooking",
    "firemaking", "woodcutting", "runecraft", "slayer", "farming",
    "hunter", "construction", "sailing",
})

# Lowercase EquipmentInventorySlot names the CDN has a silhouette for.
# The quiver's extra ammo slot (AMMO_EXTRA) has none.
SLOTS: frozenset[str] = frozenset({
    "head", "cape", "amulet", "weapon", "body", "shield",
    "legs", "gloves", "boots", "ring", "ammo",
})

Stacks = Mapping[str, Sequence[Sequence[int]]]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def icons_base(configured: str | None = DEFAULT_ICONS_BASE_URL) -> str | None:
    """Normalise a configured base URL.

    ``None`` means "not configured" and gives the default. An empty (or
    blank) value turns icons off and gives ``None``.
    """
    if configured is None:
        configured = DEFAULT_ICONS_BASE_URL
    if not isinstance(configured, str):
        return None
    base = configured.strip().rstrip("/")
    return base or None


def stacked_item_id(stacks: Stacks | None, item_id: int, quantity: Any = 1) -> int:
    """The item id whose image shows *quantity* of *item_id*.

    Coins 995 x 250 → 1002. Ids without a stack table are returned as is.
    """
    if not isinstance(quantity, (int, float)) or isinstance(quantity, bool):
        quantity = 1
    result = item_id
    for breakpoint, variant in (stacks or {}).get(str(item_id), ()):
        if quantity >= breakpoint:
            result = variant
    return result


def _parse_stacks(data: Any) -> dict[str, list[list[int]]] | None:
    """Validate a stacks.json document; bad entries are left out.

    Returns None if the document isn't an object at all.
    """
    if not isinstance(data, dict):
        return None
    stacks: dict[str, list[list[int]]] = {}
    for key, table in data.items():
        if not isinstance(key, str) or not isinstance(table, list):
            continue
        pairs = [
            [pair[0], pair[1]]
            for pair in table
            if isinstance(pair, (list, tuple))
            and len(pair) == 2
            and _is_int(pair[0])
            and _is_int(pair[1])
        ]
        if pairs:
            stacks[key] = sorted(pairs)
    return stacks


class IconResolver:
    """Builds icon URLs for one config entry.

    ``base`` is None when icons are turned off; every URL method then
    returns None.
    """

    def __init__(self, base: str | None = DEFAULT_ICONS_BASE_URL) -> None:
        self.base: str | None = icons_base(base)
        self.stacks: dict[str, list[list[int]]] = {}
        # Only the first failure in a row is logged as a warning.
        self._failing = False

    @property
    def enabled(self) -> bool:
        return self.base is not None

    def item_url(self, item_id: Any, quantity: Any = 1) -> str | None:
        """Icon URL for *quantity* of *item_id* (None for an unknown id)."""
        if self.base is None or not _is_int(item_id) or item_id < 0:
            return None
        return f"{self.base}/items/{stacked_item_id(self.stacks, item_id, quantity)}.webp"

    def skill_url(self, skill: Any) -> str | None:
        """'Attack' / 'attack' → /skills/attack.png; None for other names."""
        if self.base is None or not isinstance(skill, str):
            return None
        slug = skill.strip().lower()
        return f"{self.base}/skills/{slug}.png" if slug in SKILLS else None

    def slot_url(self, slot: Any) -> str | None:
        """'HEAD' → /slots/head.png (empty-slot silhouette); None if unknown."""
        if self.base is None or not isinstance(slot, str):
            return None
        slug = slot.strip().lower()
        return f"{self.base}/slots/{slug}.png" if slug in SLOTS else None

    async def async_refresh(self, session: aiohttp.ClientSession) -> bool:
        """Fetch ``{base}/data/stacks.json``.

        Returns True if the stack tables changed. Never raises: on a
        failure the previous tables are kept (item icons then fall back
        to the plain item id for stackables).
        """
        if self.base is None:
            return False
        url = f"{self.base}/data/stacks.json"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=STACKS_TIMEOUT)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except Exception as err:  # noqa: BLE001 - never break setup or the timer
            self._log_failure("Could not fetch OSRS icon stack tables from %s: %s", url, err)
            return False

        stacks = _parse_stacks(data)
        if stacks is None:
            self._log_failure(
                "Could not fetch OSRS icon stack tables from %s: %s",
                url,
                f"unexpected {type(data).__name__}",
            )
            return False

        self._failing = False
        changed = stacks != self.stacks
        self.stacks = stacks
        _LOGGER.debug("Loaded %d OSRS icon stack tables from %s", len(stacks), url)
        return changed

    def _log_failure(self, msg: str, *args: Any) -> None:
        if self._failing:
            _LOGGER.debug(msg, *args)
        else:
            self._failing = True
            _LOGGER.warning(msg, *args)
