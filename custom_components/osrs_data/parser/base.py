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

    name = player.get("name", "Unknown")
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
                    "name": item.get("name", ""),
                    "gePrice": item.get("gePrice", 0),
                    "haPrice": item.get("haPrice", 0),
                    "quantity": item.get("quantity", 0),
                }

    # ── Events (future use, initially empty) ─────────────────────────
    events = player.get("events", [])
    if not isinstance(events, list):
        events = []

    return {
        "name": name,
        "accountType": account_type,
        "world": world,
        "skills": skills,
        "inventory": inventory,
        "equipment": equipment,
        "events": events,
    }
