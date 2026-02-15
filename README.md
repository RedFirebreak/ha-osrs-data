# OSRS Webhook (Home Assistant)

A Home Assistant custom integration that receives RuneLite (Dink) webhook notifications and turns them into:
- Home Assistant events (for automations)
- Sensors/entities (for dashboards and history)

## How it works

1. You add the integration in Home Assistant (via HACS or manual).
2. The integration creates a unique webhook URL.
3. You configure Dink/RuneLite to POST notifications to that webhook URL.
4. Home Assistant receives the payload and emits an event (`osrs_webhook_event`).

Dink can send `multipart/form-data` where `payload_json` contains the main JSON, and `file` may contain an image attachment. In captured payloads, embeds can reference the image using an `attachment://...` URL.

## Installation

### HACS
1. Add this repository as a custom repository in HACS (Integration).
2. Install.
3. Restart Home Assistant.

### Manual
Copy `custom_components/osrs_webhook` into your Home Assistant `custom_components/` folder and restart.

## Configuration

1. Go to **Settings → Devices & services → Add integration**
2. Search for **OSRS Webhook**
3. Finish setup

After setup, the webhook ID is stored in the config entry. Your webhook URL will be:

`https://<your-ha-domain>/api/webhook/<webhook_id>`

## Automations

This integration fires an event on the Home Assistant event bus:

- Event type: `osrs_webhook_event`
- Event data: raw Dink payload (initially)

You can trigger an automation using an Event trigger and filter on fields such as `type`, `playerName`, or `embeds`.

## Privacy & Security

Webhook URLs are effectively secret tokens. If your Home Assistant is exposed publicly, treat the webhook URL as sensitive and avoid sharing it.
