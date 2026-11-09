from telegram.ext import CallbackQueryHandler, CommandHandler

from config import settings
from keyboards.misc_keyboard import tournament_kb, tournament_list_kb
from ui import texts
from utils.decorators import ack, deps, guard, respond


async def _list(update, context):
    c = deps(context)
    items = await c.repo.list_tournaments(["registration", "running"], 10)
    text = "🏟 <b>TOURNAMENTS</b>\n" + ("Pick one:" if items else "No active tournaments. Check back soon!")
    await respond(update, context, text, tournament_list_kb(items))


async def _view(update, context, tid: int):
    c, uid = deps(context), update.effective_user.id
    t = await c.repo.get_tournament(tid)
    if not t:
        return await respond(update, context, "Tournament not found.", None)
    players = await c.repo.tournament_players(tid)
    names = {p["user_id"]: p["name"] for p in players}
    if t["winner_id"] and t["winner_id"] not in names:
        names[t["winner_id"]] = await c.repo.display_name(t["winner_id"])
    joined = any(p["user_id"] == uid for p in players)
    await respond(update, context, texts.tournament_text(t, players, names),
                  tournament_kb(t, joined, uid in settings.admin_ids))


@guard()
async def tournaments_cmd(update, context):
    await _list(update, context)


@guard()
async def tournament_cb(update, context):
    c, uid = deps(context), update.effective_user.id
    parts = update.callback_query.data.split(":")
    act = parts[1]
    if act == "list":
        await ack(update)
        return await _list(update, context)
    tid = int(parts[2])
    if act == "view":
        await ack(update)
    elif act == "join":
        res = await c.repo.tournament_join(tid, uid)
        await ack(update, {"ok": "✅ Registered! You'll be notified when it starts.", "full": "Tournament is full.",
                           "dup": "You are already registered.", "closed": "Registration is closed.",
                           "missing": "Tournament not found."}[res], True)
    elif act == "leave":
        ok = await c.repo.tournament_leave(tid, uid)
        await ack(update, "You left the tournament." if ok else "Cannot leave now.", True)
    elif act in ("start", "cancel"):
        if uid not in settings.admin_ids:
            return await ack(update, "⛔ Admins only.", True)
        msg = await (c.tournaments.start(tid, uid) if act == "start" else c.tournaments.cancel(tid, uid))
        await ack(update, msg, True)
    await _view(update, context, tid)


def register(app) -> None:
    app.add_handler(CommandHandler("tournaments", tournaments_cmd))
    app.add_handler(CallbackQueryHandler(tournament_cb, pattern=r"^t:"))
