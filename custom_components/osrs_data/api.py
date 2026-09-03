"""HTTP API views for the OSRS Data integration.

Provides:
  POST /api/osrs-data/pair         — consume a pairing code and receive a device token
  POST /api/osrs-data/events       — submit player data (authenticated via X-Osrs-Token)
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
    DATA_EVENT_DEDUPE_CACHE,
    DATA_PAIRING_STORE,
    DATA_STORE,
    PAIRING_CODE_TTL,
    SIGNAL_ACCOUNT_UPDATED,
)
from .parser.base import parse as parse_player_data

_LOGGER = logging.getLogger(__name__)

# Delay (in seconds) before writing state to disk after a change.
_SAVE_DELAY = 5

_TOKEN_HEADER = "X-Osrs-Token"


def _build_save_payload(entry_data: dict[str, Any]) -> dict[str, Any]:
    """Build the storage payload from current entry data."""
    save_data: dict[str, Any] = {}
    history_store = entry_data.get(DATA_HISTORY_STORE)
    if history_store is not None:
        save_data["history"] = history_store.to_dict()
    acct_store = entry_data.get(DATA_ACCOUNT_STORE)
    if acct_store is not None:
        save_data["accounts"] = acct_store.to_dict()
    pairing_store = entry_data.get(DATA_PAIRING_STORE)
    if pairing_store is not None:
        save_data["paired_devices"] = pairing_store.to_dict()
    return save_data


def _build_normalized_event(parsed: dict[str, Any]) -> dict[str, Any]:
    """Build a normalized event dict for the Home Assistant event bus."""
    return {
        "player_name": parsed.get("name"),
        "account_type": parsed.get("accountType"),
        "world": parsed.get("world"),
        "state": parsed.get("state", "UNKNOWN"),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "events": parsed.get("events", []),
    }


def _summarize_event(event_type: str, data: dict[str, Any]) -> str:
    """Build a short human-readable summary for a history entry."""
    if event_type == "DEATH":
        killer = data.get("killerName") or "unknown"
        lost = data.get("valueLost", 0)
        return f"Died to {killer} (-{lost} gp)"
    if event_type in ("LOOT", "PKLOOT"):
        source = data.get("source")
        src_text = source.get("text") if isinstance(source, dict) else None
        total = data.get("totalValue", 0)
        return f"{total} gp from {src_text or 'unknown source'}"
    if event_type == "LEVELUP":
        skill = data.get("skill")
        level = data.get("level")
        if skill is not None:
            return f"{skill} reached level {level}"
    name = data.get("name")
    if name:
        return f"{event_type}: {name}"
    return event_type


def _get_entry_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Get the first (and typically only) entry data dict.

    Skips internal keys (prefixed with ``_``) that we store under
    ``hass.data[DOMAIN]`` for bookkeeping (e.g. ``_pending_pairings``).
    """
    domain_data = hass.data.get(DOMAIN, {})
    for entry_id, entry_data in domain_data.items():
        if isinstance(entry_id, str) and entry_id.startswith("_"):
            continue
        if isinstance(entry_data, dict):
            return entry_data
    return None


def _schedule_save(entry_data: dict[str, Any]) -> None:
    """Schedule a deferred write of all data to disk."""
    store = entry_data.get(DATA_STORE)
    if store is None:
        return
    store.async_delay_save(lambda: _build_save_payload(entry_data), _SAVE_DELAY)


