from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}


def normalize_db_url(url: str) -> str:
    """Accept sqlite / postgres URLs from hosts (Railway, Render, Heroku) and make them async."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    bot_username: str = os.getenv("BOT_USERNAME", "Deck31Bot").lstrip("@")
    admin_ids: set[int] = field(default_factory=lambda: _ids(os.getenv("ADMIN_IDS", "")))
    owner_ids: set[int] = field(default_factory=lambda: _ids(os.getenv("OWNER_IDS", "")))   # get the special gold owner card
    database_url: str = normalize_db_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///briscola.db"))
    turn_timeout: int = int(os.getenv("TURN_TIMEOUT", "45"))
    # auto_play: server plays a card for the AFK player; forfeit: AFK player loses at once
    timeout_policy: str = os.getenv("TIMEOUT_POLICY", "auto_play")
    afk_strikes_limit: int = int(os.getenv("AFK_STRIKES_LIMIT", "2"))
    room_ttl_minutes: int = int(os.getenv("ROOM_TTL_MINUTES", "15"))
    trump_mode: str = os.getenv("TRUMP_MODE", "bottom_card")
    default_images: bool = os.getenv("DEFAULT_IMAGES", "1") == "1"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


    @property
    def owners(self) -> set[int]:
        """OWNER_IDS, or - if unset and there is exactly one admin - that admin."""
        return self.owner_ids or (self.admin_ids if len(self.admin_ids) == 1 else set())


settings = Settings()
