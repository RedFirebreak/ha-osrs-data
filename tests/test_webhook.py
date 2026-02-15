"""Tests for the OSRS Webhook normalized event pipeline."""

from __future__ import annotations

import importlib
import io
import json
import os
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock homeassistant packages before importing the integration
for mod_name in (
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.webhook",
    "homeassistant.helpers",
    "homeassistant.helpers.webhook",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
):
    sys.modules.setdefault(mod_name, MagicMock())

# Import custom_components.osrs_webhook as a proper package
_root = os.path.join(os.path.dirname(__file__), "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from custom_components.osrs_webhook.webhook import (  # noqa: E402
    _build_normalized_event,
    _extract_image_metadata,
    _get_file_size,
    _handle_webhook,
)


# ── Sample payloads ──────────────────────────────────────────────────

LEVEL_PAYLOAD: dict[str, Any] = {
    "content": "PlayerOne has levelled Attack to 70",
    "extra": {
        "levelledSkills": {"Attack": 70},
        "allSkills": {"Attack": 70, "Strength": 60},
        "combatLevel": {"value": 85, "increased": True},
    },
    "type": "LEVEL",
    "playerName": "PlayerOne",
    "accountType": "NORMAL",
    "seasonalWorld": False,
    "dinkAccountHash": "abc123def456ghi789",
    "world": 518,
    "regionId": 12850,
    "embeds": [{"image": {"url": "attachment://screenshot.png"}}],
}

MINIMAL_PAYLOAD: dict[str, Any] = {
    "type": "DEATH",
    "playerName": "TestUser",
    "accountType": "IRONMAN",
    "dinkAccountHash": "hash123",
    "extra": {"valueLost": 300, "isPvp": False},
}


# ── Tests for _build_normalized_event ────────────────────────────────


class TestBuildNormalizedEvent:
    """Tests for building the normalized event dict."""

    def test_full_payload_with_image(self):
        """LEVEL payload with world, regionId, and image metadata."""
        image_meta = {
            "filename": "screenshot.png",
            "content_type": "image/png",
            "size": 102400,
        }
        result = _build_normalized_event(LEVEL_PAYLOAD, image_meta)

        assert result["event_type"] == "LEVEL"
        assert result["account"]["playerName"] == "PlayerOne"
        assert result["account"]["accountType"] == "NORMAL"
        assert result["account"]["dinkAccountHash"] == "abc123def456ghi789"
        assert result["account"]["seasonalWorld"] is False
        assert result["data"] == LEVEL_PAYLOAD["extra"]
        assert result["raw_meta"]["world"] == 518
        assert result["raw_meta"]["regionId"] == 12850
        assert result["image"] == image_meta
        # received_at should be a valid ISO timestamp
        datetime.fromisoformat(result["received_at"])

    def test_minimal_payload_no_image(self):
        """Payload without world/regionId/image."""
        result = _build_normalized_event(MINIMAL_PAYLOAD, None)

        assert result["event_type"] == "DEATH"
        assert result["account"]["playerName"] == "TestUser"
        assert result["account"]["accountType"] == "IRONMAN"
        assert result["account"]["dinkAccountHash"] == "hash123"
        assert result["account"]["seasonalWorld"] is None
        assert result["data"]["valueLost"] == 300
        assert result["raw_meta"] == {}
        assert "image" not in result

    def test_empty_payload(self):
        """Completely empty payload still produces a valid event."""
        result = _build_normalized_event({}, None)

        assert result["event_type"] == "UNKNOWN"
        assert result["account"]["playerName"] is None
        assert result["data"] == {}
        assert result["raw_meta"] == {}
        assert "image" not in result

    def test_no_embeds_dependency(self):
        """Normalized event does not depend on embeds at all."""
        result = _build_normalized_event(LEVEL_PAYLOAD, None)
        # The normalized event should not contain embeds or content
        assert "embeds" not in result
        assert "content" not in result

    def test_received_at_is_utc(self):
        """received_at timestamp should be UTC."""
        result = _build_normalized_event(MINIMAL_PAYLOAD, None)
        ts = datetime.fromisoformat(result["received_at"])
        assert ts.tzinfo is not None


# ── Tests for _extract_image_metadata ────────────────────────────────


