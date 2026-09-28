# Implementation Examples

Ready-to-use Home Assistant blueprints, scripts, and dashboards for the [OSRS Data](../README.md) integration.

## Contents

### Blueprints

| File | Name | Description |
|------|------|-------------|
| `blueprints/flash-lights-on-event.yaml` | Flash lights on event | Flashes selected lights when an OSRS event fires. Supports custom flash color, brightness, flash count, and transition speed. Automatically restores previous light states after flashing. |
| `blueprints/wave-lights-on-event.yaml` | Wave lights on event | Staggers light flashes one-by-one across multiple lights for a chase/wave effect. Each light runs its own independent blink cycle, offset by a configurable delay. Requires the helper script below. |
| `blueprints/notify-on-event.yaml` | Notify on event | Sends a notification when a chosen OSRS event fires. Title and message are templates with full access to `trigger.event.data`. |
| `blueprints/valuable-loot-notify.yaml` | Notify on valuable loot | Notifies when a `LOOT`/`PKLOOT` event's `totalValue` meets or exceeds a configurable threshold. |
| `blueprints/low-hp-alert.yaml` | Low HP alert | Notifies (and optionally turns a light red) when a player's **Health** sensor drops to or below a threshold. |

### Scripts

| File | Name | Description |
|------|------|-------------|
| `scripts/osrs-flash-single-light.yaml` | Flash single light | Helper script used by the **wave** blueprint. Runs a dim↔bright blink cycle on a single light. Runs in parallel mode so the wave blueprint can call it once per light concurrently. |

### Dashboards

| File | Name | Description |
|------|------|-------------|
| `dashboards/osrs-progress.yaml` | **Player Progress** (rich) | Modern, sectioned dashboard: status chips, HP/Prayer vitals, combat/total level, XP-over-time charts, an auto-discovered skills grid, recent loot & deaths, and activity counters. Needs three HACS cards (see below). |
| `dashboards/osrs-overview.yaml` | OSRS overview (core-only) | Dependency-free Lovelace view using only built-in cards — works on any HA install. Player status, vitals, combat/total level, recent deaths/loot. |

