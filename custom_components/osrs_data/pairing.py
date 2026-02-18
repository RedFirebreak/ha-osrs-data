"""Pairing and device token management for the OSRS Data integration."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from typing import Any

from .const import PAIRING_CODE_LENGTH, PAIRING_CODE_TTL, DEVICE_TOKEN_LENGTH

_LOGGER = logging.getLogger(__name__)


def _generate_pairing_code() -> str:
    """Generate a random 6-digit numeric pairing code."""
    return "".join([str(secrets.randbelow(10)) for _ in range(PAIRING_CODE_LENGTH)])


def _generate_device_token() -> str:
    """Generate a cryptographically secure device token."""
    return secrets.token_hex(DEVICE_TOKEN_LENGTH // 2)


def _hash_token(token: str) -> str:
    """Hash a device token for safe storage."""
    return hashlib.sha256(token.encode()).hexdigest()


class PairedDevice:
    """Represents a paired RuneLite client device."""

    def __init__(
        self,
        device_id: str,
        token_hash: str,
        name: str = "",
        created_at: float | None = None,
    ) -> None:
        self.device_id = device_id
        self.token_hash = token_hash
        self.name = name
        self.created_at = created_at or time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the device for persistence."""
        return {
            "device_id": self.device_id,
            "token_hash": self.token_hash,
            "name": self.name,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PairedDevice:
        """Restore a device from persisted data."""
        return cls(
            device_id=data["device_id"],
            token_hash=data["token_hash"],
            name=data.get("name", ""),
            created_at=data.get("created_at"),
        )


class PairingStore:
    """Manages pairing codes and paired devices."""

    def __init__(self) -> None:
        # Active pairing codes: code -> {expires_at, device_name}
        self._pending_codes: dict[str, dict[str, Any]] = {}
        # Paired devices: device_id -> PairedDevice
        self._devices: dict[str, PairedDevice] = {}
        # Token hash -> device_id (for fast lookup during auth)
        self._token_index: dict[str, str] = {}

    def create_pairing_code(self, device_name: str = "") -> str:
        """Generate a new pairing code and return it.

        The code expires after PAIRING_CODE_TTL seconds.
        """
        self._evict_expired_codes()
        code = _generate_pairing_code()
        # Ensure uniqueness
        while code in self._pending_codes:
            code = _generate_pairing_code()
        self._pending_codes[code] = {
            "expires_at": time.time() + PAIRING_CODE_TTL,
            "device_name": device_name,
        }
        _LOGGER.info("Pairing code created (expires in %ds)", PAIRING_CODE_TTL)
        return code

    def consume_pairing_code(self, code: str) -> dict[str, Any] | None:
        """Validate and consume a pairing code.

        Returns the new device info with the raw token if valid, None otherwise.
        """
        self._evict_expired_codes()
        pending = self._pending_codes.pop(code, None)
        if pending is None:
            _LOGGER.warning("Invalid or expired pairing code attempted")
            return None

        raw_token = _generate_device_token()
        token_hash = _hash_token(raw_token)
        device_id = secrets.token_hex(8)
        device_name = pending.get("device_name", "")

        device = PairedDevice(
            device_id=device_id,
            token_hash=token_hash,
            name=device_name,
        )
        self._devices[device_id] = device
        self._token_index[token_hash] = device_id

        _LOGGER.info("Device %s paired successfully", device_id)
        return {
            "device_id": device_id,
            "token": raw_token,
            "name": device_name,
        }

    def validate_token(self, token: str) -> str | None:
        """Validate a device token and return the device_id, or None."""
        token_hash = _hash_token(token)
        return self._token_index.get(token_hash)

    def revoke_device(self, device_id: str) -> bool:
        """Remove a paired device and invalidate its token."""
        device = self._devices.pop(device_id, None)
        if device is None:
            return False
        self._token_index.pop(device.token_hash, None)
        _LOGGER.info("Device %s revoked", device_id)
        return True

    def list_devices(self) -> list[dict[str, Any]]:
        """Return a list of all paired devices (without token hashes)."""
        return [
            {
                "device_id": d.device_id,
                "name": d.name,
                "created_at": d.created_at,
            }
            for d in self._devices.values()
        ]

    def _evict_expired_codes(self) -> None:
        """Remove expired pairing codes."""
        now = time.time()
        expired = [
            code
            for code, info in self._pending_codes.items()
            if info["expires_at"] <= now
        ]
        for code in expired:
            del self._pending_codes[code]

    def inject_pending_code(
        self, code: str, device_name: str, expires_at: float
    ) -> None:
        """Inject a pending pairing code created externally (e.g. during config flow)."""
        self._pending_codes[code] = {
            "expires_at": expires_at,
            "device_name": device_name,
        }

    def to_dict(self) -> list[dict[str, Any]]:
        """Serialize all paired devices for persistence."""
        return [d.to_dict() for d in self._devices.values()]

    def load_dict(self, data: list[dict[str, Any]]) -> None:
        """Restore paired devices from persisted data."""
        for device_data in data:
            device = PairedDevice.from_dict(device_data)
            self._devices[device.device_id] = device
            self._token_index[device.token_hash] = device.device_id
