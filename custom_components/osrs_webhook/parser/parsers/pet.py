"""Parser for PET events."""

from __future__ import annotations

from typing import Any


def parse(extra: dict[str, Any], player_name: str) -> dict[str, Any]:
    """Parse a PET event's extra data.

    Returns dict with 'summary' and 'data' keys.
    """
    pet_name = extra.get("petName")
    milestone = extra.get("milestone")
    duplicate = extra.get("duplicate", False)

    if pet_name:
        summary = f"{player_name} received pet: {pet_name}"
        if duplicate:
            summary += " (duplicate)"
    else:
        summary = f"{player_name} received a pet"

    data: dict[str, Any] = {
        "petName": pet_name,
        "duplicate": duplicate,
    }

    if milestone is not None:
        data["milestone"] = milestone

    return {"summary": summary, "data": data}
