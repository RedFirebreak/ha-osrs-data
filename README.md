# OSRS Data (Home Assistant)

[![Validate](https://github.com/RedFirebreak/ha-osrs-data/actions/workflows/validate.yaml/badge.svg)](https://github.com/RedFirebreak/ha-osrs-data/actions/workflows/validate.yaml) [![hassfest](https://github.com/RedFirebreak/ha-osrs-data/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/RedFirebreak/ha-osrs-data/actions/workflows/hassfest.yaml)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RedFirebreak&category=Integration&repository=ha-osrs-data)

A Home Assistant custom integration that receives RuneLite (Dink) notifications and turns them into:
- Home Assistant events (for automations)
- Sensors/entities (for dashboards and history)
- Persistent history (last X events per account/type survive restarts)
- Automatic deduplication of event retries

## Installation

### HACS (recommended)
1. Add this repository as a custom repository in HACS (Integration).
2. Install.
3. Restart Home Assistant.

### Manual
Copy `custom_components/osrs_data` from this repository into your Home Assistant `config/custom_components/` folder and restart.

**Important:** The folder must be named `osrs_data` (matching the domain in manifest.json).

## Setup & Pairing

### First-time setup
After HACS / manual installation of the plugin.
1. Go to **Settings → Devices & services → Add integration**
2. Search for **OSRS Data**
3. Enter a name for the integration → **Next**
4. A **pairing code** is displayed
5. In your RuneLite plugin, enter the code and your HA URL to pair
6. Click **Submit** in Home Assistant — done!

The plugin receives a device-specific token and uses it for all future requests.

## Configuring the Runelite plugin
1. With your **pairing code** ready, open the plugin's sidepanel.
2. Enter the pairing-setting menu
3. Configure HA-Data-exporter to point at your Home Assistant URL:
   ```
   https://<your-ha-domain>/
   ```
4. Enter your **pairing code**.
5. Click the "pair" button
6. Check your active pairing in the sidepanel
7. (if not done already) Finish the integration setup in Home Assistant


### Pairing additional clients

Already have the integration set up and want to pair another computer?

- **Options flow:** Go to **Settings → Integrations → OSRS Data → Configure** → enter a device name → get a new code
- **Service:** Go to **Developer Tools → Services → `osrs_data.create_pairing_code`** → call it → a notification appears with the code

Each pairing creates an independent device token. Existing tokens are never invalidated when new clients are added.

### Revoking a client

Individual clients can be revoked without affecting others:

```
DELETE /api/osrs-data/devices/{device_id}
```
(Requires HA authentication)

### Endpoints

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `POST /api/osrs-data/pair` | None (code-gated) | Consume a pairing code, receive device token |
| `POST /api/osrs-data/events` | `X-Osrs-Token` header | Submit event data |
| `POST /api/osrs-data/pair/code` | HA auth | Generate a new pairing code |
| `GET /api/osrs-data/devices` | HA auth | List paired devices |
| `DELETE /api/osrs-data/devices/{id}` | HA auth | Revoke a device |

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
| `COLLECTION` | Collection log entries |

### Sensors

For each RuneScape account, the integration creates:
- **Counter sensors** — cumulative totals for each event type (levels, loot events, deaths, pets, quests, combat tasks, diaries)
- **Last Event sensor** — the most recent event type, summary, and parsed data as attributes
- **Per-type last event sensors** — last loot, last death, last pet, etc.
- **Skill level sensors** — individual skill levels (created on first level event)

### Persistent history

Event history is stored per account and per event type using ring buffers:
- **Loot**: last 100 entries
- **Deaths**: last 50 entries
- **All other types**: last 50 entries

History survives Home Assistant restarts.

### Event deduplication

If Dink retries an event (e.g., due to network issues), the integration ignores exact duplicate events within a 30-second window. Distinct events (different loot drops, different skills, etc.) always pass through.

## Automations

The integration fires `osrs_data_event` on the Home Assistant event bus. Use an **Event trigger** to build automations.

### Example: notify on rare loot

```yaml
automation:
  - alias: "OSRS rare loot alert"
    trigger:
      - platform: event
        event_type: osrs_data_event
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
        event_type: osrs_data_event
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
        event_type: osrs_data_event
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

Every `osrs_data_event` contains:

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

- Pairing codes are one-time-use and expire after 5 minutes.
- Device tokens are scoped per client and hashed (SHA-256) at rest.
- Individual clients can be revoked without affecting others.
- No HA access tokens or webhook secrets are ever exposed to the plugin.

## Developer References

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Async / Blocking Operations](https://developers.home-assistant.io/docs/asyncio_blocking_operations/)
- [Config Flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [Options Flow](https://developers.home-assistant.io/docs/config_entries_options_flow_handler/)
