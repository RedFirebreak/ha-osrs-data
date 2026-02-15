"""Parser for COMBAT_ACHIEVEMENT events."""

from __future__ import annotations

from typing import Any


def parse(extra: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Parse a COMBAT_ACHIEVEMENT event's extra data.

    Returns dict with 'summary' and 'data' keys.
    """
    tier = extra.get("tier", "Unknown")
    task = extra.get("task", "Unknown")
    task_points = extra.get("taskPoints")
    total_points = extra.get("totalPoints")
    current_tier = extra.get("currentTier")
    next_tier = extra.get("nextTier")
    just_completed_tier = extra.get("justCompletedTier")

    if just_completed_tier:
        summary = (
            f"{player_name} completed {just_completed_tier} combat achievement tier"
            f" with task: {task}"
        )
    else:
        summary = f"{player_name} completed {tier} combat task: {task}"

    data: dict[str, Any] = {
        "tier": tier,
        "task": task,
    }

    if task_points is not None:
        data["taskPoints"] = task_points
    if total_points is not None:
        data["totalPoints"] = total_points
    if current_tier is not None:
        data["currentTier"] = current_tier
    if next_tier is not None:
        data["nextTier"] = next_tier
    if just_completed_tier is not None:
        data["justCompletedTier"] = just_completed_tier

    return {"summary": summary, "data": data}