See **[Installing the dashboards](#installing-the-dashboards)** below for prerequisites and setup.

## Installation

### Blueprints

1. In Home Assistant, go to **Settings → Automations & Scenes → Blueprints**.
2. Click **Import Blueprint** (bottom right).
3. Paste the raw GitHub URL of the blueprint YAML file, e.g.:
   ```
   https://github.com/RedFirebreak/ha-osrs-data/blob/main/implementation/blueprints/flash-lights-on-event.yaml
   ```
4. Click **Preview** → **Import Blueprint**.
5. Create a new automation from the imported blueprint and configure the inputs.

Alternatively, you can manually copy the YAML file into your Home Assistant `config/blueprints/automation/osrs_data/` folder and restart.

### Scripts

The **wave** blueprint requires the `osrs_flash_single_light` helper script. Install it using one of these methods:

**Option A — UI**
1. Go to **Settings → Automations & Scenes → Scripts**.
2. Click **+ Add Script** → choose **Edit in YAML** mode.
3. Paste the contents of `scripts/osrs-flash-single-light.yaml`.
4. Save.

**Option B — YAML**
1. Add the contents of `scripts/osrs-flash-single-light.yaml` to your `scripts.yaml` file under the key `osrs_flash_single_light:`.
2. Restart Home Assistant (or reload scripts).

## Installing the dashboards

There are two example dashboards. Pick one:

- **`dashboards/osrs-progress.yaml`** — the rich "Player Progress" dashboard. Best-looking, but needs a few HACS frontend cards (below).
- **`dashboards/osrs-overview.yaml`** — a core-only fallback that uses built-in cards only. Skip the prerequisites and jump to [Add the dashboard](#3-add-the-dashboard).

### 1. Prerequisites (rich dashboard only)

Install these from **HACS → Frontend** (search by name, install, then hard-refresh your browser with `Ctrl+F5`):

| Card | Why it's needed |
|------|-----------------|
| [Mushroom](https://github.com/piitaya/lovelace-mushroom) | Modern status/vitals cards and chips |
| [apexcharts-card](https://github.com/RomRider/apexcharts-card) | XP / total-level trend charts over time |
| [auto-entities](https://github.com/thomasloven/lovelace-auto-entities) | Auto-discovers the activity-counter sensors (no slug needed) |
| [config-template-card](https://github.com/iantrich/config-template-card) | *Optional* — only for the [dropdown account switcher](#optional-multi-account-dropdown) |

> The XP/level charts stay empty until Home Assistant's recorder has logged some history — give it a few hours of play to populate.

### 2. Find your account slug

Most cards reference your character via a **slug**: your RuneScape name, lowercased, with spaces and symbols turned into underscores.

| RSN | Slug |
|-----|------|
| `Zezima` | `zezima` |
| `Lynx Titan` | `lynx_titan` |

To confirm it, open **Developer Tools → States** and filter for `sensor.osrs_` — the middle segment is your slug (e.g. `sensor.osrs_`**`zezima`**`_total_level`).

The **Skills** and **Event counters** sections auto-discover their sensors and need **no slug** — you only edit the slug for the status/vitals/progression cards.

### 3. Add the dashboard

**Method A — paste into the UI (quickest)**

1. **Settings → Dashboards → + Add Dashboard** → *New dashboard from scratch* → open it.
2. Top-right **⋮ → Edit Dashboard → ⋮ → Raw configuration editor**.
3. Copy the **`views:`** block from `osrs-progress.yaml` (or the whole `osrs-overview.yaml` view) and paste it in.
4. In the editor, **Find & Replace `myrsn` → your slug**. Save.

**Method B — YAML-mode dashboard (file-based, great for Docker/Portainer)**

`osrs-progress.yaml` is already a complete dashboard file, so you can point Home Assistant straight at it. Add to `configuration.yaml`:

```yaml
lovelace:
  mode: storage        # keep your normal UI dashboards working
  dashboards:
    osrs-progress:
      mode: yaml
      title: OSRS
      icon: mdi:sword-cross
      show_in_sidebar: true
      filename: osrs-dashboards/osrs-progress.yaml
```

Then expose the repo's dashboards folder inside the container by adding one bind-mount to your compose service (alongside the `custom_components` mount you already have):

```yaml
    volumes:
      # ...your existing mounts...
      - /path/to/ha-osrs-data/implementation/dashboards:/config/osrs-dashboards:ro
```

Re-deploy the stack (Portainer → **Update the stack**), then restart Home Assistant. You still need to set your slug once — either edit the file in the repo, or copy it out of the read-only mount to a writable path and point `filename:` there.

> While you're editing compose, you can auto-load the blueprints the same way:
> ```yaml
>       - /path/to/ha-osrs-data/implementation/blueprints:/config/blueprints/automation/osrs_data:ro
> ```
> HA discovers blueprints from that folder automatically — no config entry needed.

### Optional: multi-account dropdown

Rather than baking your slug into the cards, you can pick your character from a dropdown — handy if you play multiple accounts.

1. Create a dropdown helper (**Settings → Devices & Services → Helpers → + Create Helper → Dropdown**), or add to `configuration.yaml`:
   ```yaml
   input_select:
     osrs_account:
       name: OSRS account
       options:
         - zezima          # your slug(s)
         - lynx_titan
       icon: mdi:account-switch
   ```
2. Install **config-template-card** (see prerequisites) and wrap a card so its entity IDs are built from the dropdown. For example, the combat-level tile becomes:
   ```yaml
   - type: custom:config-template-card
     variables:
       SLUG: states['input_select.osrs_account'].state
     entities:
       - input_select.osrs_account
     card:
       type: custom:mushroom-entity-card
       entity: ${ 'sensor.osrs_' + SLUG + '_combat_level' }
       name: Combat
   ```
3. Add an `input-select` (or Mushroom select chip) card at the top of the view so you can switch accounts, and apply the same `${ 'sensor.osrs_' + SLUG + '_...' }` pattern to the other slug-bound cards.

## Blueprint Options

The two **light** blueprints (flash and wave) share the following configurable inputs:

| Input | Description | Default |
|-------|-------------|---------|
| **Event type** | Which OSRS event triggers the flash (`DEATH`, `LEVELUP`, `LOOT`, `PKLOOT`, `CLIENTSHUTDOWN`, `SUPERIORSPAWN`, `ACHIEVEMENTDIARY`, `COMBATTASK`) | *(required)* |
| **Account name** | Restrict to a specific account (leave empty for all) | *(empty)* |
| **Lights** | One or more light entities to flash | *(required)* |
| **Only flash if any light is on** | Skip flashing if all selected lights are off | `true` |
| **Change flash color** | Enable to use a custom RGB color during flashes | `false` |
| **Flash color (RGB)** | Custom color used when "Change flash color" is enabled | `[255, 160, 0]` |
| **Flash brightness** | Brightness at peak flash (1–255) | `255` |
| **Dim brightness** | Brightness at dim phase (0–255) | `40` |
| **Number of flashes** | How many dim↔bright cycles to run | `3` |
| **Transition (seconds)** | Transition time for each brightness change | `0.15` |
| **Pause (seconds)** | Pause between brightness changes | `0.25` |
| **Restore transition** | Transition time when restoring previous light state | `0.5` |

The **wave** blueprint adds one extra input:

| Input | Description | Default |
|-------|-------------|---------|
| **Stagger delay** | Delay between starting each light's blink cycle (creates the wave offset) | `0.25` |

## Usage Tips

- **Multiple events:** Import the same blueprint multiple times to react to different event types (e.g., one for `DEATH` with red lights, one for `LEVELUP` with green lights).
- **Account filtering:** Leave the account name empty to trigger for every linked RuneScape account, or set it to a specific account name to filter.
- **Light selection:** Works with any Home Assistant light entity that supports brightness control. Color options require RGB-capable lights.
- **Wave effect:** For the best wave effect, select lights in the physical order you want them to flash and adjust the stagger delay.
