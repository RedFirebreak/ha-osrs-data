"""TTL-based soft deduplication for webhook retries."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_TTL = 30  # seconds


def _build_signature(
    account_id: str,
    event_type: str,
    extra: dict[str, Any],
) -> str:
    """Build a dedup signature from account, event type, and key fields."""
    parts: list[str] = [account_id, event_type]

    normalized = event_type.upper().strip()

    if normalized == "LOOT":
        for item in extra.get("items", []):
            parts.append(f"{item.get('name', '')}:{item.get('quantity', 1)}")
        parts.append(extra.get("source", ""))
    elif normalized == "LEVEL":
        for skill, lvl in sorted(extra.get("levelledSkills", {}).items()):
            parts.append(f"{skill}:{lvl}")
    elif normalized == "DEATH":
        parts.append(str(extra.get("valueLost", 0)))
        parts.append(str(extra.get("isPvp", False)))
        parts.append(extra.get("killerName", ""))
    elif normalized == "QUEST":
        parts.append(extra.get("questName", ""))
    elif normalized == "PET":
        parts.append(extra.get("petName", ""))
        parts.append(str(extra.get("duplicate", False)))
    elif normalized == "COMBAT_ACHIEVEMENT":
        parts.append(extra.get("tier", ""))
        parts.append(extra.get("task", ""))
    elif normalized == "ACHIEVEMENT_DIARY":
        parts.append(extra.get("area", ""))
        parts.append(extra.get("difficulty", ""))

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


class DedupeCache:
    """TTL cache that drops exact duplicate webhooks within a time window."""

    def __init__(self, ttl: int = DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._seen: dict[str, float] = {}

    def is_duplicate(
        self,
        account_id: str,
        event_type: str,
        extra: dict[str, Any],
    ) -> bool:
        """Return True if this event was already seen within the TTL window."""
        self._evict()
        sig = _build_signature(account_id, event_type, extra)
        now = time.monotonic()
        if sig in self._seen:
            _LOGGER.debug("Duplicate webhook detected (sig=%s…)", sig[:12])
            return True
        self._seen[sig] = now
        return False

    def _evict(self) -> None:
        """Remove expired entries."""
        cutoff = time.monotonic() - self._ttl
        expired = [k for k, t in self._seen.items() if t < cutoff]
        for k in expired:
            del self._seen[k]
