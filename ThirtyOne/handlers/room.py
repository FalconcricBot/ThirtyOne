"""Private rooms: create / join (button, code, deep link) / fill with AI / start / leave."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from config import settings
from keyboards.main_menu import home_kb
from keyboards.room_keyboard import mode_kb, room_kb
from services.game_manager import PlayerInfo
from services.matchmaking import LobbyError
from ui import texts
from utils.decorators import ack, deps, guard, reply, respond
from utils.helpers import clean_name, esc
from utils.validators import parse_room_code

log = logging.getLogger(__name__)


def _name(update: Update) -> str:
    return clean_name(update.effective_user.full_name)


async def refresh_card(bot, room, text: str | None = None, kb="auto") -> None:
    """Update the room card wherever it lives (private chat or group)."""
    if room.message_id is None:
        return
    try:
        await bot.edit_message_text(text or texts.room_text(room), chat_id=room.chat_id, message_id=room.message_id,
                                    parse_mode=ParseMode.HTML, reply_markup=room_kb(room) if kb == "auto" else kb)
    except TelegramError as e:
        if "not modified" not in str(e).lower():
            log.info("room card refresh failed: %s", e)


async def post_card(context, chat_id: int, room) -> None:
    m = await context.bot.send_message(chat_id, texts.room_text(room), parse_mode=ParseMode.HTML, reply_markup=room_kb(room))
    room.message_id, room.chat_id = m.message_id, chat_id


async def create_room(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: int) -> None:
    c = deps(context)
    if c.maintenance:
        return await reply(update, "🔧 The bot is in maintenance — new games are paused.")
    room = c.lobby.create_room(update.effective_user.id, _name(update), mode, update.effective_chat.id)
    q = update.callback_query
    if q and q.message and update.effective_chat.type == ChatType.PRIVATE:
        room.message_id = q.message.message_id
        await respond(update, context, texts.room_text(room), room_kb(room))
    else:
        await post_card(context, update.effective_chat.id, room)


@guard()
async def createroom_cmd(update, context):
    try:
        mode = int(context.args[0]) if context.args else 0
    except ValueError:
        mode = 0
    if mode in (2, 4):
        try:
            await create_room(update, context, mode)
        except LobbyError as e:
            await reply(update, str(e))
    else:
        await respond(update, context, "👥 <b>Create a private room</b>\nChoose the mode:", mode_kb("r:new"))


async def join_room_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    if code.startswith("31-"):                       # 31 Card Game rooms
        from handlers.thirty_one import join_room31
        return await join_room31(update, context, code)
    c = deps(context)
    if await c.repo.is_banned(update.effective_user.id):
        return
    try:
        room = c.lobby.rooms.get(code)
        if room and await c.repo.is_blocked(update.effective_user.id, room.owner_id):
            raise LobbyError("You cannot join this room.")
        room = c.lobby.join_room(code, update.effective_user.id, _name(update))
    except LobbyError as e:
        return await reply(update, f"❌ {e}")
    await refresh_card(context.bot, room)
    if update.effective_chat.type == ChatType.PRIVATE and room.chat_id != update.effective_chat.id:
        await context.bot.send_message(update.effective_chat.id, f"✅ You joined room <code>{code}</code>. "
                                       "The owner will start the game — your cards will arrive here.", parse_mode=ParseMode.HTML)
    elif update.callback_query is None:
        await reply(update, f"✅ Joined room {code}.")
    for uid, _n in room.players:
        if uid != update.effective_user.id and uid > 0:
            await c.notifier.dm(uid, f"🙋 <b>{esc(_name(update))}</b> joined room <code>{code}</code> "
                                     f"({len(room.players)}/{room.mode})", silent=True)


@guard()
async def joinroom_cmd(update, context):
    code = parse_room_code(context.args[0]) if context.args else None
    if code:
        return await join_room_flow(update, context, code)
    context.user_data["await"] = "join"
    await reply(update, "🔑 Send the room code (example: BA-82941).")


async def start_room(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    c, uid = deps(context), update.effective_user.id
    if c.maintenance:
        return await ack(update, "🔧 Maintenance mode — new games are paused.", True)
    try:
        room = c.lobby.begin_start(code, uid)
    except LobbyError as e:
        return await ack(update, str(e), True)
    try:
        if not room.full:
            c.lobby.abort_start(code)
            return await ack(update, "Room isn't full yet — wait for players or tap 🤖 Fill with AI.", True)
        humans = [(u, n) for u, n in room.players if u > 0]
        blocked = [n for u, n in humans if not await c.notifier.can_dm(u)]
        if blocked:
            c.lobby.abort_start(code)
            link = f"https://t.me/{settings.bot_username}?start=hello"
            await context.bot.send_message(
                room.chat_id, "⚠️ <b>Private card delivery needed</b>\n" + ", ".join(esc(n) for n in blocked) +
                " must start the bot first (cards are sent privately so nobody sees your hand).",
                parse_mode=ParseMode.HTML, reply_markup=M([[B("▶ Start Bot", url=link)]]))
            return await ack(update)
        players = [PlayerInfo(u, n, "medium" if u < 0 else None) for u, n in room.players]
        in_group = room.chat_id < 0
        await ack(update, "🚀 Starting...")
        await c.games.start_game(players, kind="room", room_code=code, group_chat_id=room.chat_id if in_group else None)
        c.lobby.finish_start(code)
        await refresh_card(context.bot, room, f"🚀 <b>Room {code}</b> — game started!"
                           + ("" if in_group else " Check your cards below."), kb=None)
    except Exception:
        log.exception("could not start room %s", code)
        c.lobby.abort_start(code)
        await reply(update, "⚠️ Could not start the game. Please try again.")


@guard()
async def room_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c, uid = deps(context), update.effective_user.id
    parts = update.callback_query.data.split(":")
    action = parts[1]
    if action == "new":
        await ack(update)
        try:
            await create_room(update, context, int(parts[2]))
        except LobbyError as e:
            await reply(update, str(e))
        return
    code = parts[2]
    if action == "start":
        return await start_room(update, context, code)
    if action == "join":
        await ack(update)
        return await join_room_flow(update, context, code)
    room = c.lobby.rooms.get(code)
    if room is None:
        await ack(update, "This room no longer exists.", True)
        return await respond(update, context, "This room was closed.", home_kb())
    try:
        if action == "ai":
            c.lobby.fill_ai(code, uid)
            await ack(update, "🤖 AI players added.")
        elif action == "refresh":
            await ack(update, "Refreshed")
        elif action == "leave":
            room, closed = c.lobby.leave_room(uid)
            await ack(update, "You left the room.")
            if closed:
                return await refresh_card(context.bot, room, f"❌ Room <code>{code}</code> closed.", kb=None)
        elif action == "cancel":
            if room.owner_id != uid:
                return await ack(update, "Only the owner can cancel the room.", True)
            c.lobby.close_room(code)
            await ack(update, "Room cancelled.")
            return await refresh_card(context.bot, room, f"❌ Room <code>{code}</code> was cancelled.", kb=None)
    except LobbyError as e:
        return await ack(update, str(e), True)
    await refresh_card(context.bot, room)


@guard()
async def pick_join_cb(update, context):
    await ack(update)
    context.user_data["await"] = "join"
    await context.bot.send_message(update.effective_chat.id, "🔑 Send the room code (example: <code>BA-82941</code>).",
                                   parse_mode=ParseMode.HTML)


@guard()
async def pick_room_cb(update, context):
    await ack(update)
    await respond(update, context, "👥 <b>Create a private room</b>\nChoose the mode:", mode_kb("r:new"))


@guard()
async def leave_cmd(update, context):
    c, uid = deps(context), update.effective_user.id
    if uid in c.games31.by_user:
        return await update.effective_message.reply_text("🏳 Leave the running 31 match? You will be eliminated.",
                                                         reply_markup=c.games31.ask_leave(uid))
    if uid in c.games.by_user:
        kb = c.games.ask_leave(uid)
        return await update.effective_message.reply_text("🏳 Leave the running match? You will forfeit.", reply_markup=kb)
    if c.games.stop_watching(uid):
        return await reply(update, "👀 You stopped watching.")
    if uid in c.lobby.user_room:
        room, closed = c.lobby.leave_room(uid)
        await reply(update, "✅ You left the room.")
        if room.game == "thirty_one":
            from handlers.thirty_one import refresh_card as refresh31
            cfg = await c.games31.config()
            await refresh31(context.bot, room, cfg, f"❌ Room <code>{room.code}</code> closed." if closed else None,
                            kb=None if closed else "auto")
        elif closed:
            await refresh_card(context.bot, room, f"❌ Room <code>{room.code}</code> closed.", kb=None)
        else:
            await refresh_card(context.bot, room)
        return
    if c.lobby.queue_remove(uid):
        return await reply(update, "✅ Search cancelled.")
    await reply(update, "You are not in a room, queue or match.")


@guard()
async def cancel_cmd(update, context):
    c, uid = deps(context), update.effective_user.id
    context.user_data.pop("await", None)
    did = False
    if c.lobby.queue_remove(uid):
        did = True
    if uid in c.lobby.user_room:
        room, closed = c.lobby.leave_room(uid)
        did = True
        if closed:
            await refresh_card(context.bot, room, f"❌ Room <code>{room.code}</code> closed.", kb=None)
        else:
            await refresh_card(context.bot, room)
    await reply(update, "✅ Cancelled." if did else "Nothing to cancel. (Use /leave to quit a running match.)")


def register(app) -> None:
    app.add_handler(CommandHandler("createroom", createroom_cmd))
    app.add_handler(CommandHandler("joinroom", joinroom_cmd))
    app.add_handler(CommandHandler("leave", leave_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(pick_room_cb, pattern=r"^p:room$"))
    app.add_handler(CallbackQueryHandler(pick_join_cb, pattern=r"^p:join$"))
    app.add_handler(CallbackQueryHandler(room_cb, pattern=r"^r:"))
