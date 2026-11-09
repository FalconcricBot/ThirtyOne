"""In-game callbacks: card plays, score, leave/forfeit, rematch, replay, spectating."""
from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from keyboards.misc_keyboard import spectate_list_kb
from utils.decorators import ack, deps, guard, reply, respond


@guard()
async def play_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, gid, ver, code = update.callback_query.data.split(":")
    alert = await deps(context).games.handle_move(update.effective_user.id, int(gid), int(ver), code)
    await ack(update, alert, alert is not None)


@guard()
async def score_cb(update, context):
    c = deps(context)
    txt = c.games.score_text(update.effective_user.id)
    await ack(update, txt or "No running match.", True)


@guard()
async def hand_cmd(update, context):
    c = deps(context)
    ok = await c.games31.resend_hand(update.effective_user.id) or await c.games.resend_hand(update.effective_user.id)
    if not ok:
        await reply(update, "You are not in a running match. Use /play to start one.")


@guard()
async def score_cmd(update, context):
    c = deps(context)
    txt = c.games31.score_text(update.effective_user.id) or c.games.score_text(update.effective_user.id)
    await reply(update, txt or "You are not in a running match.")


@guard()
async def leave_cb(update, context):
    c, uid = deps(context), update.effective_user.id
    parts = update.callback_query.data.split(":")
    if parts[1] == "no":
        await ack(update, "Good luck!")
        return await update.callback_query.message.delete()
    if parts[1] == "yes":
        await ack(update)
        ok = await c.games.forfeit(uid)
        return await respond(update, context, "🏳 You left the match." if ok else "That match is already over.", None)
    # lv:<gid> -> ask for confirmation
    await ack(update)
    kb = c.games.ask_leave(uid)
    if kb:
        await context.bot.send_message(update.effective_chat.id, "🏳 Leave the running match? You will forfeit.", reply_markup=kb)


@guard()
async def rematch_cb(update, context):
    msg = await deps(context).games.rematch_vote(update.effective_user.id, int(update.callback_query.data.split(":")[1]))
    await ack(update, msg, True)


@guard()
async def replay_cb(update, context):
    await ack(update)
    _, gid, idx = update.callback_query.data.split(":")
    page = await deps(context).games.replay_page(int(gid), int(idx))
    if page is None:
        return await reply(update, "Replay not available.")
    await respond(update, context, *page)


@guard()
async def replay_cmd(update, context):
    gid = int(update.message.text.split()[0].split("@")[0].split("_")[1])
    page = await deps(context).games.replay_page(gid, 0)
    if page is None:
        return await reply(update, "Replay not available.")
    await update.message.reply_text(page[0], parse_mode="HTML", reply_markup=page[1])


@guard()
async def spectate_cb(update, context):
    c, uid = deps(context), update.effective_user.id
    arg = update.callback_query.data.split(":")[1]
    if arg == "stop":
        c.games.stop_watching(uid)
        await ack(update, "Stopped watching.")
        return await update.callback_query.message.delete()
    if arg == "list":
        await ack(update)
        games = c.games.public_games()
        return await respond(update, context, "👀 <b>LIVE MATCHES</b>\n" + ("Pick one to watch:" if games else "No live matches right now."),
                             spectate_list_kb(games))
    err = await c.games.spectate(uid, int(arg))
    await ack(update, err or "👀 Watching — updates arrive in this chat.", bool(err))


@guard(private=True)
async def spectate_cmd(update, context):
    games = deps(context).games.public_games()
    await update.message.reply_text("👀 <b>LIVE MATCHES</b>\n" + ("Pick one to watch:" if games else "No live matches right now."),
                                    parse_mode="HTML", reply_markup=spectate_list_kb(games))


def register(app) -> None:
    app.add_handler(CallbackQueryHandler(play_card_cb, pattern=r"^g:\d+:\d+:[A3KQJ76542][HDCS]$"))
    app.add_handler(CallbackQueryHandler(score_cb, pattern=r"^g:score:\d+$"))
    app.add_handler(CommandHandler("hand", hand_cmd))
    app.add_handler(CommandHandler("score", score_cmd))
    app.add_handler(CommandHandler("spectate", spectate_cmd))
    app.add_handler(CallbackQueryHandler(leave_cb, pattern=r"^lv:"))
    app.add_handler(CallbackQueryHandler(rematch_cb, pattern=r"^rm:\d+$"))
    app.add_handler(CallbackQueryHandler(replay_cb, pattern=r"^rp:\d+:\d+$"))
    app.add_handler(MessageHandler(filters.Regex(r"^/replay_\d+"), replay_cmd))
    app.add_handler(CallbackQueryHandler(spectate_cb, pattern=r"^sp:"))