class TestExtractImageMetadata:
    """Tests for extracting image metadata from file fields."""

    def test_none_returns_none(self):
        assert _extract_image_metadata(None) is None

    def test_file_field_with_data(self):
        """Simulate an aiohttp FileField-like object."""
        file_data = b"\x89PNG" + b"\x00" * 1024
        file_field = SimpleNamespace(
            filename="screenshot.png",
            content_type="image/png",
            file=io.BytesIO(file_data),
        )
        result = _extract_image_metadata(file_field)

        assert result is not None
        assert result["filename"] == "screenshot.png"
        assert result["content_type"] == "image/png"
        # size is resolved asynchronously via hass.async_add_executor_job
        assert result["size"] is None

    def test_get_file_size(self):
        """_get_file_size correctly measures file size via seek/tell."""
        file_data = b"\x89PNG" + b"\x00" * 512
        file_obj = io.BytesIO(file_data)
        size = _get_file_size(file_obj)
        assert size == len(file_data)
        # cursor should be reset to start
        assert file_obj.tell() == 0

    def test_file_field_without_file_attribute(self):
        """Object without a .file attribute."""
        file_field = SimpleNamespace(
            filename="img.jpg",
            content_type="image/jpeg",
        )
        result = _extract_image_metadata(file_field)

        assert result is not None
        assert result["filename"] == "img.jpg"
        assert result["size"] is None


# ── Tests for _handle_webhook (async handler) ────────────────────────


class TestHandleWebhook:
    """Integration-level tests for the webhook handler."""

    @pytest.fixture
    def mock_hass(self):
        hass = MagicMock()
        hass.bus = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
        return hass

    def _make_multipart_request(
        self,
        payload: dict[str, Any],
        file_field=None,
    ):
        """Create a mock request with multipart/form-data."""
        form = {
            "payload_json": json.dumps(payload),
        }
        if file_field is not None:
            form["file"] = file_field

        request = MagicMock()
        request.headers = {"Content-Type": "multipart/form-data; boundary=----"}
        request.post = AsyncMock(return_value=form)
        return request

    def _make_json_request(self, payload: dict[str, Any]):
        """Create a mock request with application/json."""
        request = MagicMock()
        request.headers = {"Content-Type": "application/json"}
        request.json = AsyncMock(return_value=payload)
        return request

    @pytest.mark.asyncio
    async def test_multipart_level_payload(self, mock_hass):
        """Full LEVEL multipart with payload_json fires normalized event."""
        request = self._make_multipart_request(LEVEL_PAYLOAD)
        result = await _handle_webhook(mock_hass, "test-id", request)

        assert result == {"ok": True}
        mock_hass.bus.async_fire.assert_called_once()
        event_name, event_data = mock_hass.bus.async_fire.call_args[0]
        assert event_name == "osrs_webhook_event"
        assert event_data["event_type"] == "LEVEL"
        assert event_data["account"]["playerName"] == "PlayerOne"
        assert event_data["data"] == LEVEL_PAYLOAD["extra"]

    @pytest.mark.asyncio
    async def test_multipart_with_file(self, mock_hass):
        """Multipart with file attachment includes image metadata."""
        file_data = b"\x89PNG" + b"\x00" * 512
        file_field = SimpleNamespace(
            filename="screenshot.png",
            content_type="image/png",
            file=io.BytesIO(file_data),
        )
        request = self._make_multipart_request(LEVEL_PAYLOAD, file_field)
        result = await _handle_webhook(mock_hass, "test-id", request)

        assert result == {"ok": True}
        event_data = mock_hass.bus.async_fire.call_args[0][1]
        assert "image" in event_data
        assert event_data["image"]["filename"] == "screenshot.png"
        assert event_data["image"]["size"] == len(file_data)

    @pytest.mark.asyncio
    async def test_json_fallback(self, mock_hass):
        """JSON request is handled as fallback."""
        request = self._make_json_request(MINIMAL_PAYLOAD)
        result = await _handle_webhook(mock_hass, "test-id", request)

        assert result == {"ok": True}
        event_data = mock_hass.bus.async_fire.call_args[0][1]
        assert event_data["event_type"] == "DEATH"
        assert event_data["account"]["playerName"] == "TestUser"

    @pytest.mark.asyncio
    async def test_error_returns_ok_false(self, mock_hass):
        """On error, return {ok: false} without crashing."""
        request = MagicMock()
        request.headers = {"Content-Type": "application/json"}
        request.json = AsyncMock(side_effect=ValueError("bad json"))

        result = await _handle_webhook(mock_hass, "test-id", request)

        assert result["ok"] is False
        assert "error" in result
        mock_hass.bus.async_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_multipart_empty_payload_json(self, mock_hass):
        """Multipart with missing payload_json field still works."""
        request = MagicMock()
        request.headers = {"Content-Type": "multipart/form-data; boundary=----"}
        request.post = AsyncMock(return_value={})

        result = await _handle_webhook(mock_hass, "test-id", request)

        assert result == {"ok": True}
        event_data = mock_hass.bus.async_fire.call_args[0][1]
        assert event_data["event_type"] == "UNKNOWN"
