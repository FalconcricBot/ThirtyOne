"""Quick match queue and practice vs AI."""
from __future__ import annotations

import logging
import random

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from keyboards.room_keyboard import ai_level_kb, ai_mode_kb, mode_kb, quick_kb
from services.game_manager import PlayerInfo
from services.matchmaking import LobbyError
from utils.decorators import ack, deps, guard, reply, respond
from utils.helpers import clean_name

log = logging.getLogger(__name__)
BOT_NAMES = ["Marco", "Giulia", "Luca", "Sofia", "Enzo", "Elena", "Dante", "Aria"]


async def _search(update, context, mode: int):
    c, uid = deps(context), update.effective_user.id
    if c.maintenance:
        return await reply(update, "🔧 The bot is in maintenance — new games are paused.")
    name = clean_name(update.effective_user.full_name)
    try:
        matched = c.lobby.queue_add(uid, name, mode)
    except LobbyError as e:
        return await reply(update, str(e))
    if matched is None:
        text = (f"⚡ <b>QUICK MATCH</b>\n🔎 Searching for {'an opponent' if mode == 2 else 'players'}... "
                f"({c.lobby.queue_size(mode)}/{mode})\nYou'll get your cards here the moment a table is full.")
        if update.callback_query:
            await respond(update, context, text, quick_kb())
            msg = update.callback_query.message
            c.search_msgs[uid] = (msg.chat_id, msg.message_id)
        else:
            m = await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=quick_kb())
            c.search_msgs[uid] = (m.chat_id, m.message_id)
        return
    for u, _n in matched:                         # clean up "searching" messages
        ref = c.search_msgs.pop(u, None)
        if ref:
            await c.notifier.delete(*ref)
    unreachable = [u for u, _n in matched if not await c.notifier.can_dm(u)]
    if unreachable:
        for u, n in matched:
            c.lobby.queue_remove(u)
            if u not in unreachable:
                await c.notifier.dm(u, "😕 A player could not be reached. Please search again.")
        return
    try:
        await c.games.start_game([PlayerInfo(u, n) for u, n in matched], kind="quick")
    except Exception:
        log.exception("quick match start failed")
        for u, _n in matched:
            c.lobby.set_playing([u], False)
            await c.notifier.dm(u, "⚠️ Could not start the match. Please try again.")


@guard(private=True)
async def quickmatch_cmd(update, context):
    await respond(update, context, "⚡ <b>QUICK MATCH</b>\nChoose the mode:", mode_kb("q"))


@guard(private=True)
async def quick_cb(update, context):
    await ack(update)
    arg = update.callback_query.data.split(":")[1]
    if arg == "cancel":
        c, uid = deps(context), update.effective_user.id
        c.lobby.queue_remove(uid)
        c.search_msgs.pop(uid, None)
        return await respond(update, context, "✅ Search cancelled.", None)
    await _search(update, context, int(arg))


@guard(private=True)
async def pick_quick_cb(update, context):
    await ack(update)
    await respond(update, context, "⚡ <b>QUICK MATCH</b>\nChoose the mode:", mode_kb("q"))


@guard(private=True)
async def pick_ai_cb(update, context):
    await ack(update)
    await respond(update, context, "🤖 <b>PRACTICE vs AI</b>\nChoose difficulty:\n<i>Practice pays 40% XP and doesn't count for rankings.</i>",
                  ai_level_kb())


@guard(private=True)
async def ai_cb(update, context):
    await ack(update)
    c, uid = deps(context), update.effective_user.id
    parts = update.callback_query.data.split(":")
    if parts[1] == "lvl":
        return await respond(update, context, f"🤖 Difficulty: <b>{parts[2].title()}</b>\nChoose the mode:", ai_mode_kb(parts[2]))
    level, mode = parts[2], int(parts[3])
    if c.maintenance:
        return await reply(update, "🔧 The bot is in maintenance — new games are paused.")
    reason = c.lobby.busy_reason(uid)
    if reason:
        return await reply(update, reason)
    me = clean_name(update.effective_user.full_name)
    names = random.sample(BOT_NAMES, 3)
    if mode == 2:
        players = [PlayerInfo(uid, me), PlayerInfo(-2, f"🤖 {names[0]}", level)]
    else:                                         # you + AI partner (seat 3) vs two AI
        players = [PlayerInfo(uid, me), PlayerInfo(-2, f"🤖 {names[0]}", level),
                   PlayerInfo(-3, f"🤖 {names[1]} (partner)", level), PlayerInfo(-4, f"🤖 {names[2]}", level)]
    await respond(update, context, f"🤖 Practice match vs <b>{level.title()}</b> AI — dealing your cards...", None)
    await c.games.start_game(players, kind="practice")


def register(app) -> None:
    app.add_handler(CommandHandler("quickmatch", quickmatch_cmd))
    app.add_handler(CallbackQueryHandler(pick_quick_cb, pattern=r"^p:quick$"))
    app.add_handler(CallbackQueryHandler(quick_cb, pattern=r"^q:"))
    app.add_handler(CallbackQueryHandler(pick_ai_cb, pattern=r"^p:ai$"))
    app.add_handler(CallbackQueryHandler(ai_cb, pattern=r"^a:"))
