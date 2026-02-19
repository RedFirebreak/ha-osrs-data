# OSRS Dashboard Installation & Setup Guide

This guide explains how to install and configure the OSRS custom helpers,
template sensors, blueprints, and dashboard cards for Home Assistant.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Player Selector Helper](#1-player-selector-helper)
3. [Template Sensors](#2-template-sensors)
4. [Automation Blueprints](#3-automation-blueprints)
5. [XP Tracking with Utility Meters](#4-xp-tracking-with-utility-meters)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **OSRS Data integration** installed and at least one RuneLite client paired
- Home Assistant **2024.1+** (for template sensor syntax)
- Optional HACS cards for extra visual polish:
  - [card-mod](https://github.com/thomasloven/lovelace-card-mod) — custom card styling
  - [layout-card](https://github.com/thomasloven/lovelace-layout-card) — masonry/grid layouts
  - [mushroom](https://github.com/piitaya/lovelace-mushroom) — beautiful template cards

---

## 1. Player Selector Helper

The player selector is an `input_select` entity that every dashboard card
reads to determine which player's data to display.

### Option A: UI Setup

1. Go to **Settings → Devices & Services → Helpers → + Create Helper**
2. Choose **Dropdown**
3. Configure:
   - **Name:** `OSRS Player Selector`
   - **Entity ID:** `input_select.osrs_player_selector`
   - **Options:** Add each of your player names (e.g. `PlayerOne`, `PlayerTwo`)
   - **Icon:** `mdi:account-search`
4. Save

### Option B: YAML Setup

Add the contents of `input_select_player.yaml` to your `configuration.yaml`:

```yaml
# In configuration.yaml
input_select:
  osrs_player_selector:
    name: "OSRS Player Selector"
    icon: mdi:account-search
    options:
      - "PlayerOne"
      - "PlayerTwo"
    initial: "PlayerOne"
```

> **Important:** Player names must match exactly what appears in the
> `sensor.osrs_<player>_player_info` entity state (case-sensitive).

---

## 2. Template Sensors

Template sensors compute derived stats like Combat Level, Total Level,
Total XP, and Closest Skill to Level Up. These power several dashboard cards.

### Setup

Add the contents of `template_sensors.yaml` to your `configuration.yaml`:

```yaml
# In configuration.yaml — add below existing content
template:
  - sensor:
      # ... (paste the full template_sensors.yaml content here)
```

Or use a [packages directory](https://www.home-assistant.io/docs/configuration/packages/):

```yaml
# In configuration.yaml
homeassistant:
  packages:
    osrs_dashboard: !include custom_helpers/template_sensors.yaml
```

After adding, restart Home Assistant. The following sensors will appear:

| Sensor | Description |
|--------|-------------|
| `sensor.osrs_closest_to_level_up` | Skill name closest to leveling, with `xp_remaining`, `current_level`, and `progress_percent` attributes |
| `sensor.osrs_total_level` | Sum of all skill levels |
| `sensor.osrs_total_xp` | Sum of all skill XP |
| `sensor.osrs_combat_level` | Calculated OSRS combat level |

---

## 3. Automation Blueprints

Blueprints are pre-built automation templates you can import and configure
through the Home Assistant UI.

### Available Blueprints

| Blueprint | File | Description |
|-----------|------|-------------|
| Level-Up Notification | `blueprints/level_up_notification.yaml` | Notifies when a skill gains a level |
| Low HP Alert | `blueprints/low_hp_alert.yaml` | Alerts when HP drops below threshold, optional light flash |
| XP Milestone | `blueprints/xp_milestone.yaml` | Notifies when total XP passes a milestone |

### Import Steps

1. Copy the blueprint `.yaml` files to your HA config directory:
   ```
   config/blueprints/automation/osrs_data/
   ```
   Create the `osrs_data` subfolder if it doesn't exist.

2. Restart Home Assistant (or reload automations).

3. Go to **Settings → Automations & Scenes → Blueprints**.

4. The OSRS blueprints will appear in the list.

5. Click a blueprint → **Create Automation** → configure inputs → **Save**.

### Example: Level-Up Notification

After importing the blueprint:
1. Click **Level-Up Notification → Create Automation**
2. Select your skill sensor (e.g. `sensor.osrs_playerone_attack_level`)
3. Enter your notification service (e.g. `notify.mobile_app_my_phone`)
4. Save — you'll get notified on every level up!

> **Tip:** Create one automation per skill you want to monitor, or create
> a single automation using an entity group or template trigger for all skills.

---

## 4. XP Tracking with Utility Meters

For daily/weekly XP tracking, use Home Assistant's built-in
[Utility Meter](https://www.home-assistant.io/integrations/utility_meter/) integration.

### Setup Example (Daily XP Tracking)

Add to your `configuration.yaml`:

```yaml
utility_meter:
  osrs_daily_total_xp:
    source: sensor.osrs_total_xp
    name: "OSRS Daily Total XP"
    cycle: daily

  osrs_weekly_total_xp:
    source: sensor.osrs_total_xp
    name: "OSRS Weekly Total XP"
    cycle: weekly

  # Per-skill example:
  osrs_daily_attack_xp:
    source: sensor.osrs_playerone_attack_level
    name: "OSRS Daily Attack XP"
    cycle: daily
```

After restarting, you'll have `sensor.osrs_daily_total_xp` that resets
every day, showing XP gained since midnight.

> **Note:** Utility meters track the *change* in the source sensor's
> numeric value. For per-skill XP tracking, the source should be the
> skill sensor whose state is the XP value (or use an attribute template).

---

## Troubleshooting

### Sensors show "unavailable" or "unknown"

- Ensure the OSRS Data integration is set up and at least one RuneLite
  client has sent data.
- Check that player names in `input_select.osrs_player_selector` exactly
  match what appears in `sensor.osrs_<player>_player_info`.

### Template sensors not appearing

- Verify `template_sensors.yaml` syntax is correct (use **Developer Tools →
  Template** to test individual templates).
- Restart Home Assistant after configuration changes.

### Dashboard cards are blank

- The `input_select.osrs_player_selector` entity must exist first.
- Template sensors must be loaded before the dashboard renders.
- Check **Developer Tools → States** to verify sensor entity IDs.

### Blueprint import fails

- Ensure files are placed in `config/blueprints/automation/osrs_data/`.
- File must have valid YAML syntax (test with a YAML linter).
- Restart HA after adding blueprint files.
