"""Parser for LOOT events."""

from __future__ import annotations

from typing import Any


def parse(extra: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Parse a LOOT event's extra data.

    Returns dict with 'summary' and 'data' keys.
    """
    items = extra.get("items", [])
    source = extra.get("source", "Unknown")
    category = extra.get("category")
    kill_count = extra.get("killCount")

    total_value = sum(
        item.get("priceEach", 0) * item.get("quantity", 1) for item in items
    )
    item_names = [item.get("name", "Unknown") for item in items]
    summary = f"{player_name} looted {', '.join(item_names)} from {source}"

    parsed_items = []
    for item in items:
        parsed_item: dict[str, Any] = {
            "id": item.get("id"),
            "name": item.get("name"),
            "quantity": item.get("quantity", 1),
            "priceEach": item.get("priceEach", 0),
        }
        if "rarity" in item:
            parsed_item["rarity"] = item["rarity"]
        if "criteria" in item:
            parsed_item["criteria"] = item["criteria"]
        parsed_items.append(parsed_item)

    data: dict[str, Any] = {
        "items": parsed_items,
        "source": source,
        "totalValue": total_value,
    }

    if category is not None:
        data["category"] = category
    if kill_count is not None:
        data["killCount"] = kill_count

    return {"summary": summary, "data": data}
