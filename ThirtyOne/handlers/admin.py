"""Telegram admin dashboard. Every handler is gated by guard(admin=True) = ID check against ADMIN_IDS."""
from __future__ import annotations

import time

from telegram.ext import CallbackQueryHandler, CommandHandler

from keyboards.admin_keyboard import admin_kb
from utils.decorators import ack, deps, guard, reply, respond
from utils.helpers import DIV, esc
from utils.logger import error_count, tail_log
from utils.validators import parse_tournament_args

STARTED = time.time()


async def _stats_text(c) -> str:
    n = await c.repo.counts()
    return ("📊 <b>ADMIN STATS</b>\n" + DIV +
            f"\n👥 Registered users: <b>{n['users']}</b>\n🟢 Active (24h / DAU): <b>{n['active_24h']}</b>"
            f"\n🆕 New (24h): <b>{n['new_24h']}</b>\n🎮 Active matches: <b>{n['games_active']}</b> "
            f"(in memory: {len(c.games.sessions)})\n✅ Completed matches: <b>{n['games_done']}</b>"
            f"\n🏟 Tournaments: <b>{n['tournaments']}</b>\n🚫 Banned: <b>{n['banned']}</b>"
            f"\n⚠️ Errors (24h): <b>{error_count(time.time() - 86400)}</b>\n🔧 Maintenance: <b>{'ON' if c.maintenance else 'off'}</b>"
            f"\n⏱ Uptime: {int((time.time() - STARTED) // 3600)}h")


async def _resolve(c, token: str) -> int | None:
    if token.lstrip("-").isdigit():
        return int(token)
    found = await c.repo.find_users(token, 1)
    return found[0]["id"] if found else None


@guard(admin=True)
async def admin_cmd(update, context):
    c = deps(context)
    await respond(update, context, "🛠 <b>ADMIN PANEL</b>\n" + DIV +
                  "\n/stats • /playerinfo &lt;id|@user&gt; • /ban &lt;id&gt; [reason] • /unban &lt;id&gt;"
                  "\n/announcement &lt;text|off&gt; • /maintenance &lt;on|off&gt; • /broadcast &lt;text&gt;"
                  "\n/create_tournament Name | capacity | start_min | deadline_min | description"
                  "\n/end_tournament &lt;id&gt; • /remove_player &lt;tournament_id&gt; &lt;user&gt; • /logs"
                  "\n🔥 31 game: /t31config • /t31set &lt;key&gt; &lt;value&gt; • /create_tournament31", admin_kb(c.maintenance))


@guard(admin=True)
async def stats_cmd(update, context):
    c = deps(context)
    await respond(update, context, await _stats_text(c), admin_kb(c.maintenance))


@guard(admin=True)
async def playerinfo_cmd(update, context):
    c = deps(context)
    uid = await _resolve(c, context.args[0]) if context.args else None
    p = await c.repo.get_player(uid) if uid else None
    if not p:
        return await reply(update, "Usage: /playerinfo <id|@username> (player not found)")
    banned = await c.repo.is_banned(uid)
    await reply(update, f"👤 <b>{esc(p['display_name'])}</b> (<code>{p['id']}</code>) @{esc(p['username'] or '-')}\n"
                        f"#{p['player_no']} • XP {p['xp']} • 💰 {p['coins']}\nMatches {p['matches']} • W {p['wins']} L {p['losses']} D {p['draws']}\n"
                        f"Joined {p['created_at']:%Y-%m-%d} • {'🚫 BANNED' if banned else 'active'}", parse_mode="HTML")


@guard(admin=True)
async def ban_cmd(update, context):
    c = deps(context)
    uid = await _resolve(c, context.args[0]) if context.args else None
    if not uid:
        return await reply(update, "Usage: /ban <id|@username> [reason]")
    if uid in __import__("config").settings.admin_ids:
        return await reply(update, "You cannot ban an admin.")
    reason = " ".join(context.args[1:]) or "no reason"
    await c.repo.ban(uid, reason, update.effective_user.id)
    await c.repo.log_admin(update.effective_user.id, "ban", f"{uid}: {reason}")
    await c.games.forfeit(uid)
    await c.games31.forfeit(uid)
    c.lobby.queue_remove(uid)
    if uid in c.lobby.user_room:
        c.lobby.leave_room(uid)
    await reply(update, f"🚫 Banned {uid}.")


@guard(admin=True)
async def unban_cmd(update, context):
    c = deps(context)
    uid = await _resolve(c, context.args[0]) if context.args else None
    ok = await c.repo.unban(uid) if uid else False
    if ok:
        await c.repo.log_admin(update.effective_user.id, "unban", str(uid))
    await reply(update, f"✅ Unbanned {uid}." if ok else "User is not banned (usage: /unban <id|@username>).")


