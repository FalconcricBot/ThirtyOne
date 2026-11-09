"""31 Card Game: menu, rooms, quick match, AI practice, in-game buttons, stats, leaderboards, admin config."""
from __future__ import annotations

import logging
import random

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from config import settings
from game.thirty_one.rules import DEFAULT_CONFIG, ThirtyOneConfig
from handlers.matchmaking import BOT_NAMES
from keyboards import thirty_one_keyboard as K
from services.game_manager import PlayerInfo
from services.matchmaking import LobbyError
from ui import thirty_one_texts as T
from utils.decorators import ack, deps, guard, reply, respond
from utils.helpers import clean_name, esc
from utils.validators import parse_tournament_args

log = logging.getLogger(__name__)
PER_PAGE = 10


def _name(update: Update) -> str:
    return clean_name(update.effective_user.full_name)


async def _private_or_dm(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, kb=None) -> None:
    """Informational screens: edit in private chat; from a group message send a DM instead (never touch the table)."""
    if update.effective_chat.type == ChatType.PRIVATE:
        return await respond(update, context, text, kb)
    ok = await deps(context).notifier.dm(update.effective_user.id, text, kb)
    await ack(update, "📩 Sent to your private chat." if ok else "Start the bot privately first: t.me/" + settings.bot_username, ok is None)


# ============================================================== menus
async def show_games_menu(update, context):
    from keyboards.thirty_one_keyboard import games_menu_kb
    await respond(update, context, T.games_menu_text(), games_menu_kb())


@guard()
async def games_cb(update, context):
    await ack(update)
    c = deps(context)
    arg = update.callback_query.data.split(":")[1]
    context.user_data.pop("await", None)
    if arg == "briscola":
        from keyboards.main_menu import play_menu_kb
        return await respond(update, context, "🎮 <b>SELECT GAME MODE</b>", play_menu_kb())
    stats = await c.repo.t31_get_stats(update.effective_user.id)
    await respond(update, context, T.menu_text(stats), K.menu_kb())


@guard()
async def thirtyone_cmd(update, context):
    stats = await deps(context).repo.t31_get_stats(update.effective_user.id)
    await respond(update, context, T.menu_text(stats), K.menu_kb())


@guard()
async def rules_cb(update, context):
    await ack(update)
    cfg = await deps(context).games31.config()
    await _private_or_dm(update, context, T.rules_text(cfg), K.back_kb())


@guard()
async def stats_cb(update, context):
    await ack(update)
    c = deps(context)
    await respond(update, context, T.stats_text(await c.repo.t31_get_stats(update.effective_user.id)), K.back_kb())


