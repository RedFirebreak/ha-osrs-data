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

The plugin receives a device-specific token and uses it for all future requests. The pair response also includes your Home Assistant location name (Settings → System → General), which the plugin uses as the connection's default name.

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

- **Options flow:** Go to **Settings → Integrations → OSRS Data → Configure** → choose **Pair a new RuneLite client** → enter a device name → get a new code (the same menu also has **Edit integration settings**, see [Options](#options))
- **Service:** Go to **Developer Tools → Services → `osrs_data.create_pairing_code`** → call it → a notification appears with the code

Each pairing creates an independent device token. Existing tokens are never invalidated when new clients are added.

Only one OSRS Data integration entry is supported: pair every client to that entry. Home Assistant refuses to add a second one. A duplicate entry left over from an older version is not loaded, and the log says so. Delete that entry; your data and paired clients are kept.

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

Responses follow the plugin's delivery rules:

- A revoked or unknown token returns `401`, and the plugin disables that connection.
- A payload that is unusable as a whole (not JSON, or no player with a name) returns `400`, and the plugin drops it without retrying. A section or field with the wrong type is skipped and the rest of the payload is applied. Bad input never returns a `5xx`.
- While the integration isn't ready, requests return `503` with `Retry-After: 60`, and the plugin pauses and retries.
- After 10 failed pairing attempts from one IP address within 10 minutes, `/api/osrs-data/pair` returns `429` with `Retry-After` and an `error` message until the window has passed.

The plugin sends its version in an `X-Osrs-Exporter-Version` header. It is shown as the account device's firmware (`sw_version`), in the Player Info `plugin_version` attribute, and in the device list (`plugin_version`, `last_seen`).

## Features

### Sensors

The integration automatically creates a **Status** sensor (shows `ready` with the endpoint URLs as attributes) and, for each RuneScape account that sends data, a full set of per-account sensors grouped under an HA device named **OSRS \<PlayerName\>**:

| Sensor | State | Key Attributes |
|--------|-------|----------------|
| **Player Info** | Player name | `display_name`, `previous_names`, `account_type`, `world`, `world_types`, `last_update`, `plugin_version`, `events` |
| **Inventory** | Occupied slot count | `items` (list of item dicts), `slots_used`, `slots_total` (28), `received` |
| **Equipment** | Number of equipped slots | One key per slot: `HEAD`, `CAPE`, `WEAPON`, `BODY`, `LEGS`, `GLOVES`, `BOOTS`, `AMMO`, `AMMO_EXTRA`, `AMULET`, `RING`, `SHIELD`; `received` |
| **Health** | Current HP | `current`, `max`, `last_update`, `received` |
| **Prayer Points** | Current prayer points | `current`, `max`, `last_update`, `received` |
| **Location** | `x, y` coordinates | `x`, `y`, `plane`, `last_update`, `received` |
| **Spellbook** | Active spellbook name | `id`, `last_update`, `received` |
| **Game State** | RuneLite client game state | `last_update` |
| **Total Level** | Sum of all skill levels | `total_xp`, `skill_count`, `last_update` |
| **Combat Level** | Computed OSRS combat level | `last_update` |
| **Last Death** | Killer name of the most recent death | `value_lost`, `danger`, `killer_name`, `killer_npc_id`, `kept_items`, `lost_items`, `location`, `timestamp`, `recent` |
| **Last Loot** | Source of the most recent loot drop | `total_value`, `highest_value_item`, `items`, `source`, `type`, `npc_id`, `timestamp`, `recent` |
| **Last Collection Log** | Most recent new collection log item | `item_id` (`null` if unknown), `value`, `kill_count`, `timestamp`, `recent` |
| **\<Skill\> Level** *(per skill)* | Skill level | `xp`, `last_update` |
| **\<EVENT\> Total** *(per event type)* | Cumulative event count | `last_fired` |

Skill-level sensors are created dynamically — one per OSRS skill (up to 23) — the first time stats data arrives for an account. **Total Level** and **Combat Level** are derived from each skill's XP (matching the way the game computes them, so they are unaffected by temporary stat boosts). **Last Death**, **Last Loot** and **Last Collection Log** populate the first time such an event arrives; **Last Loot**'s state is the most notable item from the drop, and their `recent` attribute holds the last 10 entries from the history buffer (see [Event history](#event-history)). Their `timestamp` is when the event happened in game (the plugin's event timestamp), not when Home Assistant received it.

The plugin's per-connection filters can leave out inventory, equipment, health, prayer points, location or spellbook. A section that is left out keeps its last known value, and that sensor's `received` attribute is `false` until the section is sent again.

Collection log events only arrive when the in-game setting **Collection log – New addition notification** is on (chat or popup).

The HA Exporter plugin sends nothing from special worlds unless its **Send data from special worlds** setting is on. When it is on, on special worlds (Leagues/`SEASONAL`, `DEADMAN`, `BETA_WORLD`, `TOURNAMENT_WORLD`, `QUEST_SPEEDRUNNING`, `NOSAVE_MODE`, `PVP_ARENA`) skill, Total Level and Combat Level sensors are **not** updated, so those separate stats never overwrite your main-game values. Live sensors (health, world, location, online status, …) keep updating.

**Name changes:** when the HA Exporter plugin sends its stable `accountHash`, a renamed account stays on the same device and entities: entity IDs, statistics and event history carry over, and the old name is listed in `previous_names`. Accounts that existed before this version keep their original entity IDs; the hash is linked the first time the plugin reports it. If an account is renamed *before* it has sent data with a hash even once, it shows up as a new device (the same as in older versions).

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

### Event history

Every game event (deaths, loot, level-ups, collection log items, achievement diaries, combat tasks, …) is recorded into a persistent, per-account, per-type rolling buffer. The buffer belongs to the account, not its display name, so it follows name changes and two accounts can't mix their history. Defaults keep the last **50 deaths**, **100 loot** drops, and **50** of every other type; these limits are configurable (see [Options](#options)).

Query the history with the **`osrs_data.get_history`** service (returns a response):

```yaml
action: osrs_data.get_history
data:
  event_type: DEATH   # optional — omit for all types
  account_name: myrsn # optional — the account's current name; omit for all accounts
  limit: 20
```

Each returned entry's `account_name` is the account's current display name.

The **Last Death** and **Last Loot** sensors also expose the most recent 10 entries via their `recent` attribute, so a dashboard can list them without calling a service (both example dashboards in [`implementation/dashboards/`](implementation/dashboards/) render these as recent loot/death tables).

### Options

Go to **Settings → Devices & services → OSRS Data → Configure → Edit integration settings** to tune:

| Option | Default | Effect |
|--------|---------|--------|
| Death history entries kept | 50 | Size of the DEATH history buffer |
| Loot history entries kept | 100 | Size of the LOOT history buffer |
| Default history entries kept | 50 | Buffer size for every other event type |
| Deduplication window (seconds) | 30 | How long duplicate events without an `eventId` are suppressed |
| Presence timeout fallback (seconds) | 1500 | Offline threshold used when no `tickDelay` is known |

Changing options reloads the integration so the new values take effect immediately.

### Event deduplication

The HA Exporter plugin resends payloads that failed (e.g., due to network issues). A resent payload is processed again: its snapshot is simply applied again, and its individual events are deduplicated:

- If an event carries an `eventId` (or legacy `event_id`), that ID is the key. It is remembered for 15 minutes, because the plugin can queue and resend events for up to 10 minutes while it backs off.
- Otherwise a composite signature of account, event type and event data is used, with the configurable window.

The plugin also stamps every payload with a `timestamp`. When it resends an older queued payload after a newer one from the same RuneLite client has arrived, the older snapshot is not applied, so inventory and skills never roll back. Its events are still processed, and the account stays online while data arrives.

The timestamp comes from the player's PC clock, which can be wrong. A timestamp in the future is treated as the time Home Assistant received the payload, and snapshots are only compared with earlier ones from the same paired client, so clients whose clocks differ are applied in the order they arrive.

### Event types

The HA Exporter plugin sends events in the `events[]` array of each payload. The integration fires an individual `osrs_data_event` on the HA event bus for each event, with flat fields for easy automation matching.

| Event type (raw) | Normalized `event_type` | Description |
|---|---|---|
| `clientShutdown` | `CLIENTSHUTDOWN` | Client/logout — marks account offline |
| `death` | `DEATH` | Player death with kept/lost items and killer info |
| `levelUp` | `LEVELUP` | In-game level up for one or more skills |
| `loot` | `LOOT` | NPC or other loot drop |
| `pkLoot` | `PKLOOT` | PvP loot (player kill) |
| `superiorSpawn` | `SUPERIORSPAWN` | Superior slayer monster spawned (`name`, `npcId`, `location`) |
| `achievementDiary` | `ACHIEVEMENTDIARY` | Achievement diary task/tier completed |
| `combatTask` | `COMBATTASK` | Combat Achievement task completed |
| `collectionLog` | `COLLECTIONLOG` | New collection log item (`itemName`, `itemId` (`-1` if unknown), `value`, optional `killCount`) |

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
  "event_id": "3f2c9a4e-8d1b-4c6e-9f0a-2b7d5e1c8a90",
  "occurred_at": "2025-01-15T12:34:50+00:00",
  "received_at": "2025-01-15T12:34:56+00:00"
}
```

`event_id` is the plugin's unique ID for the event (`null` for older plugin versions). `occurred_at` is when it happened in game; it can be earlier than `received_at` when the plugin had to queue the event.

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
| Notify on event | Blueprint | Sends a notification on a chosen OSRS event, with templated title/message |
| Notify on valuable loot | Blueprint | Notifies when LOOT/PKLOOT `totalValue` meets a configurable threshold |
| Low HP alert | Blueprint | Notifies (and optionally flashes a light red) when a Health sensor drops below a threshold |
| Flash single light | Script | Helper script used by the wave blueprint to run a blink cycle on one light |
| **Player Progress** | Dashboard | Rich player dashboard — status, vitals, XP-over-time charts, auto skills grid, recent loot/deaths (needs Mushroom + apexcharts-card + auto-entities from HACS) |
| OSRS overview | Dashboard | Core-only Lovelace view (no custom cards) showing vitals, levels, gear, and recent deaths/loot |

See the [implementation README](implementation/README.md) for full installation and usage instructions, including the dashboard [prerequisites](implementation/README.md#installing-the-dashboards) and an optional multi-account dropdown.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Project Structure

```
custom_components/osrs_data/   # The integration itself
implementation/                 # Blueprints, scripts & dashboards for Home Assistant
tests/                          # Automated test suite
```

## Privacy & Security

- Pairing codes are one-time-use and expire after 5 minutes.
- Failed pairing attempts are rate limited per IP address (10 per 10 minutes).
- Device tokens are scoped per client and hashed (SHA-256) at rest.
- Individual clients can be revoked without affecting others.
- No HA access tokens or webhook secrets are ever exposed to the plugin.

## Developer References

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Async / Blocking Operations](https://developers.home-assistant.io/docs/asyncio_blocking_operations/)
- [Config Flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [Options Flow](https://developers.home-assistant.io/docs/config_entries_options_flow_handler/)
- [Blueprint Documentation](https://www.home-assistant.io/docs/automation/using_blueprints/)

## License

Apache License 2.0 (see [LICENSE](LICENSE)), Copyright 2026 RedFirebreak. You may use, change and
redistribute it, including commercially. If you do, keep the [NOTICE](NOTICE) file and credit
RedFirebreak with a link to https://github.com/RedFirebreak/ha-osrs-data. GitHub's "Cite this repository" button uses
[CITATION.cff](CITATION.cff).
