# Sample Runelite Plugin POST Request

The Runelite plugin sends JSON payloads to the `/api/osrs-data/events` endpoint
with an `X-Osrs-Token` header for authentication.

## Headers

```
Content-Type: application/json
X-Osrs-Token: <device-token>
X-Osrs-Exporter-Version: 1.4
```

## Example Payload

```json
{
    "player": {
        "name": "PlayerOne",
        "accountHash": "de731bc0f710567a6a0e852bbe79eb5fa8daf37d4140440a774591f0",
        "accountType": "0",
        "world": "302",
        "worldTypes": ["MEMBERS"],
        "stats": {
            "skills": {
                "Attack": { "xp": 737627, "level": 60 },
                "Defence": { "xp": 123456, "level": 50 },
                "Strength": { "xp": 900000, "level": 70 },
                "Hitpoints": { "xp": 1234567, "level": 75 },
                "Ranged": { "xp": 500000, "level": 55 },
                "Prayer": { "xp": 200000, "level": 43 },
                "Magic": { "xp": 400000, "level": 59 },
                "Cooking": { "xp": 300000, "level": 52 },
                "Woodcutting": { "xp": 600000, "level": 58 },
                "Fletching": { "xp": 100000, "level": 40 },
                "Fishing": { "xp": 700000, "level": 62 },
                "Firemaking": { "xp": 250000, "level": 48 },
                "Crafting": { "xp": 150000, "level": 42 },
                "Smithing": { "xp": 80000, "level": 37 },
                "Mining": { "xp": 350000, "level": 50 },
                "Herblore": { "xp": 50000, "level": 30 },
                "Agility": { "xp": 450000, "level": 55 },
                "Thieving": { "xp": 200000, "level": 45 },
                "Slayer": { "xp": 300000, "level": 50 },
                "Farming": { "xp": 100000, "level": 38 },
                "Runecraft": { "xp": 75000, "level": 35 },
                "Hunter": { "xp": 120000, "level": 40 },
                "Construction": { "xp": 90000, "level": 35 }
            }
        },
        "inventory": {
            "items": [
                { "name": "Abyssal whip", "gePrice": 1500000, "haPrice": 72000, "quantity": 1 },
                { "name": "Shark", "gePrice": 800, "haPrice": 600, "quantity": 10 },
                { "name": "Super combat potion(4)", "gePrice": 12000, "haPrice": 5000, "quantity": 3 }
            ]
        },
        "health": {
            "current": 75,
            "max": 99
        },
        "prayerPoints": {
            "current": 43,
            "max": 43
        },
        "location": {
            "x": 1416,
            "y": 3350,
            "plane": 0
        },
        "spellbook": {
            "id": 3,
            "name": "arceuus"
        },
        "equipment": {
            "items": [
                { "name": "Neitiznot faceguard", "gePrice": 3500000, "haPrice": 60000, "quantity": 1, "equipmentSlot": "HEAD" },
                { "name": "Fire cape", "gePrice": 0, "haPrice": 0, "quantity": 1, "equipmentSlot": "CAPE" },
                { "name": "Abyssal whip", "gePrice": 1500000, "haPrice": 72000, "quantity": 1, "equipmentSlot": "WEAPON" },
                { "name": "Fighter torso", "gePrice": 0, "haPrice": 0, "quantity": 1, "equipmentSlot": "BODY" },
                { "name": "Obsidian platelegs", "gePrice": 900000, "haPrice": 60000, "quantity": 1, "equipmentSlot": "LEGS" },
                { "name": "Barrows gloves", "gePrice": 0, "haPrice": 0, "quantity": 1, "equipmentSlot": "GLOVES" },
                { "name": "Dragon boots", "gePrice": 200000, "haPrice": 30000, "quantity": 1, "equipmentSlot": "BOOTS" },
                { "name": "Amulet of fury", "gePrice": 2500000, "haPrice": 150000, "quantity": 1, "equipmentSlot": "AMULET" },
                { "name": "Berserker ring (i)", "gePrice": 3000000, "haPrice": 45000, "quantity": 1, "equipmentSlot": "RING" },
                { "name": "Dragon defender", "gePrice": 0, "haPrice": 0, "quantity": 1, "equipmentSlot": "SHIELD" }
            ]
        }
    },
    "events": [
        {
            "type": "collectionLog",
            "data": { "itemName": "Abyssal whip", "itemId": 4151, "value": 1500000, "killCount": 312 },
            "eventId": "3f2c9a4e-8d1b-4c6e-9f0a-2b7d5e1c8a90",
            "timestamp": 1735689600000
        }
    ],
    "state": "LOGGED_IN",
    "tickDelay": 100,
    "timestamp": 1735689600123
}
```

## Sensor Mapping

| Sensor | State | Attributes |
|--------|-------|------------|
| Player Info | Player name | `display_name`, `previous_names`, `account_type`, `world`, `world_types`, `last_update`, `plugin_version`, `events` |
| Last Collection Log | Most recent new collection log item | `item_id`, `value`, `kill_count`, `timestamp`, `recent` |
| Inventory | Number of items | `items` (list), `slots_used`, `slots_total` (28) |
| Health | Current hitpoints | `current`, `max`, `last_update` |
| Prayer Points | Current prayer points | `current`, `max`, `last_update` |
| Location | Tile coordinates (x, y) | `x`, `y`, `plane`, `last_update` |
| Spellbook | Active spellbook name | `id`, `last_update` |
| Game State | RuneLite client game state | `last_update` |
| Equipment | Number of equipped slots | One key per slot: `HEAD`, `CAPE`, `WEAPON`, `BODY`, `LEGS`, `GLOVES`, `BOOTS`, `AMMO`, `AMMO_EXTRA`, `AMULET`, `RING`, `SHIELD` |
| `<Skill> XP` | XP value | `skill` |
| `<Skill> Level` | Level value | `skill` |
