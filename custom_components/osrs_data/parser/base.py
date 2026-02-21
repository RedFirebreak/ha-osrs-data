"""Parser for the base Runelite plugin JSON structure."""

from __future__ import annotations

from typing import Any


EQUIPMENT_SLOTS: tuple[str, ...] = (
    "HEAD",
    "CAPE",
    "WEAPON",
    "BODY",
    "LEGS",
    "GLOVES",
    "BOOTS",
    "AMMO",
    "AMMO_EXTRA",
    "AMULET",
    "RING",
    "SHIELD",
)


def parse(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a base JSON payload from the Runelite plugin.

    Returns a normalized dict with player data, or *None* if the payload
    is missing the required ``player`` key.
    """
    player = payload.get("player")
    if not player or not isinstance(player, dict):
        return None

    name = player.get("name")
    if not name:
        return None
    account_type = player.get("accountType", "normal")
    world = player.get("world")

    # ── Skills ───────────────────────────────────────────────────────
    skills: dict[str, dict[str, Any]] = {}
    stats = player.get("stats", {})
    raw_skills = stats.get("skills", {}) if isinstance(stats, dict) else {}
    for skill_name, skill_data in raw_skills.items():
        if isinstance(skill_data, dict):
            skills[skill_name] = {
                "xp": skill_data.get("xp", 0),
                "level": skill_data.get("level", 1),
            }

    # ── Inventory (max 28 slots) ─────────────────────────────────────
    inventory: list[dict[str, Any]] = []
    inv_data = player.get("inventory", {})
    inv_items = inv_data.get("items", []) if isinstance(inv_data, dict) else []
    for item in inv_items[:28]:
        if isinstance(item, dict):
            inventory.append({
                "id": item.get("id"),
                "name": item.get("name", ""),
                "gePrice": item.get("gePrice", 0),
                "haPrice": item.get("haPrice", 0),
                "quantity": item.get("quantity", 0),
            })

    # ── Equipment — normalise to per-slot dict ───────────────────────
    equipment: dict[str, dict[str, Any]] = {slot: {} for slot in EQUIPMENT_SLOTS}
    equip_data = player.get("equipment", {})
    equip_items = equip_data.get("items", []) if isinstance(equip_data, dict) else []
    for item in equip_items:
        if isinstance(item, dict):
            slot = item.get("equipmentSlot", "").upper()
            if slot in equipment:
                equipment[slot] = {
                    "id": item.get("id"),
                    "name": item.get("name", ""),
                    "gePrice": item.get("gePrice", 0),
                    "haPrice": item.get("haPrice", 0),
                    "quantity": item.get("quantity", 0),
                }

    # ── Health ────────────────────────────────────────────────────────
    health: dict[str, int] = {"current": 0, "max": 0}
    health_data = player.get("health")
    if isinstance(health_data, dict):
        health = {
            "current": health_data.get("current", 0),
            "max": health_data.get("max", 0),
        }

    # ── Prayer Points ─────────────────────────────────────────────────
    prayer_points: dict[str, int] = {"current": 0, "max": 0}
    prayer_data = player.get("prayerPoints")
    if isinstance(prayer_data, dict):
        prayer_points = {
            "current": prayer_data.get("current", 0),
            "max": prayer_data.get("max", 0),
        }

    # ── Location ─────────────────────────────────────────────────────
    location: dict[str, int] = {"x": 0, "y": 0, "plane": 0}
    location_data = player.get("location")
    if isinstance(location_data, dict):
        location = {
            "x": location_data.get("x", 0),
            "y": location_data.get("y", 0),
            "plane": location_data.get("plane", 0),
        }

    # ── Spellbook ────────────────────────────────────────────────────
    spellbook: dict[str, Any] = {"id": 0, "name": ""}
    spellbook_data = player.get("spellbook")
    if isinstance(spellbook_data, dict):
        spellbook = {
            "id": spellbook_data.get("id", 0),
            "name": spellbook_data.get("name", ""),
        }

    # ── Events ─────────────────────────────────────────────────────────
    # The RuneLite plugin sends events at the root level of the payload
    # (sibling of "player"), but earlier versions nested them inside
    # "player".  Check both locations; root-level takes precedence.
    events = payload.get("events") or player.get("events", [])
    if not isinstance(events, list):
        events = []

    # ── Tick delay (root-level) ──────────────────────────────────────
    # Number of game ticks between plugin data messages.  Used to
    # compute a per-account presence timeout (deadman's switch).
    tick_delay: int | None = None
    raw_tick = payload.get("tickDelay")
    if isinstance(raw_tick, (int, float)) and raw_tick > 0:
        tick_delay = int(raw_tick)

    return {
        "name": name,
        "accountType": account_type,
        "world": world,
        "skills": skills,
        "inventory": inventory,
        "equipment": equipment,
        "health": health,
        "prayerPoints": prayer_points,
        "location": location,
        "spellbook": spellbook,
        "events": events,
        "tickDelay": tick_delay,
    }
