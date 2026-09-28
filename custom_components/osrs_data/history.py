"""Persistent per-account, per-event-type history ring buffers.

History is keyed by the immutable account key (``AccountState.account_hash``),
so it follows an account through name changes.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .account_store import _normalize_player_name

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

    def to_dict(self) -> dict[str, Any]:
        return {
            key: hist.to_dict() for key, hist in self._accounts.items()
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        for account_key, history_data in data.items():
            hist = self.get_or_create(account_key)
            hist.load_dict(history_data)


def rekey_history(
    history: dict[str, Any], accounts: list[dict[str, Any]]
) -> dict[str, Any]:
    """Re-key stored history from display names to account keys.

    Storage before 2.2 keyed history by the account's display name.  Each
    name is matched (case-insensitively) to the stored account that
    currently has it; history for names no account has any more is kept
    under its old key.  Entries that end up under the same key are merged
    per event type, oldest first (buffer limits are applied on load).
    """
    key_by_name: dict[str, str] = {}
    for acct in accounts:
        if not isinstance(acct, dict):
            continue
        name = acct.get("player_name", "Unknown")
        if not isinstance(name, str):
            continue
        norm = _normalize_player_name(name)
        # Same key rule as AccountStore.load_dict; later accounts win a
        # shared name, like the name index there.
        key_by_name[norm] = acct.get("account_hash") or norm

    result: dict[str, Any] = {}
    for old_key, per_type in history.items():
        if not isinstance(per_type, dict):
            continue
        new_key = old_key
        if isinstance(old_key, str):
            new_key = key_by_name.get(_normalize_player_name(old_key), old_key)
        merged = result.setdefault(new_key, {})
        for event_type, entries in per_type.items():
            if not isinstance(entries, list):
                continue
            combined = merged.get(event_type, []) + entries
            combined.sort(key=lambda e: e.get("timestamp", "") if isinstance(e, dict) else "")
            merged[event_type] = combined
    return result
