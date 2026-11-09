"""Handler guards: user upsert, ban check, admin check, private-only, crash isolation."""
from __future__ import annotations

import functools
import logging

from telegram import InputMediaPhoto, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from config import settings
from utils.ratelimit import limiter

log = logging.getLogger(__name__)


def deps(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["c"]


async def reply(update: Update, text: str, **kw):
    if update.callback_query:
        await update.callback_query.answer(text[:190], show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(text, **kw)


def guard(*, admin: bool = False, private: bool = False, allow_banned: bool = False):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
            user = update.effective_user
            if user is None or user.is_bot:
                return
            try:
                c = deps(context)
                if user.id not in settings.admin_ids and not limiter.allow(user.id):
                    if update.callback_query:
                        await update.callback_query.answer("⏳ Too fast — slow down a little.")
                    elif limiter.should_warn(user.id) and update.effective_message:
                        await update.effective_message.reply_text("⏳ Too fast — slow down a little.")
                    return
                if admin and user.id not in settings.admin_ids:
                    await reply(update, "⛔ Admins only.")
                    return
                chat = update.effective_chat
                if private and chat and chat.type != ChatType.PRIVATE:
                    await reply(update, "💬 Please use this in a private chat with the bot.")
                    return
                if not allow_banned and await c.repo.is_banned(user.id):
                    await reply(update, "🚫 You are banned from Thirty One.")
                    return
                _, created = await c.repo.upsert_user(user.id, user.username, user.full_name)
                context.user_data["is_new"] = created
                return await fn(update, context, *a, **kw)
            except Exception:
                log.exception("Handler %s crashed (user=%s)", fn.__name__, user.id)
                try:
                    await reply(update, "⚠️ Something went wrong. Please try again.")
                except Exception:
                    pass
        return wrapper
    return deco


async def ack(update: Update, text: str | None = None, alert: bool = False) -> None:
    """Answer a callback query exactly once (never raises)."""
    q = update.callback_query
    if q:
        try:
            await q.answer(text[:190] if text else None, show_alert=alert)
        except TelegramError:
            pass


async def respond(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, kb=None,
                  photo: bytes | None = None) -> None:
    """Edit the message a button was pressed on (or send a new one). Handles text<->photo switches."""
    q, chat = update.callback_query, update.effective_chat
    if q and q.message:
        msg = q.message
        try:
            if photo is None and not msg.photo:
                await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                          disable_web_page_preview=True)
                return
            if photo is not None and msg.photo:
                await q.edit_message_media(InputMediaPhoto(photo, caption=text, parse_mode=ParseMode.HTML),
                                           reply_markup=kb)
                return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
        try:
            await msg.delete()
        except TelegramError:
            pass
    if photo is not None:
        await context.bot.send_photo(chat.id, photo, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                       disable_web_page_preview=True)
