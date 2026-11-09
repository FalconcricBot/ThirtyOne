"""Shared Telegram publishing helper: edit a message in place, re-send if it vanished or changed type.
(Used by the 31 game; the Briscola manager keeps its own equivalent so it stays untouched.)"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from telegram import InputMediaPhoto
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut

log = logging.getLogger(__name__)


@dataclass
class MsgRef:
    message_id: int
    kind: str                    # 'photo' | 'text'


class Publisher:
    def __init__(self, bot, notifier):
        self.bot, self.notifier = bot, notifier

    async def send_new(self, chat_id: int, kind: str, text: str, data, kb) -> MsgRef:
        if kind == "photo":
            m = await self.bot.send_photo(chat_id, data, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            m = await self.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                            disable_web_page_preview=True)
        return MsgRef(m.message_id, kind)

    async def upsert(self, chat_id: int, ref: MsgRef | None, text: str, photo, kb) -> tuple[MsgRef | None, bool]:
        """-> (new ref, blocked). `blocked` is True when the user blocked the bot / left the chat."""
        kind = "photo" if photo is not None else "text"
        data = photo.getvalue() if photo is not None else None
        for _ in range(2):
            try:
                if ref and ref.kind == kind:
                    if kind == "photo":
                        await self.bot.edit_message_media(chat_id=chat_id, message_id=ref.message_id, reply_markup=kb,
                                                          media=InputMediaPhoto(data, caption=text, parse_mode=ParseMode.HTML))
                    else:
                        await self.bot.edit_message_text(text, chat_id=chat_id, message_id=ref.message_id,
                                                         parse_mode=ParseMode.HTML, reply_markup=kb)
                    return ref, False
                if ref:
                    await self.notifier.delete(chat_id, ref.message_id)
                return await self.send_new(chat_id, kind, text, data, kb), False
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 0.5)
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    return ref, False
                log.info("edit failed (%s) - resending", e)
                ref = None
            except Forbidden:
                log.info("chat %s blocked the bot", chat_id)
                return None, True
            except (TimedOut, NetworkError) as e:
                log.warning("network problem while publishing: %s", e)
                return ref, False
            except TelegramError as e:
                log.error("telegram error while publishing: %s", e)
                return ref, False
        return ref, False
