from __future__ import annotations

import html
import random
import re
from datetime import datetime, timezone

from game.cards import card

SUIT_SYMBOLS = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
SUIT_LABELS = {"H": "♥ Hearts", "D": "♦ Diamonds", "C": "♣ Clubs", "S": "♠ Spades"}
DIV = "━━━━━━━━━━━━━━━━━━"


def header(emoji: str, title: str, sub: str | None = None) -> str:
    """Simple screen header (bold title, small italic subtitle, divider). Plain text only - renders the same on
    every Telegram client, unlike box-drawing corners which break in proportional fonts."""
    return f"{emoji} <b>{title}</b>" + (f"\n<i>{sub}</i>" if sub else "") + f"\n{DIV}"


def utcnow() -> datetime:
    """Naive UTC datetime (consistent across SQLite and PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def esc(s: str | None) -> str:
    return html.escape(s or "", quote=False)


def fmt_num(n: int | float) -> str:
    return f"{int(n):,}"


def clean_name(name: str | None, fallback: str = "Player", limit: int = 22) -> str:
    name = re.sub(r"\s+", " ", (name or "")).strip()
    return (name[:limit] or fallback)


def card_label(code: str) -> str:
    return str(card(code))


def new_room_code(existing: set[str], prefix: str = "BA") -> str:
    while True:
        code = f"{prefix}-{random.randint(10000, 99999)}"
        if code not in existing:
            return code


def bar(value: int, total: int, width: int = 10) -> str:
    total = max(total, 1)
    filled = max(0, min(width, round(width * value / total)))
    return "▰" * filled + "▱" * (width - filled)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{esc(name)}</a>'
