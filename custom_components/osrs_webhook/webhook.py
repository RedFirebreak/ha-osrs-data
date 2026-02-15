from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import webhook

from .const import DOMAIN, EVENT_TYPE, CONF_WEBHOOK_ID

_LOGGER = logging.getLogger(__name__)


async def _handle_webhook(
    hass: HomeAssistant,
    webhook_id: str,
    request,
) -> Any:
    """
    Handle incoming webhook calls from Dink/RuneLite.

    Dink can send multipart/form-data with:
      - payload_json: a JSON string
      - file: an image attachment (optional)
    """
    try:
        content_type = request.headers.get("Content-Type", "")
        data: dict[str, Any] = {}

        if "multipart/form-data" in content_type:
            form = await request.post()
            payload_json = form.get("payload_json")
            if payload_json:
                data = json.loads(payload_json)
            # file = form.get("file")  # aiohttp.web.FileField (optional)
        else:
            data = await request.json()

        # Fire HA event so automations can react immediately
        hass.bus.async_fire(EVENT_TYPE, data)

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
