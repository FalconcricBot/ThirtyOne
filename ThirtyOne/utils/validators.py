from __future__ import annotations

import re

_ROOM = re.compile(r"^(BA|31)?-?(\d{5})$", re.I)


def parse_room_code(text: str | None) -> str | None:
    """'ba-82941' / '82941' / 'BA82941' -> 'BA-82941';  '31-82941' -> '31-82941'."""
    m = _ROOM.match((text or "").strip())
    return f"{(m.group(1) or 'BA').upper()}-{m.group(2)}" if m else None


def parse_tournament_args(text: str) -> dict:
    """'Name | capacity | start_in_min | [deadline_in_min] | [description]'"""
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        raise ValueError("Use: /create_tournament Name | capacity | start_in_minutes | deadline_minutes(optional) | description(optional)")
    name = parts[0][:60]
    if not name:
        raise ValueError("Tournament name is empty.")
    try:
        capacity, start_min = int(parts[1]), int(parts[2])
        deadline_min = int(parts[3]) if len(parts) > 3 and parts[3] else start_min
    except ValueError:
        raise ValueError("Capacity and minutes must be numbers.") from None
    if not 2 <= capacity <= 64:
        raise ValueError("Capacity must be between 2 and 64.")
    if not 1 <= start_min <= 60 * 24 * 14 or not 1 <= deadline_min <= start_min:
        raise ValueError("Start must be 1 min - 14 days away and the deadline cannot be after the start.")
    return {"name": name, "capacity": capacity, "start_min": start_min, "deadline_min": deadline_min,
            "description": (parts[4] if len(parts) > 4 else "")[:300]}


def valid_card_code(code: str) -> bool:
    return bool(re.fullmatch(r"[A3KQJ76542][HDCS]", code or ""))
