"""Parser for DEATH events."""

from __future__ import annotations

from typing import Any


def parse(extra: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Parse a DEATH event's extra data.

    Returns dict with 'summary' and 'data' keys.
    """
    value_lost = extra.get("valueLost", 0)
    is_pvp = extra.get("isPvp", False)
    killer_name = extra.get("killerName")
    killer_npc_id = extra.get("killerNpcId")
    kept_items = extra.get("keptItems", [])
    lost_items = extra.get("lostItems", [])
    location = extra.get("location")

    if is_pvp and killer_name:
        summary = f"{player_name} was killed by {killer_name} (PvP), lost {value_lost} gp"
    elif killer_name:
        summary = f"{player_name} was killed by {killer_name}, lost {value_lost} gp"
    else:
        summary = f"{player_name} died, lost {value_lost} gp"

    data: dict[str, Any] = {
        "valueLost": value_lost,
        "isPvp": is_pvp,
        "keptItems": kept_items,
        "lostItems": lost_items,
    }

    if killer_name is not None:
        data["killerName"] = killer_name
    if killer_npc_id is not None:
        data["killerNpcId"] = killer_npc_id
    if location is not None:
        data["location"] = location

    return {"summary": summary, "data": data}
