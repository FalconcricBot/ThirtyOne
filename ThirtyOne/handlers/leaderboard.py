from telegram.ext import CallbackQueryHandler, CommandHandler

from telegram.constants import ChatType

from keyboards.misc_keyboard import LB_TABS, group_board_kb, leaderboard_kb
from ui import texts
from utils.decorators import ack, deps, guard, respond

PER_PAGE = 10
KINDS = {k for k, _ in LB_TABS}


async def show(update, context, kind: str, page: int):
    c, uid = deps(context), update.effective_user.id
    ids = None
    if kind == "friends":
        ids = [f["id"] for f in await c.repo.friends(uid)] + [uid]
    rows, total = await c.repo.leaderboard(kind, PER_PAGE, page * PER_PAGE, ids)
    pages = max(1, -(-total // PER_PAGE))
    await respond(update, context, texts.leaderboard_text(kind, rows, page, total, PER_PAGE, uid),
                  leaderboard_kb(kind, page, pages))


@guard()
async def leaderboard_cmd(update, context):
    await show(update, context, "global", 0)


@guard()
async def leaderboard_cb(update, context):
    await ack(update)
    _, kind, page = update.callback_query.data.split(":")
    if kind in KINDS:
        await show(update, context, kind, max(0, int(page)))


async def _group_board(update, context, game: str):
    c, chat = deps(context), update.effective_chat
    rows = await c.repo.group_leaderboard(chat.id, game)
    await respond(update, context, texts.group_board_text(chat.title, game, rows, update.effective_user.id), group_board_kb(game))


@guard()
async def groupboard_cmd(update, context):
    if update.effective_chat.type == ChatType.PRIVATE:
        return await update.effective_message.reply_text(
            "👥 /groupboard shows the ranking of ONE group — use it inside your group chat (matches started there count).")
    await _group_board(update, context, "thirty_one")


@guard()
async def groupboard_cb(update, context):
    await ack(update)
    game = update.callback_query.data.split(":")[1]
    if game in ("briscola", "thirty_one"):
        await _group_board(update, context, game)


def register(app) -> None:
    app.add_handler(CommandHandler("groupboard", groupboard_cmd))
    app.add_handler(CallbackQueryHandler(groupboard_cb, pattern=r"^gl:(briscola|thirty_one)$"))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CallbackQueryHandler(leaderboard_cb, pattern=r"^lb:[a-z]+:\d+$"))
