from __future__ import annotations

import logging

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from config import settings
from database.models import Base

log = logging.getLogger(__name__)


def make_engine(url: str | None = None) -> AsyncEngine:
    url = url or settings.database_url
    kw: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"timeout": 30}
    engine = create_async_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _pragmas(dbapi_conn, _):              # WAL = readers don't block the writer
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


def _ensure_columns(sync_conn) -> None:
    """Tiny safety net for databases created before a column existed (same change as migration 0002)."""
    insp = inspect(sync_conn)
    cols = {c["name"] for c in insp.get_columns("player_profiles")}
    if "profile_template" not in cols:
        sync_conn.execute(text("ALTER TABLE player_profiles ADD COLUMN profile_template VARCHAR(10) NOT NULL DEFAULT 'face'"))
    tcols = {c["name"] for c in insp.get_columns("tournaments")}
    if "game" not in tcols:                                   # migration 0003
        sync_conn.execute(text("ALTER TABLE tournaments ADD COLUMN game VARCHAR(12) NOT NULL DEFAULT 'briscola'"))


async def init_db(engine: AsyncEngine) -> None:
    """Create missing tables. In production prefer `alembic upgrade head` (see README)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)
    log.info("Database ready")
