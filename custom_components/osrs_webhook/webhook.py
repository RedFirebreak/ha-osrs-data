from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import webhook

from .const import DOMAIN, EVENT_TYPE, CONF_WEBHOOK_ID

_LOGGER = logging.getLogger(__name__)


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


def _extract_image_metadata(file_field: Any) -> dict[str, Any] | None:
    """Extract metadata from an uploaded file field (no bytes persisted)."""
    if file_field is None:
        return None

    size: int | None = None
    if hasattr(file_field, "file") and file_field.file:
        file_field.file.seek(0, 2)
        size = file_field.file.tell()
        file_field.file.seek(0)

    return {
        "filename": getattr(file_field, "filename", None),
        "content_type": getattr(file_field, "content_type", None),
        "size": size,
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
            image_meta = _extract_image_metadata(form.get("file"))
        else:
            payload = await request.json()

        event_data = _build_normalized_event(payload, image_meta)
        hass.bus.async_fire(EVENT_TYPE, event_data)

        return {"ok": True}
    except Exception as exc:
        _LOGGER.exception("Webhook handling failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> None:
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    webhook.async_register(
        hass=hass,
        domain=DOMAIN,
        name="OSRS Webhook",
        webhook_id=webhook_id,
        handler=_handle_webhook,
    )
