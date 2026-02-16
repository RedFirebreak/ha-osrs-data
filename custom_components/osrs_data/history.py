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

    def __init__(self) -> None:
        self._buffers: dict[str, HistoryBuffer] = {}

    def _get_buffer(self, event_type: str) -> HistoryBuffer:
        if event_type not in self._buffers:
            maxlen = DEFAULT_LIMITS.get(event_type, DEFAULT_LIMIT)
            self._buffers[event_type] = HistoryBuffer(maxlen)
        return self._buffers[event_type]

    def record(
        self,
        event_type: str,
        summary: str,
        data: dict[str, Any],
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
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

    def __init__(self) -> None:
        self._accounts: dict[str, AccountHistory] = {}

    def get_or_create(self, account_key: str) -> AccountHistory:
        if account_key not in self._accounts:
            self._accounts[account_key] = AccountHistory()
        return self._accounts[account_key]

    def to_dict(self) -> dict[str, Any]:
        return {
            key: hist.to_dict() for key, hist in self._accounts.items()
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        for account_key, history_data in data.items():
            hist = self.get_or_create(account_key)
            hist.load_dict(history_data)
