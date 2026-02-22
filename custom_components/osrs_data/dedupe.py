"""TTL-based soft deduplication for event retries."""

from __future__ import annotations

import hashlib
import json as _json
import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_TTL = 30  # seconds


def _build_signature(
    account_id: str,
    payload: dict[str, Any],
) -> str:
    """Build a dedup signature from account and payload data."""
    raw = account_id + "|" + _json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


class DedupeCache:
    """TTL cache that drops exact duplicate submissions within a time window."""

    def __init__(self, ttl: int = DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._seen: dict[str, float] = {}

    def is_duplicate(
        self,
        account_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Return True if this payload was already seen within the TTL window."""
        self._evict()
        sig = _build_signature(account_id, payload)
        now = time.monotonic()
        if sig in self._seen:
            _LOGGER.debug("Duplicate submission detected (sig=%s…)", sig[:12])
            return True
        self._seen[sig] = now
        return False

    def _evict(self) -> None:
        """Remove expired entries."""
        cutoff = time.monotonic() - self._ttl
        expired = [k for k, t in self._seen.items() if t < cutoff]
        for k in expired:
            del self._seen[k]


class EventDedupeCache:
    """TTL cache that drops duplicate individual events within a time window.

    If an event carries an ``event_id`` field it is used directly as the
    dedup key.  Otherwise a composite signature is built from the account
    name, event type, and event data.
    """

    def __init__(self, ttl: int = DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._seen: dict[str, float] = {}

    def is_duplicate(
        self,
        account_name: str,
        event: dict[str, Any],
    ) -> bool:
        """Return True if this event was already seen within the TTL window."""
        self._evict()
        key = self._event_key(account_name, event)
        now = time.monotonic()
        if key in self._seen:
            _LOGGER.debug("Duplicate event detected (key=%s…)", key[:12])
            return True
        self._seen[key] = now
        return False

    @staticmethod
    def _event_key(account_name: str, event: dict[str, Any]) -> str:
        """Build a dedup key for a single event dict."""
        event_id = event.get("event_id")
        if event_id:
            return str(event_id)
        raw = (
            account_name
            + "|"
            + event.get("type", "")
            + "|"
            + _json.dumps(event.get("data", ""), sort_keys=True)
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _evict(self) -> None:
        """Remove expired entries."""
        cutoff = time.monotonic() - self._ttl
        expired = [k for k, t in self._seen.items() if t < cutoff]
        for k in expired:
            del self._seen[k]
