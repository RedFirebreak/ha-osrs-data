"""HTTP API views for the OSRS Data integration.

Provides:
  POST /api/osrs-data/pair         — consume a pairing code and receive a device token
  POST /api/osrs-data/events       — submit event data (authenticated via X-Osrs-Token)
  GET  /api/osrs-data/devices      — list paired devices
  DELETE /api/osrs-data/devices/{device_id} — revoke a paired device
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from homeassistant.core import HomeAssistant
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DOMAIN,
    EVENT_TYPE,
    DATA_ACCOUNT_STORE,
    DATA_HISTORY_STORE,
    DATA_DEDUPE_CACHE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    SIGNAL_ACCOUNT_UPDATED,
)
from .parser.dispatcher import dispatch as dispatch_parser
from .webhook import (
    _build_normalized_event,
    _extract_image_metadata,
    _get_file_size,
    _build_save_payload,
    _SAVE_DELAY,
)

_LOGGER = logging.getLogger(__name__)

_TOKEN_HEADER = "X-Osrs-Token"


def _get_entry_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Get the first (and typically only) entry data dict."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_id, entry_data in domain_data.items():
        if isinstance(entry_data, dict):
            return entry_data
    return None


def _schedule_save(entry_data: dict[str, Any]) -> None:
    """Schedule a deferred write of all data to disk."""
    store = entry_data.get(DATA_STORE)
    if store is None:
        return
    store.async_delay_save(lambda: _build_save_payload(entry_data), _SAVE_DELAY)


class OsrsPairView(HomeAssistantView):
    """Handle pairing requests from RuneLite clients."""

    url = "/api/osrs-data/pair"
    name = "api:osrs-data:pair"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Consume a pairing code and issue a device token."""
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return self.json({"ok": False, "error": "Invalid JSON"}, status_code=400)

        code = body.get("code", "").strip()
        if not code:
            return self.json({"ok": False, "error": "Missing pairing code"}, status_code=400)

        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"ok": False, "error": "Integration not configured"}, status_code=503)

        pairing_store = entry_data.get(DATA_PAIRING_STORE)
        if pairing_store is None:
            return self.json({"ok": False, "error": "Pairing not available"}, status_code=503)

        result = pairing_store.consume_pairing_code(code)
        if result is None:
            return self.json({"ok": False, "error": "Invalid or expired pairing code"}, status_code=403)

        # Persist the new device
        _schedule_save(entry_data)

        return self.json({
            "ok": True,
            "device_id": result["device_id"],
            "token": result["token"],
        })


class OsrsEventsView(HomeAssistantView):
    """Handle event submissions from paired RuneLite clients."""

    url = "/api/osrs-data/events"
    name = "api:osrs-data:events"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Process an event submission."""
        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"ok": False, "error": "Integration not configured"}, status_code=503)

        # Authenticate via device token
        token = request.headers.get(_TOKEN_HEADER, "").strip()
        if not token:
            return self.json({"ok": False, "error": "Missing authentication token"}, status_code=401)

        pairing_store = entry_data.get(DATA_PAIRING_STORE)
        if pairing_store is None:
            return self.json({"ok": False, "error": "Pairing not available"}, status_code=503)

        device_id = pairing_store.validate_token(token)
        if device_id is None:
            return self.json({"ok": False, "error": "Invalid or revoked token"}, status_code=403)

        try:
            content_type = request.headers.get("Content-Type", "")
            payload: dict[str, Any] = {}
            image_meta: dict[str, Any] | None = None

            if "multipart/form-data" in content_type:
                form = await request.post()
                raw = form.get("payload_json")
                if raw:
                    payload = json.loads(raw)
                file_field = form.get("file")
                image_meta = _extract_image_metadata(file_field)
                if (
                    image_meta is not None
                    and hasattr(file_field, "file")
                    and file_field.file
                ):
                    image_meta["size"] = await hass.async_add_executor_job(
                        _get_file_size, file_field.file
                    )
            else:
                payload = await request.json()

            event_data = _build_normalized_event(payload, image_meta)

            event_type = payload.get("type", "UNKNOWN")
            extra = payload.get("extra", {})
            player_name = payload.get("playerName", "Unknown")
            account_hash = payload.get("dinkAccountHash")
            account_id = account_hash or player_name
            if not account_hash:
                _LOGGER.debug("No dinkAccountHash; using playerName as account key")

            parsed = dispatch_parser(event_type, extra, player_name)

            if parsed is not None:
                # Dedupe check
                dedupe = entry_data.get(DATA_DEDUPE_CACHE)
                if dedupe is not None and dedupe.is_duplicate(
                    account_id, event_type, extra
                ):
                    _LOGGER.debug(
                        "Dropping duplicate event %s for %s", event_type, account_id
                    )
                    return self.json({"ok": True, "duplicate": True})

                store = entry_data.get(DATA_ACCOUNT_STORE)
                if store is not None:
                    acct = store.get_or_create(account_hash, player_name)
                    acct.record_event(
                        event_type,
                        parsed["summary"],
                        parsed["data"],
                        player_name=player_name,
                    )

                    # Record to history buffer
                    history_store = entry_data.get(DATA_HISTORY_STORE)
                    if history_store is not None:
                        hist = history_store.get_or_create(account_id)
                        hist.record(event_type, parsed["summary"], parsed["data"])

                    async_dispatcher_send(
                        hass, SIGNAL_ACCOUNT_UPDATED, acct.account_hash
                    )

                    _schedule_save(entry_data)

            hass.bus.async_fire(EVENT_TYPE, event_data)

            return self.json({"ok": True})
        except Exception as exc:
            _LOGGER.exception("Event handling failed: %s", exc)
            return self.json({"ok": False, "error": str(exc)}, status_code=500)


class OsrsDevicesView(HomeAssistantView):
    """List paired devices."""

    url = "/api/osrs-data/devices"
    name = "api:osrs-data:devices"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return all paired devices."""
        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"ok": False, "error": "Integration not configured"}, status_code=503)

        pairing_store = entry_data.get(DATA_PAIRING_STORE)
        if pairing_store is None:
            return self.json({"ok": False, "error": "Pairing not available"}, status_code=503)

        return self.json({"ok": True, "devices": pairing_store.list_devices()})


class OsrsDeviceRevokeView(HomeAssistantView):
    """Revoke a specific paired device."""

    url = "/api/osrs-data/devices/{device_id}"
    name = "api:osrs-data:devices:revoke"
    requires_auth = True

    async def delete(self, request: web.Request, device_id: str) -> web.Response:
        """Revoke a paired device by its ID."""
        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"ok": False, "error": "Integration not configured"}, status_code=503)

        pairing_store = entry_data.get(DATA_PAIRING_STORE)
        if pairing_store is None:
            return self.json({"ok": False, "error": "Pairing not available"}, status_code=503)

        if pairing_store.revoke_device(device_id):
            _schedule_save(entry_data)
            return self.json({"ok": True})
        return self.json({"ok": False, "error": "Device not found"}, status_code=404)
