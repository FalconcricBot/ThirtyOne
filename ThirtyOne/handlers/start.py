from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.constants import ChatType
from telegram.ext import CommandHandler, ContextTypes

from config import settings
from handlers.menu import send_home
from utils.decorators import deps, guard
from utils.validators import parse_room_code


@guard()
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    c = deps(context)
    if chat.type != ChatType.PRIVATE:
        kb = M([[B("🃏 Open Thirty One", url=f"https://t.me/{settings.bot_username}?start=hello")]])
        await update.message.reply_text("🃏 Start me in private chat first — your cards are delivered there!", reply_markup=kb)
        return
    arg = context.args[0] if context.args else ""
    if context.user_data.get("is_new"):
        await update.message.reply_text("🎉 Welcome to <b>Thirty One</b>! You start with 💰 100 coins.", parse_mode="HTML")
    if arg == "hand":                                  # button under the group turn-ping
        if await c.games31.resend_hand(user.id) or await c.games.resend_hand(user.id):
            return
        await update.message.reply_text("You have no running match right now. Use /games to start one!")
    if arg.startswith("room_"):
        code = parse_room_code(arg[5:])
        if code:
            from handlers.room import join_room_flow
            await join_room_flow(update, context, code)
            return
    if arg.startswith("ref_") and arg[4:].isdigit() and int(arg[4:]) != user.id:
        from handlers.friends import send_friend_request
        await send_friend_request(context, user.id, int(arg[4:]), reply_to=update)
    await send_home(update, context)


def register(app) -> None:
    app.add_handler(CommandHandler("start", start))