class OsrsPairCodeView(HomeAssistantView):
    """Generate a pairing code (HA-authenticated, for the HA frontend/admin)."""

    url = "/api/osrs-data/pair/code"
    name = "api:osrs-data:pair:code"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Create a new pairing code for a RuneLite client."""
        hass: HomeAssistant = request.app["hass"]
        entry_data = _get_entry_data(hass)
        if entry_data is None:
            return self.json({"ok": False, "error": "Integration not configured"}, status_code=503)

        pairing_store = entry_data.get(DATA_PAIRING_STORE)
        if pairing_store is None:
            return self.json({"ok": False, "error": "Pairing not available"}, status_code=503)

        try:
            body = await request.json()
        except Exception:
            body = {}

        device_name = body.get("device_name", "RuneLite Client") if body else "RuneLite Client"

        code = pairing_store.create_pairing_code(device_name)

        return self.json({
            "ok": True,
            "code": code,
            "expires_in": PAIRING_CODE_TTL,
        })


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

        # 1. Try per-entry pairing stores first (the common path)
        entry_data = _get_entry_data(hass)
        live_pairing = (
            entry_data.get(DATA_PAIRING_STORE) if entry_data else None
        )

        if live_pairing is not None:
            result = live_pairing.consume_pairing_code(code)
            if result is not None:
                _schedule_save(entry_data)
                return self.json({
                    "ok": True,
                    "device_id": result["device_id"],
                    "token": result["token"],
                })

        # 2. Fall back to pending config-flow pairings (first-time setup)
        pending_pairings = hass.data.get(DOMAIN, {}).get("_pending_pairings", {})
        for _flow_id, pending in pending_pairings.items():
            temp_store = pending.get("store")
            if temp_store is not None:
                result = temp_store.consume_pairing_code(code)
                if result is not None:
                    pending["result"] = result
                    # Mirror the device into the live entry store so
                    # the token is valid immediately for /events.
                    if live_pairing is not None:
                        live_pairing.register_device(
                            result["device_id"],
                            result["token"],
                            result.get("name", ""),
                        )
                        _schedule_save(entry_data)
                    return self.json({
                        "ok": True,
                        "device_id": result["device_id"],
                        "token": result["token"],
                    })

        if entry_data is None:
            return self.json({"ok": False, "error": "Integration not configured"}, status_code=503)
        if live_pairing is None:
            return self.json({"ok": False, "error": "Pairing not available"}, status_code=503)

        return self.json({"ok": False, "error": "Invalid or expired pairing code"}, status_code=403)


class OsrsEventsView(HomeAssistantView):
    """Handle player data submissions from paired RuneLite clients."""

    url = "/api/osrs-data/events"
    name = "api:osrs-data:events"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Process a player data submission."""
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
            payload = await request.json()

            parsed = parse_player_data(payload)
            if parsed is None:
                return self.json({"ok": False, "error": "Invalid payload: missing player data"}, status_code=400)

            player_name = parsed["name"]
            account_id = player_name

            # Dedupe check
            dedupe = entry_data.get(DATA_DEDUPE_CACHE)
            if dedupe is not None and dedupe.is_duplicate(account_id, payload):
                _LOGGER.debug("Dropping duplicate data for %s", account_id)
                return self.json({"ok": True, "duplicate": True})

            # Use player name as account key (no hash in new format)
            store = entry_data.get(DATA_ACCOUNT_STORE)
            if store is not None:
                acct = store.get_or_create(None, player_name)
                acct.update_player_data(parsed, player_name=player_name)

                async_dispatcher_send(
                    hass, SIGNAL_ACCOUNT_UPDATED, acct.account_hash
                )

                _schedule_save(entry_data)

            event_data = _build_normalized_event(parsed)
            hass.bus.async_fire(EVENT_TYPE, event_data)

            # Fire individual HA events for each entry in the events list
            received_at = event_data["received_at"]
            event_dedupe = entry_data.get(DATA_EVENT_DEDUPE_CACHE)
            history_store = entry_data.get(DATA_HISTORY_STORE)
            events_list = parsed.get("events", [])
            for ev in events_list:
                if not isinstance(ev, dict):
                    continue
                ev_type = ev.get("type", "UNKNOWN").upper()
                # Per-event deduplication
                if event_dedupe is not None and event_dedupe.is_duplicate(
                    player_name, ev
                ):
                    continue
                # Fire the bus event with the raw data untouched so the
                # public event contract (list for LEVELUP, string for
                # CLIENTSHUTDOWN, dict for DEATH/LOOT) is preserved.
                ev_data = ev.get("data", {})
                hass.bus.async_fire(EVENT_TYPE, {
                    "account_name": player_name,
                    "event_type": ev_type,
                    "event_data": ev_data,
                    "received_at": received_at,
                })
                # Internal state + history want a dict; wrap non-dict data.
                ev_dict = ev_data if isinstance(ev_data, dict) else {"value": ev_data}
                # Update event totals + rich "last …" state
                if store is not None:
                    acct.record_game_event(ev_type, ev_dict)
                # Record the typed event into the per-account history buffer
                if history_store is not None:
                    history_store.get_or_create(account_id).record(
                        ev_type,
                        _summarize_event(ev_type, ev_dict),
                        ev_dict,
                    )

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