@guard(admin=True)
async def announcement_cmd(update, context):
    c = deps(context)
    text = " ".join(context.args).strip()
    if not text:
        return await reply(update, "Usage: /announcement <text>  or  /announcement off")
    c.announcement = "" if text.lower() == "off" else text[:200]
    await c.repo.set_setting("announcement", c.announcement)
    await c.repo.log_admin(update.effective_user.id, "announcement", c.announcement or "off")
    await reply(update, "📢 Announcement " + ("cleared." if not c.announcement else "set — shown in the main menu."))


@guard(admin=True)
async def maintenance_cmd(update, context):
    c = deps(context)
    arg = (context.args[0].lower() if context.args else "")
    if arg not in ("on", "off"):
        return await reply(update, f"Maintenance is {'ON' if c.maintenance else 'off'}. Use /maintenance on|off")
    c.maintenance = arg == "on"
    await c.repo.set_setting("maintenance", "1" if c.maintenance else "0")
    await c.repo.log_admin(update.effective_user.id, "maintenance", arg)
    await reply(update, f"🔧 Maintenance {'ON — new games blocked, running games continue' if c.maintenance else 'OFF'}.")


@guard(admin=True)
async def broadcast_cmd(update, context):
    c = deps(context)
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        return await reply(update, "Usage: /broadcast <text>")
    ids = await c.repo.all_user_ids()
    await reply(update, f"📣 Sending to {len(ids)} users...")
    ok, fail = await c.notifier.broadcast(ids, f"📣 <b>Thirty One</b>\n\n{esc(text)}")
    await c.repo.log_admin(update.effective_user.id, "broadcast", f"{ok} ok / {fail} failed: {text[:150]}")
    await reply(update, f"✅ Delivered {ok}, failed {fail}.")


@guard(admin=True)
async def create_tournament_cmd(update, context):
    c = deps(context)
    raw = update.effective_message.text.partition(" ")[2]
    try:
        args = parse_tournament_args(raw)
    except ValueError as e:
        return await reply(update, f"❌ {e}")
    tid = await c.tournaments.create(update.effective_user.id, **args)
    await reply(update, f"🏟 Tournament #{tid} created. Players register in /tournaments. It starts automatically in {args['start_min']} min.")


@guard(admin=True)
async def end_tournament_cmd(update, context):
    c = deps(context)
    if not context.args or not context.args[0].isdigit():
        return await reply(update, "Usage: /end_tournament <id>")
    await reply(update, await c.tournaments.cancel(int(context.args[0]), update.effective_user.id))


@guard(admin=True)
async def remove_player_cmd(update, context):
    c = deps(context)
    if len(context.args) < 2 or not context.args[0].isdigit():
        return await reply(update, "Usage: /remove_player <tournament_id> <user id|@username>")
    uid = await _resolve(c, context.args[1])
    if not uid:
        return await reply(update, "Player not found.")
    await reply(update, await c.tournaments.remove_player(int(context.args[0]), uid, update.effective_user.id))


@guard(admin=True)
async def logs_cmd(update, context):
    c = deps(context)
    rows = await c.repo.admin_logs(10)
    admin = "\n".join(f"{r['at']:%m-%d %H:%M} • {r['admin_id']} • {r['action']} • {esc(r['details'])[:60]}" for r in rows) or "—"
    tail = esc(tail_log(15))[-1800:]
    await context.bot.send_message(update.effective_chat.id,
                                   f"📜 <b>ADMIN LOG</b>\n{admin}\n\n<b>BOT LOG (tail)</b>\n<pre>{tail}</pre>", parse_mode="HTML")


@guard(admin=True)
async def admin_cb(update, context):
    c = deps(context)
    act = update.callback_query.data.split(":")[1]
    await ack(update)
    if act == "stats":
        await respond(update, context, await _stats_text(c), admin_kb(c.maintenance))
    elif act == "logs":
        await logs_cmd(update, context)
    elif act == "maint":
        c.maintenance = not c.maintenance
        await c.repo.set_setting("maintenance", "1" if c.maintenance else "0")
        await c.repo.log_admin(update.effective_user.id, "maintenance", "on" if c.maintenance else "off")
        await respond(update, context, await _stats_text(c), admin_kb(c.maintenance))


def register(app) -> None:
    for name, fn in [("admin", admin_cmd), ("stats", stats_cmd), ("playerinfo", playerinfo_cmd), ("ban", ban_cmd),
                     ("unban", unban_cmd), ("announcement", announcement_cmd), ("maintenance", maintenance_cmd),
                     ("broadcast", broadcast_cmd), ("create_tournament", create_tournament_cmd),
                     ("end_tournament", end_tournament_cmd), ("remove_player", remove_player_cmd), ("logs", logs_cmd)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern=r"^ad:"))
