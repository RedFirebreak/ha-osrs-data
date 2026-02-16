"""Parser for ACHIEVEMENT_DIARY events."""

from __future__ import annotations

from typing import Any


def parse(extra: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Parse an ACHIEVEMENT_DIARY event's extra data.

    Returns dict with 'summary' and 'data' keys.
    """
    area = extra.get("area", "Unknown")
    difficulty = extra.get("difficulty", "Unknown")
    total = extra.get("total")
    tasks_completed = extra.get("tasksCompleted")
    tasks_total = extra.get("tasksTotal")
    area_tasks_completed = extra.get("areaTasksCompleted")
    area_tasks_total = extra.get("areaTasksTotal")

    summary = f"{player_name} completed {difficulty} {area} Achievement Diary"

    data: dict[str, Any] = {
        "area": area,
        "difficulty": difficulty,
    }

    if total is not None:
        data["total"] = total
    if tasks_completed is not None:
        data["tasksCompleted"] = tasks_completed
    if tasks_total is not None:
        data["tasksTotal"] = tasks_total
    if area_tasks_completed is not None:
        data["areaTasksCompleted"] = area_tasks_completed
    if area_tasks_total is not None:
        data["areaTasksTotal"] = area_tasks_total

    return {"summary": summary, "data": data}
