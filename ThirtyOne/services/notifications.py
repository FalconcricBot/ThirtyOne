"""Safe Telegram sending helpers (rate-limit aware, never raise)."""
from __future__ import annotations

import asyncio
import html
import logging
import re

from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot):
        self.bot = bot

    async def dm(self, uid: int, text: str, kb=None, silent: bool = False) -> int | None:
        """Send a DM. Returns message_id, or None if the user blocked the bot / never started it."""
        for attempt in range(2):
            try:
                m = await self.bot.send_message(uid, text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                                disable_notification=silent, disable_web_page_preview=True)
                return m.message_id
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 0.5)
            except (Forbidden, BadRequest) as e:
                log.info("DM to %s failed: %s", uid, e)
                return None
            except TelegramError as e:
                log.warning("DM to %s failed: %s", uid, e)
                return None
        return None

    async def can_dm(self, uid: int) -> bool:
        """True if the user has started the bot (private card delivery is possible)."""
        try:
            await self.bot.send_chat_action(uid, ChatAction.TYPING)
            return True
        except (Forbidden, BadRequest):
            return False
        except TelegramError:
            return True            # transient network problem - do not block the game

    async def delete(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            return
        try:
            await self.bot.delete_message(chat_id, message_id)
        except TelegramError:
            pass

    async def broadcast(self, user_ids: list[int], text: str) -> tuple[int, int]:
        ok = fail = 0
        for uid in user_ids:
            if await self.dm(uid, text, silent=False) is not None:
                ok += 1
            else:
                fail += 1
            await asyncio.sleep(0.05)       # ~20 msg/s, below Telegram's 30/s limit
        return ok, fail


_TOKEN = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


def format_error_alert(errors: list[str], limit: int = 5) -> str:
    """Compact admin alert. Repeated messages are merged and anything that looks like a bot token is masked."""
    counts: dict[str, int] = {}
    for e in errors:
        e = _TOKEN.sub("***", e).strip()[:160]
        counts[e] = counts.get(e, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    lines = "\n".join(f"• {html.escape(m)}" + (f"  <b>×{n}</b>" if n > 1 else "") for m, n in top)
    more = len(counts) - len(top)
    return (f"🚨 <b>{len(errors)} error(s)</b> logged recently\n{lines}" + (f"\n…and {more} more kind(s)" if more > 0 else "")
            + "\n\nFull details: /logs")


async def alert_admins(notifier, admin_ids, errors: list[str]) -> int:
    """DM every admin. Returns how many were reached."""
    if not errors:
        return 0
    text = format_error_alert(errors)
    return sum([await notifier.dm(a, text, silent=False) is not None for a in admin_ids])
