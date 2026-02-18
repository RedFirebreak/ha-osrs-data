"""Tests for the pairing and device token management module."""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock, patch

# Mock homeassistant before imports
for mod_name in (
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.components.sensor",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_data.pairing import (  # noqa: E402
    PairedDevice,
    PairingStore,
    _generate_device_token,
    _generate_pairing_code,
    _hash_token,
)
from custom_components.osrs_data.const import (  # noqa: E402
    PAIRING_CODE_LENGTH,
    DEVICE_TOKEN_LENGTH,
)


class TestGeneratePairingCode:
    def test_code_length(self):
        code = _generate_pairing_code()
        assert len(code) == PAIRING_CODE_LENGTH

    def test_code_is_numeric(self):
        code = _generate_pairing_code()
        assert code.isdigit()

    def test_codes_are_unique(self):
        codes = {_generate_pairing_code() for _ in range(100)}
        # 100 random 6-digit codes: collisions are possible but very rare
        assert len(codes) >= 90


class TestGenerateDeviceToken:
    def test_token_length(self):
        token = _generate_device_token()
        assert len(token) == DEVICE_TOKEN_LENGTH

    def test_token_is_hex(self):
        token = _generate_device_token()
        int(token, 16)  # Should not raise

    def test_tokens_are_unique(self):
        tokens = {_generate_device_token() for _ in range(50)}
        assert len(tokens) == 50


class TestHashToken:
    def test_same_token_same_hash(self):
        h1 = _hash_token("my_token_123")
        h2 = _hash_token("my_token_123")
        assert h1 == h2

    def test_different_tokens_different_hashes(self):
        h1 = _hash_token("token_a")
        h2 = _hash_token("token_b")
        assert h1 != h2

    def test_hash_is_sha256_hex(self):
        h = _hash_token("test")
        assert len(h) == 64
        int(h, 16)  # Should not raise


class TestPairedDevice:
    def test_creation(self):
        device = PairedDevice("dev1", "hash123", "My Plugin")
        assert device.device_id == "dev1"
        assert device.token_hash == "hash123"
        assert device.name == "My Plugin"
        assert device.created_at is not None

    def test_to_dict(self):
        device = PairedDevice("dev1", "hash123", "My Plugin", created_at=1000.0)
        data = device.to_dict()
        assert data["device_id"] == "dev1"
        assert data["token_hash"] == "hash123"
        assert data["name"] == "My Plugin"
        assert data["created_at"] == 1000.0

    def test_from_dict(self):
        data = {
            "device_id": "dev1",
            "token_hash": "hash123",
            "name": "My Plugin",
            "created_at": 1000.0,
        }
        device = PairedDevice.from_dict(data)
        assert device.device_id == "dev1"
        assert device.token_hash == "hash123"
        assert device.name == "My Plugin"
        assert device.created_at == 1000.0

    def test_roundtrip(self):
        device = PairedDevice("dev1", "hash123", "My Plugin", created_at=1000.0)
        restored = PairedDevice.from_dict(device.to_dict())
        assert restored.device_id == device.device_id
        assert restored.token_hash == device.token_hash
        assert restored.name == device.name
        assert restored.created_at == device.created_at


class TestPairingStore:
    def test_create_pairing_code(self):
        store = PairingStore()
        code = store.create_pairing_code("Test Device")
        assert len(code) == PAIRING_CODE_LENGTH
        assert code.isdigit()

    def test_consume_valid_code(self):
        store = PairingStore()
        code = store.create_pairing_code("Test Device")
        result = store.consume_pairing_code(code)
        assert result is not None
        assert "device_id" in result
        assert "token" in result
        assert result["name"] == "Test Device"

    def test_consume_invalid_code(self):
        store = PairingStore()
        result = store.consume_pairing_code("999999")
        assert result is None

    def test_consume_code_twice(self):
        """Pairing codes are one-time use."""
        store = PairingStore()
        code = store.create_pairing_code()
        result1 = store.consume_pairing_code(code)
        result2 = store.consume_pairing_code(code)
        assert result1 is not None
        assert result2 is None

    def test_expired_code_rejected(self):
        """Expired codes cannot be consumed."""
        store = PairingStore()
        code = store.create_pairing_code()
        # Manually expire the code
        for info in store._pending_codes.values():
            info["expires_at"] = time.time() - 1
        result = store.consume_pairing_code(code)
        assert result is None

    def test_validate_token_after_pairing(self):
        store = PairingStore()
        code = store.create_pairing_code()
        result = store.consume_pairing_code(code)
        assert result is not None
        device_id = store.validate_token(result["token"])
        assert device_id == result["device_id"]

    def test_validate_invalid_token(self):
        store = PairingStore()
        assert store.validate_token("invalid_token_here") is None

    def test_revoke_device(self):
        store = PairingStore()
        code = store.create_pairing_code()
        result = store.consume_pairing_code(code)
        assert result is not None
        assert store.revoke_device(result["device_id"]) is True
        # Token should no longer be valid
        assert store.validate_token(result["token"]) is None

    def test_revoke_nonexistent_device(self):
        store = PairingStore()
        assert store.revoke_device("nonexistent") is False

    def test_list_devices(self):
        store = PairingStore()
        code1 = store.create_pairing_code("Device A")
        code2 = store.create_pairing_code("Device B")
        store.consume_pairing_code(code1)
        store.consume_pairing_code(code2)
        devices = store.list_devices()
        assert len(devices) == 2
        names = {d["name"] for d in devices}
        assert names == {"Device A", "Device B"}
        # Token hashes should NOT be exposed
        for d in devices:
            assert "token_hash" not in d

    def test_list_devices_after_revoke(self):
        store = PairingStore()
        code = store.create_pairing_code("Device A")
        result = store.consume_pairing_code(code)
        assert len(store.list_devices()) == 1
        store.revoke_device(result["device_id"])
        assert len(store.list_devices()) == 0

    def test_multiple_codes_independent(self):
        """Multiple pairing codes can exist simultaneously."""
        store = PairingStore()
        code1 = store.create_pairing_code("Device A")
        code2 = store.create_pairing_code("Device B")
        assert code1 != code2
        result1 = store.consume_pairing_code(code1)
        result2 = store.consume_pairing_code(code2)
        assert result1 is not None
        assert result2 is not None
        assert result1["device_id"] != result2["device_id"]

    def test_persistence_roundtrip(self):
        """Paired devices survive serialization."""
        store = PairingStore()
        code = store.create_pairing_code("Test Device")
        result = store.consume_pairing_code(code)
        assert result is not None

        data = store.to_dict()
        store2 = PairingStore()
        store2.load_dict(data)

        # The device should be restored
        assert len(store2.list_devices()) == 1
        assert store2.list_devices()[0]["name"] == "Test Device"
        # The token should still work
        assert store2.validate_token(result["token"]) == result["device_id"]

    def test_persistence_empty_store(self):
        store = PairingStore()
        data = store.to_dict()
        assert data == []
        store2 = PairingStore()
        store2.load_dict(data)
        assert len(store2.list_devices()) == 0

    def test_pending_codes_not_persisted(self):
        """Pending pairing codes should NOT be persisted (they are ephemeral)."""
        store = PairingStore()
        store.create_pairing_code("Device A")
        data = store.to_dict()
        # Pending codes are not in the serialized output
        assert data == []
