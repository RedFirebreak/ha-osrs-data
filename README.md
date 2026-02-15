# OSRS Webhook (Home Assistant)

A Home Assistant custom integration that receives RuneLite (Dink) webhook notifications and turns them into:
- Home Assistant events (for automations)
- Sensors/entities (for dashboards and history)
- Persistent history (last X events per account/type survive restarts)
- Automatic deduplication of webhook retries

## Installation

### HACS (recommended)
1. Add this repository as a custom repository in HACS (Integration).
2. Install.
3. Restart Home Assistant.

### Manual
Copy `custom_components/osrs_webhook` from this repository into your Home Assistant `config/custom_components/` folder and restart.

**Important:** The folder must be named `osrs_webhook` (matching the domain in manifest.json), not `ha-osrs-runelite-webhooks`.

## Setup

1. Go to **Settings → Devices & services → Add integration**
2. Search for **OSRS Webhook**
3. Finish setup — the integration generates a unique webhook ID

Your webhook URL will be:

```
https://<your-ha-domain>/api/webhook/<webhook_id>
```

You can find `<webhook_id>` in the integration's config entry. If you use Nabu Casa, the URL follows the same pattern with your Nabu Casa domain.

## Configuring Dink (RuneLite)

1. In RuneLite, install the **Dink** plugin.
2. Open Dink settings and set the **Primary Webhook URL** to your Home Assistant webhook URL.
3. Enable the notification types you want (Deaths, Loot, Levels, Pets, Quests, Combat Achievements, Achievement Diaries).
4. Dink sends `multipart/form-data` with `payload_json` (JSON) and an optional `file` (screenshot). This integration parses `payload_json` and uses the `type` and `extra` fields.

## Features

### Event types

| Type | What it tracks |
|------|----------------|
| `LEVEL` | Skill level-ups and combat level changes |
| `LOOT` | Item drops with source, value, rarity |
| `DEATH` | Deaths with items lost/kept, PvP/NPC info |
| `PET` | Pet drops and duplicates |
| `QUEST` | Quest completions and progress |
| `COMBAT_ACHIEVEMENT` | Combat task completions and tier progress |
| `ACHIEVEMENT_DIARY` | Diary completions by area and difficulty |

### Sensors

For each RuneScape account, the integration creates:
- **Counter sensors** — cumulative totals for each event type (levels, loot events, deaths, pets, quests, combat tasks, diaries)
- **Last Event sensor** — the most recent event type, summary, and parsed data as attributes

### Persistent history

Event history is stored per account and per event type using ring buffers:
- **Loot**: last 100 entries
- **Deaths**: last 50 entries
- **All other types**: last 50 entries

History survives Home Assistant restarts.

### Webhook deduplication

If Dink retries a webhook (e.g., due to network issues), the integration ignores exact duplicate events within a 30-second window. Distinct events (different loot drops, different skills, etc.) always pass through.

## Automations

The integration fires `osrs_webhook_event` on the Home Assistant event bus. Use an **Event trigger** to build automations.

### Example: notify on rare loot

```yaml
automation:
  - alias: "OSRS rare loot alert"
    trigger:
      - platform: event
        event_type: osrs_webhook_event
        event_data:
          event_type: LOOT
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.data.totalValue | int > 100000 }}"
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "💰 Rare drop!"
          message: >
            {{ trigger.event.data.account.playerName }} looted
            {{ trigger.event.data.data.items | map(attribute='name') | join(', ') }}
            worth {{ trigger.event.data.data.totalValue | int }} gp
```

### Example: flash lights on death

```yaml
automation:
  - alias: "OSRS death flash"
    trigger:
      - platform: event
        event_type: osrs_webhook_event
        event_data:
          event_type: DEATH
    action:
      - service: light.turn_on
        target:
          entity_id: light.desk_lamp
        data:
          color_name: red
          flash: short
```

### Example: TTS on pet drop

```yaml
automation:
  - alias: "OSRS pet announcement"
    trigger:
      - platform: event
        event_type: osrs_webhook_event
        event_data:
          event_type: PET
    action:
      - service: tts.google_translate_say
        data:
          entity_id: media_player.living_room
          message: >
            {{ trigger.event.data.account.playerName }} just got a pet!
            {{ trigger.event.data.data.petName }}
```

## Event data structure

Every `osrs_webhook_event` contains:

```json
{
  "event_type": "LOOT",
  "account": {
    "playerName": "YourRSN",
    "accountType": "NORMAL",
    "dinkAccountHash": "abc123...",
    "seasonalWorld": false
  },
  "received_at": "2025-01-15T12:34:56+00:00",
  "data": { },
  "raw_meta": {
    "world": 518,
    "regionId": 12850
  },
  "image": {
    "filename": "screenshot.png",
    "content_type": "image/png",
    "size": 102400
  }
}
```

The `data` field contains event-type-specific parsed data (see `samples/` for full examples).

## Privacy & Security

Webhook URLs are effectively secret tokens. If your Home Assistant is exposed publicly, treat the webhook URL as sensitive and avoid sharing it.

## Developer References

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Async / Blocking Operations](https://developers.home-assistant.io/docs/asyncio_blocking_operations/)
- [Config Flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [Options Flow](https://developers.home-assistant.io/docs/config_entries_options_flow_handler/)
