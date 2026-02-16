"""Parser for LEVEL events."""

from __future__ import annotations

from typing import Any


def parse(extra: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Parse a LEVEL event's extra data.

    Returns dict with 'summary' and 'data' keys.
    """
    levelled = extra.get("levelledSkills", {})
    combat_level = extra.get("combatLevel", {})

    skills_str = ", ".join(
        f"{skill} → {level}" for skill, level in levelled.items()
    )
    summary = f"{player_name} levelled {skills_str}" if skills_str else (
        f"{player_name} levelled up"
    )

    data: dict[str, Any] = {
        "levelledSkills": levelled,
    }

    all_skills = extra.get("allSkills", {})
    if all_skills:
        data["allSkills"] = all_skills

    if combat_level:
        data["combatLevel"] = combat_level.get("value")
        data["combatLevelIncreased"] = combat_level.get("increased", False)

    return {"summary": summary, "data": data}
