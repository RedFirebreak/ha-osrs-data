# Implementation Examples

Ready-to-use Home Assistant blueprints and scripts for the [OSRS Data](../README.md) integration.

## Contents

### Blueprints

| File | Name | Description |
|------|------|-------------|
| `blueprints/flash-lights-on-event.yaml` | Flash lights on event | Flashes selected lights when an OSRS event fires. Supports custom flash color, brightness, flash count, and transition speed. Automatically restores previous light states after flashing. |
| `blueprints/wave-lights-on-event.yaml` | Wave lights on event | Staggers light flashes one-by-one across multiple lights for a chase/wave effect. Each light runs its own independent blink cycle, offset by a configurable delay. Requires the helper script below. |

### Scripts

| File | Name | Description |
|------|------|-------------|
| `scripts/osrs-flash-single-light.yaml` | Flash single light | Helper script used by the **wave** blueprint. Runs a dim↔bright blink cycle on a single light. Runs in parallel mode so the wave blueprint can call it once per light concurrently. |

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

## Blueprint Options

Both blueprints share the following configurable inputs:

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
