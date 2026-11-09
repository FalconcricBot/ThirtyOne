from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from keyboards.main_menu import help_kb, home_kb, main_menu_kb, play_menu_kb
from keyboards.profile_keyboard import profile_kb
from ui import texts
from utils.decorators import ack, deps, guard, respond


async def send_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    c = deps(context)
    p = await c.repo.get_player(update.effective_user.id)
    await respond(update, context, texts.main_menu_text(p, c.announcement), main_menu_kb())


@guard()
async def menu_cmd(update, context):
    await send_home(update, context)


@guard()
async def help_cmd(update, context):
    await respond(update, context, texts.help_text(), help_kb())


@guard()
async def rules_cmd(update, context):
    await respond(update, context, texts.rules_text(), home_kb())


@guard()
async def play_cmd(update, context):
    from keyboards.thirty_one_keyboard import games_menu_kb
    from ui.thirty_one_texts import games_menu_text
    await respond(update, context, games_menu_text(), games_menu_kb())


@guard()
async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ack(update)
    action = update.callback_query.data.split(":")[1]
    c = deps(context)
    context.user_data.pop("await", None)
    if action == "home":
        await send_home(update, context)
    elif action == "games":
        from keyboards.thirty_one_keyboard import games_menu_kb
        from ui.thirty_one_texts import games_menu_text
        await respond(update, context, games_menu_text(), games_menu_kb())
    elif action == "play":
        await respond(update, context, "🎮 <b>SELECT GAME MODE</b>", play_menu_kb())
    elif action == "help":
        await respond(update, context, texts.help_text(), help_kb())
    elif action == "rules":
        await respond(update, context, texts.rules_text(), home_kb())
    elif action == "ach":
        uid = update.effective_user.id
        await respond(update, context, texts.achievements_text(await c.repo.achievements(uid)), profile_kb())
    elif action == "profile":
        from handlers.profile import send_profile
        await send_profile(update, context)


def register(app) -> None:
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("play", play_cmd))
    app.add_handler(CommandHandler("games", play_cmd))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern=r"^m:"))
