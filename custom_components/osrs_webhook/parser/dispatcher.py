"""Dispatcher that routes Dink payloads to the correct parser by event type."""

from __future__ import annotations

import logging
from typing import Any

from .parsers import (
    achievement_diary,
    collection,
    combat_achievement,
    death,
    level,
    loot,
    pet,
    quest,
)

_LOGGER = logging.getLogger(__name__)

_PARSERS: dict[str, Any] = {
    "LEVEL": level,
    "LOOT": loot,
    "DEATH": death,
    "PET": pet,
    "QUEST": quest,
    "COMBAT_ACHIEVEMENT": combat_achievement,
    "ACHIEVEMENT_DIARY": achievement_diary,
    "COLLECTION": collection,
}

SUPPORTED_TYPES: frozenset[str] = frozenset(_PARSERS)


def dispatch(
    event_type: str,
    extra: dict[str, Any],
    player_name: str,
) -> dict[str, Any] | None:
    """Route an event to its parser and return parsed result.

    Returns a dict with 'summary' and 'data' keys, or *None* if the
    event type is not supported by any parser.
    """
    normalized = event_type.upper().strip()
    parser = _PARSERS.get(normalized)
    if parser is None:
        _LOGGER.debug("No parser for event type %s", normalized)
        return None

    try:
        return parser.parse(extra, player_name)
    except Exception:
        _LOGGER.exception("Parser failed for %s", normalized)
        return None
