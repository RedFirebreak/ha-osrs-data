# 🎮 OSRS Dashboard Cards for Home Assistant

Pre-built Lovelace dashboard cards that display real-time Old School RuneScape
player data from the [OSRS Data](../README.md) integration.

---

## 📦 Available Cards

| Card | File | Description |
|------|------|-------------|
| **Player Overview** | [`cards/player_overview_card.yaml`](cards/player_overview_card.yaml) | Player name, combat level, total level, HP/prayer summary, world, account type |
| **Skill/Stats Grid** | [`cards/skill_stats_card.yaml`](cards/skill_stats_card.yaml) | All 23 OSRS skills in a grid with emoji icons, levels, and XP — styled like the in-game interface |
| **Health & Prayer** | [`cards/health_prayer_card.yaml`](cards/health_prayer_card.yaml) | HP and prayer bars with OSRS-themed colors and orb-style layout |
| **Inventory** | [`cards/inventory_card.yaml`](cards/inventory_card.yaml) | Current inventory items with quantities and GE prices |
| **Equipment** | [`cards/equipment_card.yaml`](cards/equipment_card.yaml) | Equipment screen layout showing all gear slots |
| **Closest to Level Up** | [`cards/closest_level_up_card.yaml`](cards/closest_level_up_card.yaml) | Which skill is closest to leveling, with XP remaining and progress bar |
| **Top 5 Skills to 99** | [`cards/top_skills_card.yaml`](cards/top_skills_card.yaml) | Highest non-99 skills with progress bars toward 99 |
| **XP Summary** | [`cards/xp_summary_card.yaml`](cards/xp_summary_card.yaml) | Total XP, total level, and per-skill XP breakdown |
| **Full Dashboard** | [`full_dashboard.yaml`](full_dashboard.yaml) | All cards assembled into a single complete dashboard |

---

## 🚀 Quick Start

### 1. Install Helpers & Template Sensors

Before using the dashboard cards, you need the player selector and template
sensors. See [`custom_helpers/installation.md`](../custom_helpers/installation.md)
for detailed steps.

**Short version:**
1. Add `input_select.osrs_player_selector` (via UI or YAML)
2. Add template sensors from `custom_helpers/template_sensors.yaml`
3. Restart Home Assistant

### 2. Add Cards to Your Dashboard

**Option A: Full Dashboard**
1. In HA, go to **Settings → Dashboards → + Add Dashboard**
2. Choose **Start with an empty dashboard**
3. Click the three-dot menu → **Raw configuration editor**
4. Paste the contents of [`full_dashboard.yaml`](full_dashboard.yaml)
5. Save

**Option B: Individual Cards**
1. Edit an existing dashboard
2. Click **+ Add Card → Manual**
3. Paste the YAML from any card file in the `cards/` folder
4. Save

### 3. Select Your Player

Each card reads from `input_select.osrs_player_selector`. Change the
dropdown to switch between players — all cards update automatically.

---

## 🖼️ Card Previews

### Player Overview
Shows player name, account type badge, world, combat level, total level,
and total XP at a glance.

### Skills Grid
```
 ⚔️        ❤️        ⛏️
Attack    Hitpoints   Mining
  60        75         50
737,627   1,234,567  350,000 xp

 💪        🏃        🔨
Strength  Agility    Smithing
  70        55         37
900,000   450,000    80,000 xp
  ...       ...        ...
```

### Health & Prayer Bars
```
❤️ Hitpoints     75 / 99
████████████████░░░░░░  76%

✨ Prayer         43 / 43
██████████████████████  100%
```

### Closest to Level Up
```
        ⚔️
      Attack
  Level 60 → 61

  ██████████████████░░  91.2%

  6,818 XP remaining
```

### Equipment Layout
```
           🪖 HEAD
     🧣 CAPE  📿 AMULET  🏹 AMMO
  ⚔️ WEAPON  👕 BODY  🛡️ SHIELD
           👖 LEGS
  🧤 GLOVES  🥾 BOOTS  💍 RING
```

---

## 🎨 Customization

### Styling (requires card-mod)

Cards include `card_mod` style blocks for dark OSRS-themed backgrounds and
colored borders. Install [card-mod](https://github.com/thomasloven/lovelace-card-mod)
via HACS for these styles to take effect.

Without card-mod, cards still work perfectly — they just use your theme's
default card background.

### Icons

Cards use Unicode emoji for universal compatibility. To use actual OSRS
skill icons from the wiki, replace emoji references with image tags:

```html
<img src="https://oldschool.runescape.wiki/images/Attack_icon.png"
     style="height:20px; vertical-align:middle;" />
```

For item icons, use the RuneLite cache:
```
https://static.runelite.net/cache/item/icon/<ITEM_ID>.png
```

### Themes

The dark gradient backgrounds work best with HA dark themes. For light
themes, adjust the `background` and `border` values in the `card_mod`
style blocks.

---

## 🔧 Optional HACS Cards

These HACS frontend cards enhance the dashboard but are **not required**:

| Card | Purpose |
|------|---------|
| [card-mod](https://github.com/thomasloven/lovelace-card-mod) | Custom CSS styling on any card |
| [layout-card](https://github.com/thomasloven/lovelace-layout-card) | Grid and masonry dashboard layouts |
| [mushroom](https://github.com/piitaya/lovelace-mushroom) | Beautiful minimal template cards |
| [bar-card](https://github.com/custom-cards/bar-card) | Animated progress bars |

---

## 📁 File Structure

```
dashboard/
├── README.md                         ← You are here
├── full_dashboard.yaml               ← Complete assembled dashboard
└── cards/
    ├── player_overview_card.yaml     ← Player summary
    ├── skill_stats_card.yaml         ← All skills grid
    ├── health_prayer_card.yaml       ← HP & prayer bars
    ├── inventory_card.yaml           ← Inventory list
    ├── equipment_card.yaml           ← Equipment slots
    ├── closest_level_up_card.yaml    ← Nearest level-up
    ├── top_skills_card.yaml          ← Top 5 to 99
    └── xp_summary_card.yaml          ← XP breakdown
```
