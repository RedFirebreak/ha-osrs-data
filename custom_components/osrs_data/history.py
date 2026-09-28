"""Persistent per-account, per-event-type history ring buffers."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Default max entries per event type
DEFAULT_LIMITS: dict[str, int] = {
    "DEATH": 50,
    "LOOT": 100,
}
DEFAULT_LIMIT = 50


class HistoryBuffer:
    """In-memory ring buffer backed by a deque with a max length."""

    def __init__(self, maxlen: int) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def append(self, entry: dict[str, Any]) -> None:
        self._entries.append(entry)

    def as_list(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


class AccountHistory:
    """Per-account history grouped by event type."""

    def __init__(
        self,
        limits: dict[str, int] | None = None,
        default_limit: int = DEFAULT_LIMIT,
    ) -> None:
        self._buffers: dict[str, HistoryBuffer] = {}
        self._limits = limits if limits is not None else DEFAULT_LIMITS
        self._default_limit = default_limit

    def _get_buffer(self, event_type: str) -> HistoryBuffer:
        if event_type not in self._buffers:
            maxlen = self._limits.get(event_type, self._default_limit)
            self._buffers[event_type] = HistoryBuffer(maxlen)
        return self._buffers[event_type]

    def record(
        self,
        event_type: str,
        summary: str,
        data: dict[str, Any],
        timestamp: str | None = None,
    ) -> None:
        entry = {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "summary": summary,
            "data": data,
        }
        self._get_buffer(event_type).append(entry)

    def get(self, event_type: str) -> list[dict[str, Any]]:
        if event_type not in self._buffers:
            return []
        return self._buffers[event_type].as_list()

    def all_entries(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for buf in self._buffers.values():
            result.extend(buf.as_list())
        result.sort(key=lambda e: e.get("timestamp", ""))
        return result

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {etype: buf.as_list() for etype, buf in self._buffers.items()}

    def load_dict(self, data: dict[str, list[dict[str, Any]]]) -> None:
        for event_type, entries in data.items():
            buf = self._get_buffer(event_type)
            for entry in entries:
                buf.append(entry)


class HistoryStore:
    """Multi-account history store with persistence support."""

    def __init__(
        self,
        limits: dict[str, int] | None = None,
        default_limit: int = DEFAULT_LIMIT,
    ) -> None:
        self._accounts: dict[str, AccountHistory] = {}
        self._limits = limits if limits is not None else DEFAULT_LIMITS
        self._default_limit = default_limit

    def get_or_create(self, account_key: str) -> AccountHistory:
        if account_key not in self._accounts:
            self._accounts[account_key] = AccountHistory(
                self._limits, self._default_limit
            )
        return self._accounts[account_key]

    def rename(self, old_key: str, new_key: str) -> None:
        """Move *old_key*'s history under *new_key* (e.g. after a name change).

        If *new_key* already has history the two are merged per event type,
        oldest first, keeping the newest entries within each buffer limit.
        """
        if old_key == new_key or old_key not in self._accounts:
            return
        old = self._accounts.pop(old_key)
        existing = self._accounts.get(new_key)
        if existing is None:
            self._accounts[new_key] = old
            return
        merged = AccountHistory(self._limits, self._default_limit)
        old_data = old.to_dict()
        new_data = existing.to_dict()
        for event_type in {*old_data, *new_data}:
            entries = old_data.get(event_type, []) + new_data.get(event_type, [])
            entries.sort(key=lambda e: e.get("timestamp", ""))
            merged.load_dict({event_type: entries})
        self._accounts[new_key] = merged

    def to_dict(self) -> dict[str, Any]:
        return {
            key: hist.to_dict() for key, hist in self._accounts.items()
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        for account_key, history_data in data.items():
            hist = self.get_or_create(account_key)
            hist.load_dict(history_data)
