from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiohttp.web import Response, json_response

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.webhook import async_register
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN, EVENT_TYPE, CONF_WEBHOOK_ID, DATA_ACCOUNT_STORE, DATA_HISTORY_STORE, DATA_DEDUPE_CACHE, DATA_PAIRING_STORE, DATA_STORE, SIGNAL_ACCOUNT_UPDATED
from .parser.dispatcher import dispatch as dispatch_parser

_LOGGER = logging.getLogger(__name__)

# Delay (in seconds) before writing state to disk after a change.
_SAVE_DELAY = 5


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


def _schedule_save(entry_data: dict[str, Any]) -> None:
    """Schedule a deferred write of history + account data to disk."""
    store = entry_data.get(DATA_STORE)
    if store is None:
        return
    store.async_delay_save(lambda: _build_save_payload(entry_data), _SAVE_DELAY)


def _build_normalized_event(
    payload: dict[str, Any],
    image_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a normalized event dict from a Dink webhook payload."""
    event: dict[str, Any] = {
        "event_type": payload.get("type", "UNKNOWN"),
        "account": {
            "playerName": payload.get("playerName"),
            "accountType": payload.get("accountType"),
            "dinkAccountHash": payload.get("dinkAccountHash"),
            "seasonalWorld": payload.get("seasonalWorld"),
        },
        "received_at": datetime.now(timezone.utc).isoformat(),
        "data": payload.get("extra", {}),
        "raw_meta": {},
    }

    if "world" in payload:
        event["raw_meta"]["world"] = payload["world"]
    if "regionId" in payload:
        event["raw_meta"]["regionId"] = payload["regionId"]

    if image_meta:
        event["image"] = image_meta

    return event


def _get_file_size(file_obj: Any) -> int:
    """Get file size by seeking (blocking I/O, run in executor)."""
    file_obj.seek(0, 2)
    size = file_obj.tell()
    file_obj.seek(0)
    return size


def _extract_image_metadata(file_field: Any) -> dict[str, Any] | None:
    """Extract basic metadata from an uploaded file field (no bytes persisted).

    Note: call _get_file_size via hass.async_add_executor_job for the size.
    """
    if file_field is None:
        return None

    return {
        "filename": getattr(file_field, "filename", None),
        "content_type": getattr(file_field, "content_type", None),
        "size": None,
    }


async def _handle_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    request,
) -> Any:
    """Handle incoming webhook calls from Dink/RuneLite.

    Dink sends multipart/form-data with:
      - payload_json: a JSON string
      - file: an image attachment (optional)

    A JSON fallback is kept for defensive compatibility.
    """
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
            if image_meta is not None and hasattr(file_field, "file") and file_field.file:
                image_meta["size"] = await hass.async_add_executor_job(
                    _get_file_size, file_field.file
                )
        else:
            payload = await request.json()

        event_data = _build_normalized_event(payload, image_meta)

        # Parse event and update account store
        event_type = payload.get("type", "UNKNOWN")
        extra = payload.get("extra", {})
        player_name = payload.get("playerName", "Unknown")
        account_hash = payload.get("dinkAccountHash")
        account_id = account_hash or player_name
        if not account_hash:
            _LOGGER.debug("No dinkAccountHash; using playerName as account key")

        parsed = dispatch_parser(event_type, extra, player_name)

        if parsed is not None:
            # Look up the correct entry data across all config entries
            for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
                if not isinstance(entry_data, dict):
                    continue

                # Dedupe check
                dedupe = entry_data.get(DATA_DEDUPE_CACHE)
                if dedupe is not None and dedupe.is_duplicate(account_id, event_type, extra):
                    _LOGGER.debug("Dropping duplicate event %s for %s", event_type, account_id)
                    return json_response({"ok": True, "duplicate": True})

                store = entry_data.get(DATA_ACCOUNT_STORE)
                if store is None:
                    continue
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

                # Schedule deferred save to persist state to disk
                _schedule_save(entry_data)

        # Fire event after dedupe so duplicate webhooks don't trigger automations
        hass.bus.async_fire(EVENT_TYPE, event_data)

        return json_response({"ok": True})
    except Exception as exc:
        _LOGGER.exception("Webhook handling failed: %s", exc)
        return json_response({"ok": False, "error": str(exc)}, status=500)


def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    async_register(
        hass=hass,
        domain=DOMAIN,
        name="OSRS Data",
        webhook_id=webhook_id,
        handler=_handle_webhook,
        allowed_methods=["POST"],
    )
