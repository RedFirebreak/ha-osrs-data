"""Parser for COLLECTION events (Collection Log slots)."""

from __future__ import annotations

from typing import Any


def parse(extra: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Parse a COLLECTION event's extra data.

    Returns dict with 'summary' and 'data' keys.
    """
    item_name = extra.get("itemName", "Unknown")
    item_id = extra.get("itemId")
    price = extra.get("price")
    completed_entries = extra.get("completedEntries")
    total_entries = extra.get("totalEntries")

    summary = f"{player_name} added {item_name} to their collection log"

    data: dict[str, Any] = {
        "itemName": item_name,
    }

    if item_id is not None:
        data["itemId"] = item_id
    if price is not None:
        data["price"] = price
    if completed_entries is not None:
        data["completedEntries"] = completed_entries
    if total_entries is not None:
        data["totalEntries"] = total_entries

    # Rank progression fields
    for key in (
        "currentRank",
        "rankProgress",
        "logsNeededForNextRank",
        "nextRank",
        "justCompletedRank",
    ):
        if key in extra:
            data[key] = extra[key]

    # Dropper info (not always present)
    for key in ("dropperName", "dropperType", "dropperKillCount"):
        if key in extra:
            data[key] = extra[key]

    return {"summary": summary, "data": data}
