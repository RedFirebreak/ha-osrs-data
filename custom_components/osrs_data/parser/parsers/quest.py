"""Parser for QUEST events."""

from __future__ import annotations

from typing import Any


def parse(extra: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Parse a QUEST event's extra data.

    Returns dict with 'summary' and 'data' keys.
    """
    quest_name = extra.get("questName", "Unknown")
    completed_quests = extra.get("completedQuests")
    total_quests = extra.get("totalQuests")
    quest_points = extra.get("questPoints")
    total_quest_points = extra.get("totalQuestPoints")

    summary = f"{player_name} completed quest: {quest_name}"

    data: dict[str, Any] = {
        "questName": quest_name,
    }

    if completed_quests is not None:
        data["completedQuests"] = completed_quests
    if total_quests is not None:
        data["totalQuests"] = total_quests
    if quest_points is not None:
        data["questPoints"] = quest_points
    if total_quest_points is not None:
        data["totalQuestPoints"] = total_quest_points

    return {"summary": summary, "data": data}
