# OSRS Data (Home Assistant)

[![Validate](https://github.com/RedFirebreak/ha-osrs-data/actions/workflows/validate.yaml/badge.svg)](https://github.com/RedFirebreak/ha-osrs-data/actions/workflows/validate.yaml) [![hassfest](https://github.com/RedFirebreak/ha-osrs-data/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/RedFirebreak/ha-osrs-data/actions/workflows/hassfest.yaml)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RedFirebreak&category=Integration&repository=ha-osrs-data)

A Home Assistant custom integration that receives real-time player data from the [HA Exporter](https://github.com/xXD4rkDragonXx/runelite-homeassistant-data-exporter) RuneLite plugin and turns it into:
- Rich sensors/entities per account (stats, inventory, equipment, health, prayer, location, spellbook)
- Home Assistant events (for automations)
- Persistent state (account data survives restarts)
- Automatic deduplication of retried submissions

## Companion Plugin

This integration requires the **[HA Exporter](https://github.com/xXD4rkDragonXx/runelite-homeassistant-data-exporter)** plugin for RuneLite. You can find it on the [RuneLite Plugin Hub](https://runelite.net/plugin-hub/) by searching for **HA Exporter**.

## Installation

### HACS (recommended)
1. Add this repository as a custom repository in HACS (Integration).
2. Install.
3. Restart Home Assistant.

### Manual
Copy `custom_components/osrs_data` from this repository into your Home Assistant `config/custom_components/` folder and restart.

**Important:** The folder must be named `osrs_data` (matching the domain in manifest.json).

## Setup & Pairing

### Prerequisites
- The **[HA Exporter](https://github.com/xXD4rkDragonXx/runelite-homeassistant-data-exporter)** plugin installed in RuneLite (search for **HA Exporter** on the RuneLite Plugin Hub)

### First-time setup
After HACS / manual installation of the integration:
1. Go to **Settings → Devices & services → Add integration**
2. Search for **OSRS Data**
3. Enter a name for the integration → **Next**
4. A **pairing code** is displayed
5. In the **HA Exporter** RuneLite plugin, enter the code and your HA URL to pair
6. Click **Submit** in Home Assistant — done!

The plugin receives a device-specific token and uses it for all future requests.

## Configuring the HA Exporter RuneLite plugin
1. Install **[HA Exporter](https://github.com/xXD4rkDragonXx/runelite-homeassistant-data-exporter)** from the RuneLite Plugin Hub.
2. With your **pairing code** ready, open the plugin's sidepanel.
3. Enter the pairing-setting menu.
4. Configure HA Exporter to point at your Home Assistant URL:
   ```
   https://<your-ha-domain>/
   ```
5. Enter your **pairing code**.
6. Click the "pair" button.
7. Check your active pairing in the sidepanel.
8. (if not done already) Finish the integration setup in Home Assistant.


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
| `POST /api/osrs-data/events` | `X-Osrs-Token` header | Submit player data |
| `POST /api/osrs-data/pair/code` | HA auth | Generate a new pairing code |
| `GET /api/osrs-data/devices` | HA auth | List paired devices |
| `DELETE /api/osrs-data/devices/{id}` | HA auth | Revoke a device |

## Features

### Sensors

The integration automatically creates a **Status** sensor (shows `ready` with the endpoint URLs as attributes) and, for each RuneScape account that sends data, a full set of per-account sensors grouped under an HA device named **OSRS \<PlayerName\>**:

| Sensor | State | Key Attributes |
|--------|-------|----------------|
| **Player Info** | Player name | `account_type`, `world`, `last_update`, `events` |
| **Inventory** | Occupied slot count | `items` (list of item dicts), `slots_used`, `slots_total` (28) |
| **Equipment** | Number of equipped slots | One key per slot: `HEAD`, `CAPE`, `WEAPON`, `BODY`, `LEGS`, `GLOVES`, `BOOTS`, `AMMO`, `AMMO_EXTRA`, `AMULET`, `RING`, `SHIELD` |
| **Health** | Current HP | `current`, `max`, `last_update` |
| **Prayer Points** | Current prayer points | `current`, `max`, `last_update` |
| **Location** | `x, y` coordinates | `x`, `y`, `plane`, `last_update` |
| **Spellbook** | Active spellbook name | `id`, `last_update` |
| **Game State** | RuneLite client game state | `last_update` |
| **\<Skill\> Level** *(per skill)* | Skill level | `xp`, `last_update` |

Skill-level sensors are created dynamically — one per OSRS skill (up to 23) — the first time stats data arrives for an account.

### Game State Values

The **Game State** sensor reflects the RuneLite client's current state. Possible values:

| State | Description |
|-------|-------------|
| `UNKNOWN` | Unknown game state |
| `STARTING` | The client is starting |
| `LOGIN_SCREEN` | The client is at the login screen |
| `LOGIN_SCREEN_AUTHENTICATOR` | The client is at the login screen entering authenticator code |
| `LOGGING_IN` | There is a player logging in |
| `LOADING` | The game is being loaded |
| `LOGGED_IN` | The user has successfully logged in |
| `CONNECTION_LOST` | Connection to the server was lost |
| `HOPPING` | A world hop is taking place |

### Persistence

Account state, paired devices, and history are persisted to disk via Home Assistant's built-in store. All data survives HA restarts. A deferred save (5 s) batches rapid updates.

### Event deduplication

If the HA Exporter plugin retries a submission (e.g., due to network issues), the integration ignores exact duplicate payloads within a 30-second window. Distinct data updates always pass through. Individual events within each payload are also deduplicated — if an event carries an `event_id` field it is used directly; otherwise a composite signature is built from the account, event type, and event data.

### Event types

The HA Exporter plugin sends events in the `events[]` array of each payload. The integration fires an individual `osrs_data_event` on the HA event bus for each event, with flat fields for easy automation matching.

| Event type (raw) | Normalized `event_type` | Description |
|---|---|---|
| `clientShutdown` | `CLIENTSHUTDOWN` | Client/logout — marks account offline |
| `death` | `DEATH` | Player death with kept/lost items and killer info |
| `levelUp` | `LEVELUP` | In-game level up for one or more skills |
| `loot` | `LOOT` | NPC or other loot drop |
| `pkLoot` | `PKLOOT` | PvP loot (player kill) |

Each event type also creates a counter sensor (e.g. `sensor.<account>_death_total`) that tracks the total number of events received and exposes a `last_fired` attribute.

#### clientShutdown (Logout)

Fired when the RuneLite client shuts down or the player logs out. Marks the account as offline.

```json
{
  "events": [
    {
      "type": "clientShutdown",
      "data": "Logout"
    }
  ]
}
```

#### death

Fired when the player dies. Contains kept/lost items, killer info, value lost, and death location.

```json
{
  "events": [
    {
      "type": "death",
      "data": {
        "valueLost": 88,
        "danger": "DANGEROUS",
        "killerName": "Guard",
        "killerNpcId": 11917,
        "keptItems": [
          {
            "name": "Amulet of fury",
            "id": 6585,
            "gePrice": 2391076,
            "haPrice": 121200,
            "quantity": 1
          }
        ],
        "lostItems": [
          {
            "name": "Bucket",
            "id": 1925,
            "gePrice": 5,
            "haPrice": 1,
            "quantity": 10
          },
          {
            "name": "Coins",
            "id": 995,
            "gePrice": 1,
            "haPrice": 0,
            "quantity": 30
          }
        ],
        "location": {
          "x": 3175,
          "y": 3433,
          "plane": 0
        }
      }
    }
  ]
}
```

#### levelUp

Fired when the player levels up one or more skills in-game. The `data` field is a list because multiple level-ups can be sent at once.

```json
{
  "events": [
    {
      "type": "levelUp",
      "data": [
        {
          "skill": "sailing",
          "level": 75
        }
      ]
    }
  ]
}
```

#### loot

Fired when loot is received from an NPC kill or other source.

```json
{
  "events": [
    {
      "type": "loot",
      "data": {
        "items": [
          {
            "name": "Bones",
            "id": 526,
            "gePrice": 34,
            "haPrice": 0,
            "quantity": 1
          },
          {
            "name": "Coins",
            "id": 995,
            "gePrice": 1,
            "haPrice": 0,
            "quantity": 1
          }
        ],
        "highestValueItem": {
          "name": "Bones",
          "id": 526,
          "gePrice": 34,
          "haPrice": 0,
          "quantity": 1
        },
        "totalValue": 35,
        "source": {
          "text": "Guard",
          "link": "https://oldschool.runescape.wiki/w/Special:Search?search=Guard"
        },
        "type": "NPC",
        "npcId": 11916,
        "criteria": []
      }
    }
  ]
}
```

#### pkLoot

Fired when loot is received from a player kill. Same structure as `loot` but with `"type": "PLAYER"`.

```json
{
  "events": [
    {
      "type": "pkLoot",
      "data": {
        "items": [
          {
            "name": "Bones",
            "id": 526,
            "gePrice": 34,
            "haPrice": 0,
            "quantity": 1
          },
          {
            "name": "Coins",
            "id": 995,
            "gePrice": 1,
            "haPrice": 0,
            "quantity": 1
          }
        ],
        "highestValueItem": {
          "name": "Bones",
          "id": 526,
          "gePrice": 34,
          "haPrice": 0,
          "quantity": 1
        },
        "totalValue": 35,
        "source": {
          "text": "PlayerName",
          "link": ""
        },
        "type": "PLAYER",
        "criteria": []
      }
    }
  ]
}
```

## Automations

The integration fires `osrs_data_event` on the Home Assistant event bus. There are two kinds of events:

**Base event** — fired every time data is received (roughly every 25 seconds):

```json
{
  "player_name": "YourRSN",
  "account_type": "normal",
  "world": "302",
  "received_at": "2025-01-15T12:34:56+00:00",
  "events": []
}
```

**Per-event** — fired once for each entry in the `events[]` array, with flat fields for easy automation matching:

```json
{
  "account_name": "YourRSN",
  "event_type": "DEATH",
  "event_data": { "killerName": "Guard", "valueLost": 88 },
  "received_at": "2025-01-15T12:34:56+00:00"
}
```

### Example: announce world change

```yaml
automation:
  - alias: "OSRS world change"
    trigger:
      - platform: state
        entity_id: sensor.osrs_playerone_player_info
        attribute: world
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "World hop"
          message: >
            {{ state_attr('sensor.osrs_playerone_player_info', 'player_name') }}
            moved to world {{ state_attr('sensor.osrs_playerone_player_info', 'world') }}
```

### Example: low HP alert

```yaml
automation:
  - alias: "OSRS low HP alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.osrs_playerone_health
        below: 20
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "⚠️ Low HP!"
          message: >
            {{ state_attr('sensor.osrs_playerone_health', 'current') }} /
            {{ state_attr('sensor.osrs_playerone_health', 'max') }} HP
```

### Example: flash lights on death

```yaml
automation:
  - alias: "OSRS - Blink lights on death"
    trigger:
      - platform: event
        event_type: osrs_data_event
        event_data:
          account_name: osrsuser
          event_type: DEATH
    action:
      - service: light.turn_on
        target:
          entity_id: light.desk_lamp
        data:
          color_name: red
          flash: short
```

### Example: notify on specific loot

```yaml
automation:
  - alias: "OSRS - Notify on valuable loot"
    trigger:
      - platform: event
        event_type: osrs_data_event
        event_data:
          event_type: LOOT
    condition:
      - condition: template
        value_template: >
          {{ trigger.event.data.event_data.totalValue | default(0) > 10000 }}
    action:
      - service: notify.mobile_app_my_phone
        data:
          title: "💰 Valuable loot!"
          message: >
            {{ trigger.event.data.account_name }} looted
            {{ trigger.event.data.event_data.totalValue }} gp worth of items
            from {{ trigger.event.data.event_data.source.text }}
```

### Example: flash lights on any event

```yaml
automation:
  - alias: "OSRS data received"
    trigger:
      - platform: event
        event_type: osrs_data_event
    action:
      - service: light.turn_on
        target:
          entity_id: light.desk_lamp
        data:
          color_name: green
          flash: short
```

See `tests/samples/runelite-post-request.md` for a full example of the payload sent by the HA Exporter plugin.

## Implementation Examples

The [`implementation/`](implementation/) folder contains ready-to-use Home Assistant **blueprints** and **scripts** that work with this integration:

| Template | Type | Description |
|----------|------|-------------|
| Flash lights on event | Blueprint | Flashes selected lights when an OSRS event fires, with color/brightness options and automatic state restore |
| Wave lights on event | Blueprint | Staggers (waves) light flashes one-by-one across multiple lights for a chase effect |
| Flash single light | Script | Helper script used by the wave blueprint to run a blink cycle on one light |

See the [implementation README](implementation/README.md) for full installation and usage instructions.

## Project Structure

```
custom_components/osrs_data/   # The integration itself
implementation/                 # Blueprints & scripts for Home Assistant
tests/                          # Automated test suite
```

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
- [Blueprint Documentation](https://www.home-assistant.io/docs/automation/using_blueprints/)
