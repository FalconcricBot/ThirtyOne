"""Friends, invites, search, recent opponents, blocking + the private-chat text router."""
from __future__ import annotations

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.constants import ChatType
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from config import settings
from keyboards.misc_keyboard import blocked_kb, friends_kb, person_kb
from services.statistics import level_for, rank_for
from utils.decorators import ack, deps, guard, reply, respond
from utils.helpers import esc
from utils.validators import parse_room_code


def invite_link(uid: int) -> str:
    return f"https://t.me/{settings.bot_username}?start=ref_{uid}"


async def send_friend_request(context, from_id: int, to_id: int, reply_to: Update | None = None) -> str:
    c = deps(context)
    if not await c.repo.get_player(to_id):
        return "missing"
    res = await c.repo.friend_request(from_id, to_id)
    me = esc(await c.repo.display_name(from_id))
    if res == "sent":
        kb = M([[B("✅ Accept", callback_data=f"f:accept:{from_id}"), B("✖ Decline", callback_data=f"f:remove:{from_id}")]])
        await c.notifier.dm(to_id, f"👥 <b>{me}</b> sent you a friend request.", kb)
    elif res == "accepted":
        await c.notifier.dm(to_id, f"🎉 You and <b>{me}</b> are now friends!")
    msgs = {"sent": "📨 Friend request sent.", "accepted": "🎉 You are now friends!", "already": "Already friends or request pending.",
            "blocked": "You cannot add this player.", "self": "That's you!", "missing": "Player not found."}
    if reply_to is not None and reply_to.effective_message:
        await reply_to.effective_message.reply_text(msgs[res])
    return res


async def _menu(update, context):
    c, uid = deps(context), update.effective_user.id
    friends, pending = await c.repo.friends(uid), await c.repo.pending_requests(uid)
    text = (f"👥 <b>FRIENDS</b> ({len(friends)})\n" + ("\n📨 Requests waiting for you are at the top.\n" if pending else "") +
            f"\n🔗 Your invite link:\n{invite_link(uid)}\n<i>Friends who open it send you a request.</i>")
    await respond(update, context, text, friends_kb(friends, pending))


@guard()
async def invite_cmd(update, context):
    await _menu(update, context)


async def _person(update, context, other: int):
    c, uid = deps(context), update.effective_user.id
    p = await c.repo.get_player(other)
    if not p:
        return await reply(update, "Player not found.")
    friend_ids = {f["id"] for f in await c.repo.friends(uid)}
    rel = "self" if other == uid else ("friend" if other in friend_ids else "none")
    emoji, rank, *_ = rank_for(p["xp"])
    pct = p["wins"] * 100 // p["matches"] if p["matches"] else 0
    text = (f"👤 <b>{esc(p['display_name'])}</b>" + (f" (@{esc(p['username'])})" if p["username"] else "") +
            f"\n{emoji} {rank} • Lv {level_for(p['xp'])}\n🎮 {p['matches']} matches • ✅ {p['wins']} • {pct}% win rate")
    await respond(update, context, text, person_kb(other, rel) if rel != "self" else None)


@guard()
async def friends_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c, uid = deps(context), update.effective_user.id
    parts = update.callback_query.data.split(":")
    act = parts[1]
    other = int(parts[2]) if len(parts) > 2 else None
    if act == "menu":
        await ack(update)
        context.user_data.pop("await", None)
        return await _menu(update, context)
    if act == "link":
        await ack(update)
        return await context.bot.send_message(update.effective_chat.id, f"🔗 Your invite link:\n{invite_link(uid)}")
    if act == "search":
        await ack(update)
        context.user_data["await"] = "search"
        return await context.bot.send_message(update.effective_chat.id, "🔎 Send a @username or name to search.")
    if act == "recent":
        await ack(update)
        rows = await c.repo.recent_opponents(uid)
        kb = M([[B(f"👤 {r['name'][:22]}", callback_data=f"f:view:{r['id']}")] for r in rows] + [[B("⬅ Friends", callback_data="f:menu")]])
        return await respond(update, context, "🕘 <b>RECENT OPPONENTS</b>" + ("" if rows else "\nNo opponents yet."), kb)
    if act == "blocked":
        await ack(update)
        bl = await c.repo.blocked_list(uid)
        return await respond(update, context, "🚫 <b>BLOCKED PLAYERS</b>" + ("" if bl else "\nNobody blocked."), blocked_kb(bl))
    if other is None:
        return await ack(update)
    if act == "view":
        await ack(update)
        return await _person(update, context, other)
    if act == "add":
        res = await send_friend_request(context, uid, other)
        await ack(update, {"sent": "📨 Request sent.", "accepted": "🎉 You are now friends!"}.get(res, "Not possible."), True)
    elif act == "accept":
        ok = await c.repo.friend_accept(uid, other)
        await ack(update, "🎉 Friend added!" if ok else "Request not found.", True)
        if ok:
            await c.notifier.dm(other, f"🎉 <b>{esc(await c.repo.display_name(uid))}</b> accepted your friend request!")
    elif act == "remove":
        await c.repo.friend_remove(uid, other)
        await ack(update, "Removed.")
    elif act == "block":
        await c.repo.block(uid, other)
        await ack(update, "Player blocked.", True)
    elif act == "unblock":
        await c.repo.unblock(uid, other)
        await ack(update, "Unblocked.")
        return await respond(update, context, "🚫 <b>BLOCKED PLAYERS</b>", blocked_kb(await c.repo.blocked_list(uid)))
    await _menu(update, context)


@guard(private=True)
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("await")
    if not mode or not update.message or not update.message.text:
        return
    c, text = deps(context), update.message.text.strip()
    if mode == "join":
        code = parse_room_code(text)
        if not code:
            return await reply(update, "That doesn't look like a room code. Example: BA-82941 (or /cancel)")
        context.user_data.pop("await", None)
        from handlers.room import join_room_flow
        return await join_room_flow(update, context, code)
    if mode == "search":
        context.user_data.pop("await", None)
        found = [u for u in await c.repo.find_users(text) if u["id"] != update.effective_user.id]
        if not found:
            return await reply(update, "No players found.")
        kb = M([[B(f"👤 {u['name'][:22]}" + (f" @{u['username']}" if u["username"] else ""), callback_data=f"f:view:{u['id']}")]
                for u in found] + [[B("⬅ Friends", callback_data="f:menu")]])
        await update.message.reply_text("🔎 Results:", reply_markup=kb)


def register(app) -> None:
    app.add_handler(CommandHandler("invite", invite_cmd))
    app.add_handler(CallbackQueryHandler(friends_cb, pattern=r"^f:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, text_router))
