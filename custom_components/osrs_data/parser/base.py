"""Parser for the base Runelite plugin JSON structure.

The payload is untrusted input: a value of the wrong type skips that
section or field (with a debug log) instead of raising, so bad input can
never turn into a 5xx that the plugin would retry.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _skip(what: str, value: Any) -> None:
    _LOGGER.debug("Skipping %s: unexpected %s", what, type(value).__name__)


def _parse_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one inventory/equipment item; wrong-typed fields get defaults."""
    item_id = item.get("id")
    name = item.get("name", "")
    parsed: dict[str, Any] = {
        "id": item_id if _is_int(item_id) else None,
        "name": name if isinstance(name, str) else "",
    }
    for field in ("gePrice", "haPrice", "quantity"):
        value = item.get(field, 0)
        parsed[field] = value if _is_number(value) else 0
    return parsed


def _parse_items(section: str, data: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return the section's item objects, or None if ``items`` isn't a list."""
    items = data.get("items", [])
    if not isinstance(items, list):
        _skip(f"{section} items", items)
        return None
    return [item for item in items if isinstance(item, dict)]


def _object_section(player: dict[str, Any], section: str) -> dict[str, Any] | None:
    """Return ``player[section]`` if it is an object.

    Returns None if the section is absent or null (not sent), or of the
    wrong type (skipped with a debug log).
    """
    data = player.get(section)
    if data is not None and not isinstance(data, dict):
        _skip(section, data)
        return None
    return data


def _parse_numbers(
    section: str, data: dict[str, Any], fields: tuple[str, ...]
) -> dict[str, Any] | None:
    """Return *fields* of a section (missing ones are 0).

    Returns None, skipping the whole section, if any field isn't a number.
    """
    result = {field: data.get(field, 0) for field in fields}
    for field, value in result.items():
        if not _is_number(value):
            _skip(f"{section} ({field})", value)
            return None
    return result


def parse(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a base JSON payload from the Runelite plugin.

    Returns a normalized dict with player data, or *None* if the payload
    has no usable ``player`` (an object with a non-blank string ``name``).
    The sections inventory, equipment, health, prayerPoints, location
    and spellbook are only in the result when the payload has them: the
    plugin's per-connection filters can leave any of them out, and a
    section of the wrong shape is left out too.
    """
    player = payload.get("player")
    if not player or not isinstance(player, dict):
        return None

    name = player.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    account_type = player.get("accountType", "normal")
    if not isinstance(account_type, (str, int)) or isinstance(account_type, bool):
        _skip("accountType", account_type)
        account_type = "normal"
    world = player.get("world")
    if not isinstance(world, (str, int)) or isinstance(world, bool):
        if world is not None:
            _skip("world", world)
        world = None

    # Sections that were received (absent or null ones are left out).
    result: dict[str, Any] = {}

    # ── Skills ───────────────────────────────────────────────────────
    skills: dict[str, dict[str, Any]] = {}
    stats = player.get("stats", {})
    raw_skills = stats.get("skills", {}) if isinstance(stats, dict) else {}
    if not isinstance(raw_skills, dict):
        _skip("skills", raw_skills)
        raw_skills = {}
    for skill_name, skill_data in raw_skills.items():
        if not isinstance(skill_data, dict):
            _skip(f"skill {skill_name}", skill_data)
            continue
        xp = skill_data.get("xp", 0)
        level = skill_data.get("level", 1)
        if not _is_number(xp) or not _is_number(level):
            _skip(f"skill {skill_name}", xp if not _is_number(xp) else level)
            continue
        skills[skill_name] = {"xp": xp, "level": level}

    # ── Inventory (max 28 slots) ─────────────────────────────────────
    inv_data = _object_section(player, "inventory")
    if inv_data is not None and (inv_items := _parse_items("inventory", inv_data)) is not None:
        result["inventory"] = [_parse_item(item) for item in inv_items[:28]]

    # ── Equipment — normalise to per-slot dict ───────────────────────
    equip_data = _object_section(player, "equipment")
    if equip_data is not None and (equip_items := _parse_items("equipment", equip_data)) is not None:
        equipment: dict[str, dict[str, Any]] = {slot: {} for slot in EQUIPMENT_SLOTS}
        for item in equip_items:
            slot = item.get("equipmentSlot")
            if not isinstance(slot, str):
                _skip("equipment item without a slot", slot)
                continue
            if slot.upper() in equipment:
                equipment[slot.upper()] = _parse_item(item)
        result["equipment"] = equipment

    # ── Health, prayer points, location ──────────────────────────────
    number_sections: dict[str, tuple[str, ...]] = {
        "health": ("current", "max"),
        "prayerPoints": ("current", "max"),
        "location": ("x", "y", "plane"),
    }
    for section, fields in number_sections.items():
        data = _object_section(player, section)
        if data is not None and (numbers := _parse_numbers(section, data, fields)) is not None:
            result[section] = numbers

    # ── Spellbook ────────────────────────────────────────────────────
    spellbook_data = _object_section(player, "spellbook")
    if spellbook_data is not None:
        spellbook_id = spellbook_data.get("id", 0)
        spellbook_name = spellbook_data.get("name", "")
        if _is_int(spellbook_id) and isinstance(spellbook_name, str):
            result["spellbook"] = {"id": spellbook_id, "name": spellbook_name}
        else:
            _skip("spellbook", spellbook_data)

    # ── Events ─────────────────────────────────────────────────────────
    # The RuneLite plugin sends events at the root level of the payload
    # (sibling of "player"), but earlier versions nested them inside
    # "player".  Check both locations; root-level takes precedence.
    events = payload.get("events") or player.get("events", [])
    if not isinstance(events, list):
        events = []
    # Only well-formed events (an object with a string ``type``) survive,
    # so one malformed entry can't break processing of the others.
    events = [
        ev for ev in events
        if isinstance(ev, dict) and isinstance(ev.get("type"), str)
    ]

    # ── Tick delay (root-level) ──────────────────────────────────────
    # Number of game ticks between plugin data messages.  Used to
    # compute a per-account presence timeout (deadman's switch).
    tick_delay: int | None = None
    raw_tick = payload.get("tickDelay")
    if _is_number(raw_tick) and raw_tick > 0:
        tick_delay = int(raw_tick)

    # ── Game state (root-level) ──────────────────────────────────────
    # The RuneLite client's current game state (e.g. LOGGED_IN,
    # LOGIN_SCREEN, CONNECTION_LOST).  Defaults to UNKNOWN.
    _VALID_GAME_STATES = {
        "UNKNOWN",
        "STARTING",
        "LOGIN_SCREEN",
        "LOGIN_SCREEN_AUTHENTICATOR",
        "LOGGING_IN",
        "LOADING",
        "LOGGED_IN",
        "CONNECTION_LOST",
        "HOPPING",
    }
    raw_state = payload.get("state")
    game_state: str = "UNKNOWN"
    if isinstance(raw_state, str) and raw_state.upper() in _VALID_GAME_STATES:
        game_state = raw_state.upper()

    # ── Optional fields from newer plugin versions ───────────────────
    # All are optional; missing or malformed values never fail the parse.
    # ``accountHash`` is a salted SHA-224 hex digest (never the raw
    # RuneLite hash).  Per-event ``eventId``/``timestamp`` pass through
    # untouched inside ``events``.
    raw_account_hash = player.get("accountHash")
    account_hash: str | None = (
        raw_account_hash.strip()
        if isinstance(raw_account_hash, str) and raw_account_hash.strip()
        else None
    )

    raw_world_types = player.get("worldTypes")
    world_types: list[str] = []
    if isinstance(raw_world_types, list):
        world_types = [
            wt.upper() for wt in raw_world_types if isinstance(wt, str) and wt
        ]

    return {
        "name": name,
        "accountType": account_type,
        "world": world,
        "skills": skills,
        **result,
        "events": events,
        "tickDelay": tick_delay,
        "state": game_state,
        "timestamp": payload.get("timestamp"),
        "accountHash": account_hash,
        "worldTypes": world_types,
    }