@guard()
async def history_cb(update, context):
    await ack(update)
    c, page = deps(context), int(update.callback_query.data.split(":")[2])
    rows, total = await c.repo.t31_history(update.effective_user.id, 6, page * 6)
    from keyboards.thirty_one_keyboard import history_kb
    await respond(update, context, T.history_text(rows, page, total, 6), history_kb(page, max(1, -(-total // 6))))


@guard()
async def leaderboard_cb(update, context):
    await ack(update)
    c, uid = deps(context), update.effective_user.id
    _, _, kind, page = update.callback_query.data.split(":")
    page = max(0, int(page))
    if kind not in T.LB_TITLES:
        return
    ids = ([f["id"] for f in await c.repo.friends(uid)] + [uid]) if kind == "friends" else None
    rows, total = await c.repo.t31_leaderboard(kind, PER_PAGE, page * PER_PAGE, ids)
    await _private_or_dm(update, context, T.lb_text(kind, rows, page, total, PER_PAGE, uid),
                         K.lb_kb(kind, page, max(1, -(-total // PER_PAGE))))


# ============================================================== rooms
async def refresh_card(bot, room, cfg, text: str | None = None, kb="auto") -> None:
    if room.message_id is None:
        return
    try:
        await bot.edit_message_text(text or T.room_text(room, cfg), chat_id=room.chat_id, message_id=room.message_id,
                                    parse_mode=ParseMode.HTML, reply_markup=K.room_kb(room) if kb == "auto" else kb)
    except TelegramError as e:
        if "not modified" not in str(e).lower():
            log.info("31 room card refresh failed: %s", e)


@guard()
async def room_pick_cb(update, context):
    """t31:room -> choose mode;  t31:rm:<mode> -> choose size;  t31:new:<mode>:<n> -> create."""
    await ack(update)
    c = deps(context)
    cfg = await c.games31.config()
    parts = update.callback_query.data.split(":")
    if parts[1] == "room":
        return await respond(update, context, "👥 <b>31 PRIVATE ROOM</b>\nChoose the game mode:", K.mode_pick_kb(cfg))
    if parts[1] == "rm":
        return await respond(update, context, f"👥 <b>{T.MODE_NAME[parts[2]]}</b>\nHow many players (max)?", K.size_kb(parts[2], cfg))
    if c.maintenance:
        return await reply(update, "🔧 The bot is in maintenance — new games are paused.")
    mode, n = parts[2], int(parts[3])
    if (mode == "points" and not cfg.points_mode_enabled) or (mode != "points" and not cfg.lives_mode_enabled) \
            or not cfg.min_players <= n <= cfg.max_players:
        return await reply(update, "That mode / size is disabled by the admins.")
    try:
        room = c.lobby.create_room(update.effective_user.id, _name(update), n, update.effective_chat.id,
                                   game="thirty_one", options={"mode": mode})
    except LobbyError as e:
        return await reply(update, str(e))
    q = update.callback_query
    if q and q.message and update.effective_chat.type == ChatType.PRIVATE and not q.message.photo:
        room.message_id = q.message.message_id
        await respond(update, context, T.room_text(room, cfg), K.room_kb(room))
    else:
        m = await context.bot.send_message(update.effective_chat.id, T.room_text(room, cfg), parse_mode=ParseMode.HTML,
                                           reply_markup=K.room_kb(room))
        room.message_id, room.chat_id = m.message_id, update.effective_chat.id


async def join_room31(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> None:
    c, uid = deps(context), update.effective_user.id
    if await c.repo.is_banned(uid):
        return
    cfg = await c.games31.config()
    try:
        room = c.lobby.rooms.get(code)
        if room is not None and room.game != "thirty_one":
            raise LobbyError("That room belongs to a different game.")
        if room and await c.repo.is_blocked(uid, room.owner_id):
            raise LobbyError("You cannot join this room.")
        room = c.lobby.join_room(code, uid, _name(update))
    except LobbyError as e:
        return await reply(update, f"❌ {e}")
    await refresh_card(context.bot, room, cfg)
    if update.effective_chat.type == ChatType.PRIVATE and room.chat_id != update.effective_chat.id:
        await context.bot.send_message(update.effective_chat.id, f"✅ You joined room <code>{code}</code>. The owner will "
                                       "start the game — your cards will arrive here.", parse_mode=ParseMode.HTML)
    for u, _n in room.players:
        if u != uid and u > 0:
            await c.notifier.dm(u, f"🙋 <b>{esc(_name(update))}</b> joined room <code>{code}</code> "
                                   f"({len(room.players)}/{room.mode})", silent=True)


async def _start_room(update, context, code: str) -> None:
    c, uid = deps(context), update.effective_user.id
    if c.maintenance:
        return await ack(update, "🔧 Maintenance mode — new games are paused.", True)
    cfg = await c.games31.config()
    try:
        room = c.lobby.begin_start(code, uid)
    except LobbyError as e:
        return await ack(update, str(e), True)
    try:
        if len(room.players) < cfg.min_players:
            c.lobby.abort_start(code)
            return await ack(update, f"Need at least {cfg.min_players} players — invite friends or tap 🤖 Add AI.", True)
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
        game_cfg = cfg.replace(mode=room.options.get("mode", "lives"))
        await ack(update, "🚀 Starting...")
        await c.games31.start_game(players, kind="room", cfg=game_cfg, room_code=code,
                                   group_chat_id=room.chat_id if room.chat_id < 0 else None)
        c.lobby.finish_start(code)
        await refresh_card(context.bot, room, cfg, f"🚀 <b>Room {code}</b> — game started!"
                           + ("" if room.chat_id < 0 else " Check your cards below."), kb=None)
    except Exception:
        log.exception("could not start 31 room %s", code)
        c.lobby.abort_start(code)
        await reply(update, "⚠️ Could not start the game. Please try again.")


@guard()
async def room_cb(update, context):
    c, uid = deps(context), update.effective_user.id
    _, _, action, code = update.callback_query.data.split(":")
    if action == "start":
        return await _start_room(update, context, code)
    if action == "join":
        await ack(update)
        return await join_room31(update, context, code)
    room = c.lobby.rooms.get(code)
    cfg = await c.games31.config()
    if room is None:
        await ack(update, "This room no longer exists.", True)
        return await respond(update, context, "This room was closed.", K.back_kb())
    try:
        if action == "ai":
            c.lobby.add_ai(code, uid)
            await ack(update, "🤖 AI player added.")
        elif action == "refresh":
            await ack(update, "Refreshed")
        elif action == "leave":
            room, closed = c.lobby.leave_room(uid)
            await ack(update, "You left the room.")
            if closed:
                return await refresh_card(context.bot, room, cfg, f"❌ Room <code>{code}</code> closed.", kb=None)
        elif action == "cancel":
            if room.owner_id != uid:
                return await ack(update, "Only the owner can cancel the room.", True)
            c.lobby.close_room(code)
            await ack(update, "Room cancelled.")
            return await refresh_card(context.bot, room, cfg, f"❌ Room <code>{code}</code> was cancelled.", kb=None)
    except LobbyError as e:
        return await ack(update, str(e), True)
    await refresh_card(context.bot, room, cfg)


@guard()
async def join_prompt_cb(update, context):
    await ack(update)
    context.user_data["await"] = "join"                 # the private-chat text router joins the room (BA- or 31- codes)
    await context.bot.send_message(update.effective_chat.id, "🔑 Send the room code (example: <code>31-82941</code>).",
                                   parse_mode=ParseMode.HTML)


# ============================================================== quick match + practice
@guard(private=True)
async def quick_cb(update, context):
    await ack(update)
    c, uid = deps(context), update.effective_user.id
    cfg = await c.games31.config()
    arg = update.callback_query.data.split(":")[2] if update.callback_query.data.count(":") >= 2 else ""
    if update.callback_query.data == "t31:quick":
        return await respond(update, context, "⚡ <b>31 QUICK MATCH</b>\nHow many players?", K.quick_pick_kb(cfg))
    if arg == "cancel":
        c.lobby.queue_remove(uid)
        c.search_msgs.pop(uid, None)
        return await respond(update, context, "✅ Search cancelled.", K.back_kb())
    if c.maintenance:
        return await reply(update, "🔧 The bot is in maintenance — new games are paused.")
    n = int(arg)
    try:
        matched = c.lobby.queue_add(uid, _name(update), 100 + n, size=n)
    except LobbyError as e:
        return await reply(update, str(e))
    if matched is None:
        await respond(update, context, f"⚡ <b>31 QUICK MATCH</b>\n🔎 Searching… ({c.lobby.queue_size(100 + n)}/{n})\n"
                                       "You'll get your cards here the moment a table is full.", K.quick_cancel_kb())
        msg = update.callback_query.message
        c.search_msgs[uid] = (msg.chat_id, msg.message_id)
        return
    for u, _n in matched:
        ref = c.search_msgs.pop(u, None)
        if ref:
            await c.notifier.delete(*ref)
    if any([not await c.notifier.can_dm(u) for u, _n in matched]):
        for u, _n in matched:
            c.lobby.queue_remove(u)
            await c.notifier.dm(u, "😕 A player could not be reached. Please search again.")
        return
    try:
        await c.games31.start_game([PlayerInfo(u, nm) for u, nm in matched], kind="quick", cfg=cfg.replace(mode="lives"))
    except Exception:
        log.exception("31 quick match failed to start")
        for u, _n in matched:
            c.lobby.set_playing([u], False)
            await c.notifier.dm(u, "⚠️ Could not start the match. Please try again.")


@guard(private=True)
async def ai_cb(update, context):
    await ack(update)
    c, uid = deps(context), update.effective_user.id
    parts = update.callback_query.data.split(":")
    if len(parts) == 2:
        return await respond(update, context, "🤖 <b>31 PRACTICE vs AI</b>\nChoose difficulty:\n<i>Practice pays 40% XP and "
                                              "doesn't count for rankings.</i>", K.ai_level_kb())
    if parts[2] == "lvl":
        return await respond(update, context, f"🤖 Difficulty: <b>{parts[3].title()}</b>\nHow many AI opponents?", K.ai_opp_kb(parts[3]))
    level, k = parts[3], int(parts[4])
    if c.maintenance:
        return await reply(update, "🔧 The bot is in maintenance — new games are paused.")
    if (reason := c.lobby.busy_reason(uid)):
        return await reply(update, reason)
    cfg = (await c.games31.config()).replace(mode="lives")
    names = random.sample(BOT_NAMES, k)
    players = [PlayerInfo(uid, _name(update))] + [PlayerInfo(-(i + 2), f"🤖 {names[i]}", level) for i in range(k)]
    await respond(update, context, f"🤖 Practice vs <b>{level.title()}</b> AI — dealing your cards...", None)
    await c.games31.start_game(players, kind="practice", cfg=cfg)


# ============================================================== in-game buttons
@guard()
async def action_cb(update, context):
    parts = update.callback_query.data.split(":")        # t31:a:<gid>:<ver>:<code>[:<card>]
    gid, ver, code = int(parts[2]), int(parts[3]), parts[4]
    arg = parts[5] if len(parts) > 5 else None
    alert = await deps(context).games31.handle_action(update.effective_user.id, gid, ver, code, arg)
    await ack(update, alert, alert is not None)


@guard()
async def score_cb(update, context):
    await ack(update, deps(context).games31.score_text(update.effective_user.id) or "No running match.", True)


@guard()
async def leave_cb(update, context):
    c, uid = deps(context), update.effective_user.id
    parts = update.callback_query.data.split(":")
    if parts[2] == "no":
        await ack(update, "Good luck!")
        return await update.callback_query.message.delete()
    if parts[2] == "yes":
        await ack(update)
        ok = await c.games31.forfeit(uid)
        return await respond(update, context, "🏳 You left the match." if ok else "That match is already over.", None)
    await ack(update)
    kb = c.games31.ask_leave(uid)
    if kb:
        await context.bot.send_message(update.effective_chat.id, "🏳 Leave the running match? You will be eliminated.", reply_markup=kb)


@guard()
async def rematch_cb(update, context):
    msg = await deps(context).games31.rematch_vote(update.effective_user.id, int(update.callback_query.data.split(":")[2]))
    await ack(update, msg, True)


# ============================================================== admin
def _panel_cfg(saved: dict) -> dict:
    try:
        return ThirtyOneConfig.from_dict(saved).to_dict()
    except ValueError:
        return DEFAULT_CONFIG.to_dict()


@guard(admin=True)
async def config_cmd(update, context):
    c = deps(context)
    cfg = _panel_cfg(await c.repo.t31_get_config())
    await context.bot.send_message(update.effective_chat.id, T.config_text(cfg), parse_mode=ParseMode.HTML,
                                   reply_markup=K.config_kb(cfg))


@guard(admin=True)
async def config_cb(update, context):
    c = deps(context)
    key = update.callback_query.data.split(":")[1]
    saved = _panel_cfg(await c.repo.t31_get_config())
    if key == "reset":
        new = DEFAULT_CONFIG.to_dict()
    elif key in K.CONFIG_CHOICES:
        new = K.next_config_value(saved, key)
    else:
        return await ack(update)
    try:
        ThirtyOneConfig.from_dict(new)
    except ValueError as e:
        return await ack(update, f"Invalid: {e}", True)
    await c.repo.t31_set_config(new)
    await c.repo.log_admin(update.effective_user.id, "t31config", f"{key} -> {new.get(key, 'reset')}")
    await ack(update, "Saved ✅ (applies to new games)")
    await respond(update, context, T.config_text(new), K.config_kb(new))


def _coerce(raw: str):
    low = raw.lower()
    if low in ("on", "true", "yes"):
        return True
    if low in ("off", "false", "no"):
        return False
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


@guard(admin=True)
async def set_cmd(update, context):
    c = deps(context)
    if len(context.args) != 2 or context.args[0] not in DEFAULT_CONFIG.to_dict():
        return await reply(update, "Usage: /t31set <key> <value>\nKeys: " + ", ".join(DEFAULT_CONFIG.to_dict()))
    key, val = context.args[0], _coerce(context.args[1])
    new = {**_panel_cfg(await c.repo.t31_get_config()), key: val}
    try:
        ThirtyOneConfig.from_dict(new)
    except (ValueError, TypeError) as e:
        return await reply(update, f"❌ Invalid value: {e}")
    await c.repo.t31_set_config(new)
    await c.repo.log_admin(update.effective_user.id, "t31set", f"{key}={val}")
    await reply(update, f"✅ {key} = {val} (applies to new games)")


@guard(admin=True)
async def create_tournament_cmd(update, context):
    c = deps(context)
    try:
        args = parse_tournament_args(update.effective_message.text.partition(" ")[2])
    except ValueError as e:
        return await reply(update, f"❌ {str(e).replace('/create_tournament', '/create_tournament31')}")
    tid = await c.tournaments.create(update.effective_user.id, game="thirty_one", **args)
    await reply(update, f"🔥 31 tournament #{tid} created. Players register in /tournaments. It starts automatically "
                        f"in {args['start_min']} min (1v1 lives matches, knockout bracket).")


def register(app) -> None:
    app.add_handler(CommandHandler("thirtyone", thirtyone_cmd))
    app.add_handler(CommandHandler("t31config", config_cmd))
    app.add_handler(CommandHandler("t31set", set_cmd))
    app.add_handler(CommandHandler("create_tournament31", create_tournament_cmd))
    app.add_handler(CallbackQueryHandler(games_cb, pattern=r"^cg:"))
    app.add_handler(CallbackQueryHandler(rules_cb, pattern=r"^t31:rules$"))
    app.add_handler(CallbackQueryHandler(stats_cb, pattern=r"^t31:stats$"))
    app.add_handler(CallbackQueryHandler(history_cb, pattern=r"^t31:hist:\d+$"))
    app.add_handler(CallbackQueryHandler(leaderboard_cb, pattern=r"^t31:lb:[a-z]+:\d+$"))
    app.add_handler(CallbackQueryHandler(room_pick_cb, pattern=r"^t31:(room|rm:[a-z]+|new:[a-z]+:\d)$"))
    app.add_handler(CallbackQueryHandler(room_cb, pattern=r"^t31:r:[a-z]+:31-\d{5}$"))
    app.add_handler(CallbackQueryHandler(join_prompt_cb, pattern=r"^t31:join$"))
    app.add_handler(CallbackQueryHandler(quick_cb, pattern=r"^t31:(quick|q:(\d|cancel))$"))
    app.add_handler(CallbackQueryHandler(ai_cb, pattern=r"^t31:ai(:.*)?$"))
    app.add_handler(CallbackQueryHandler(action_cb, pattern=r"^t31:a:\d+:\d+:(dr|tk|kn|d31|ds:(10|[A2-9JQK])[HDCS]|ds)$"))
    app.add_handler(CallbackQueryHandler(score_cb, pattern=r"^t31:sc:\d+$"))
    app.add_handler(CallbackQueryHandler(leave_cb, pattern=r"^t31:lv:"))
    app.add_handler(CallbackQueryHandler(rematch_cb, pattern=r"^t31:rm2:\d+$"))
    app.add_handler(CallbackQueryHandler(config_cb, pattern=r"^t31c:"))
